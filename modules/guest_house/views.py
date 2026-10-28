import re
import csv
import io
from datetime import date, datetime, timedelta

from flask import Blueprint, Response, abort, flash, g, redirect, render_template, request, url_for
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from core import approvals
from core.access import can, holders
from core.db import db
from core.mail import send_mail
from core.models import Activity, ApprovalTask, Notification, log_activity
from core.notify import mark_read, notify
from core.registry import get_setting
from core.security import permission_required

from .models import (BOOKED, EXPENSES_BY, STATUSES, STAY_TYPES, TRIP_TYPES, VISIT_TYPES,
                     Airport, ExpenseBorneBy, Guest, GuestHouse, GuestRequest,
                     FoodLocation, Hotel, Location, RailwayStation, Room, Trip, Vehicle, VisitPurpose, room_board, room_conflicts, vehicle_conflicts)

CODE = "guest_house"
bp = Blueprint(CODE, __name__, template_folder="templates")
NEEDS = ("need_guest_house", "need_hotel", "need_vehicle", "need_food", "need_ticket")


def get_visit_types():
    try:
        active = [p.name for p in VisitPurpose.query.filter_by(is_active=True).order_by(VisitPurpose.name).all()]
        if active:
            return active
    except Exception:
        pass
    return VISIT_TYPES


def get_expenses_by():
    try:
        active = [e.name for e in ExpenseBorneBy.query.filter_by(is_active=True).order_by(ExpenseBorneBy.name).all()]
        if active:
            return active
    except Exception:
        pass
    return EXPENSES_BY


def get_locations():
    try:
        return Location.query.filter_by(is_active=True).order_by(Location.point_name).all()
    except Exception:
        return []


def get_food_locations():
    try:
        return FoodLocation.query.filter_by(is_active=True).order_by(FoodLocation.name).all()
    except Exception:
        return []


def get_airports():
    try:
        return Airport.query.filter_by(is_active=True).order_by(Airport.city, Airport.name).all()
    except Exception:
        return []


def get_railway_stations():
    try:
        return RailwayStation.query.filter_by(is_active=True).order_by(RailwayStation.city, RailwayStation.name).all()
    except Exception:
        return []


def P(*perms):
    return permission_required(CODE, *perms)


def approval_record(ref_id):
    return db.session.get(GuestRequest, ref_id)


def user_requests(emp):
    return GuestRequest.query.filter_by(applicant_id=emp.employee_id).order_by(GuestRequest.updated_at.desc()).all()


def badge(emp):
    n = len(approvals.pending_for(emp, CODE))
    if can(emp, CODE, "desk"):
        n += GuestRequest.query.filter_by(status="approved").count()
    return n


def _parse_dt(value):
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M")
    except (TypeError, ValueError):
        return None


def _num(value):
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


def _get(req_id):
    return db.session.get(GuestRequest, req_id) or abort(404)


def _desk():
    return holders(CODE, "desk")


def _link(req):
    return url_for("guest_house.request_view", req_id=req.id)


def _can_view(req):
    u = g.user
    if req.applicant_id == u.employee_id or any(can(u, CODE, p) for p in ("desk", "reports", "admin")):
        return True
    return ApprovalTask.query.filter(ApprovalTask.app_code == CODE, ApprovalTask.ref_id == req.id,
                                     ApprovalTask.candidates.contains(f",{u.employee_id},", autoescape=True)).count() > 0


# ------------------------------------------------------------------ approval outcome hook
def on_approval(ref_id, outcome, actor, remarks):
    req = db.session.get(GuestRequest, ref_id)
    req.status, req.decided_at = outcome, datetime.now()
    log_activity(CODE, req.id, actor, f"Request {outcome}", remarks)
    words = {"approved": "approved", "rejected": "rejected", "returned": "sent back to you for changes"}[outcome]

    applicant_body = (
        f"Dear {req.applicant.name},\n\n"
        f"Your guest requisition {req.req_no} has been {words}.\n"
        + (f"Remarks: {remarks}\n" if remarks else "")
        + ("It has been forwarded to the Administration Desk for arrangement.\n" if outcome == "approved" else "")
        + "\nBest regards,\nAdmin"
    )
    hierarchy = get_applicant_hierarchy(req)
    notify([req.applicant], CODE, req.id, f"{req.req_no} {words}", _link(req),
           applicant_body, kind="action" if outcome == "returned" else "update",
           cc_people=hierarchy, include_link_in_email=False)

    if outcome == "approved":
        desk_body = (
            f"Dear Administration Desk,\n\n"
            f"Guest requisition {req.req_no} has been approved.\n\n"
            f"Applicant: {req.applicant.name} ({req.department or '-'})\n"
            f"First Arrival: {req.first_arrival:%d %b %Y %H:%M if req.first_arrival else '-'}\n"
            f"Guests: {len(req.guests)}\n\n"
            f"Please proceed with the arrangements in Docket.\n\n"
            f"Best regards,\nAdmin"
        )
        notify(_desk(), CODE, req.id, f"{req.req_no} approved - arrangement needed",
               url_for("guest_house.arrange", req_id=req.id),
               desk_body, kind="action", include_link_in_email=False)


# ------------------------------------------------------------------ pages
@bp.get("/")
@P("use", "desk", "reports", "masters")
def index():
    if can(g.user, CODE, "desk") or can(g.user, CODE, "reports"):
        return redirect(url_for("guest_house.dashboard"))
    return redirect(url_for("guest_house.my_requests"))


@bp.get("/requests")
@P("use")
def my_requests():
    status = request.args.get("status", "")
    q = GuestRequest.query.filter_by(applicant_id=g.user.employee_id)
    if status:
        q = q.filter_by(status=status)
    return render_template("guest_house/my_requests.html", reqs=q.order_by(GuestRequest.id.desc()).all(),
                           statuses=STATUSES, status=status)


def _read_form(req):
    """Fill req + guests from the submitted form. Returns a list of errors."""
    with db.session.no_autoflush:  # half-filled guests must not be flushed by the lookups below
        return _read_form_fields(req)


def _read_form_fields(req):
    f = request.form
    errors = []
    valid_visit_types = set(get_visit_types())
    if req.visit_type:
        valid_visit_types.add(req.visit_type)
    req.visit_type = f.get("visit_type") if f.get("visit_type") in valid_visit_types else ""
    req.purpose = f.get("purpose", "").strip()
    req.organisation = f.get("organisation", "").strip()
    # expenses_by is set by Admin Desk, default to existing or Company
    if not req.expenses_by:
        req.expenses_by = "Company"
    for need in NEEDS:
        setattr(req, need, f.get(need) == "1")
    for note in ("vehicle_note", "food_note", "ticket_note", "other_note"):
        setattr(req, note, f.get(note, "").strip())

    if not req.visit_type:
        errors.append("Choose the visit type.")
    if not req.purpose:
        errors.append("Remarks are required.")
    if req.need_guest_house and req.need_hotel and not req.other_note:
        errors.append("Both guest house and hotel are requested - explain the split in 'Anything else'.")
    if req.need_ticket:
        t_mode = f.get("travel_mode", "").strip() or req.travel_mode
        if not t_mode:
            errors.append("Select the travel mode (Air / Rail / Flight).")
        elif not req.ticket_note:
            req.ticket_note = f"Mode: {t_mode}"
    if req.need_vehicle and not req.vehicle_note:
        errors.append("Describe the vehicle need (pickup point, timing, local use).")

    now = datetime.now()
    earliest = None if get_setting(CODE, "allow_backdated") else \
        now + timedelta(hours=get_setting(CODE, "min_notice_hours"))
    max_days = get_setting(CODE, "max_stay_days")
    cols = ["g_name", "g_gender", "g_mobile", "g_email", "g_org", "g_designation", "g_arrival", "g_departure"]
    rows = list(zip(*(f.getlist(c) for c in cols)))
    req.guests = []
    for n, (name, gender, mobile, email, org, desig, arr, dep) in enumerate(rows, 1):
        if not any(x.strip() for x in (name, mobile, email, arr, dep)):
            continue  # blank row
        guest = Guest(name=name.strip(), gender=gender, mobile=mobile.strip(), email=email.strip().lower(),
                      organisation=org.strip() or req.organisation, designation=desig.strip(),
                      arrival=_parse_dt(arr), departure=_parse_dt(dep))
        req.guests.append(guest)
        label = f"Guest {n}"
        if not guest.name:
            errors.append(f"{label}: name is required.")
        if not guest.arrival or not guest.departure:
            errors.append(f"{label}: arrival and departure date/time are required.")
            continue
        if guest.departure <= guest.arrival:
            errors.append(f"{label}: departure must be after arrival.")
        if not get_setting(CODE, "allow_backdated"):
            now_floored = now.replace(second=0, microsecond=0) - timedelta(minutes=1)
            if guest.arrival < now_floored:
                errors.append(f"{label}: arrival is too soon or in the past (backdated).")
            if guest.departure < now_floored:
                errors.append(f"{label}: departure is in the past (backdated).")
            min_notice = get_setting(CODE, "min_notice_hours")
            if min_notice > 0 and guest.arrival < now_floored + timedelta(hours=min_notice):
                errors.append(f"{label}: arrival is too soon or in the past (minimum notice of {min_notice} hour(s) required).")
        if (guest.departure - guest.arrival).days > max_days:
            errors.append(f"{label}: stay is longer than {max_days} days.")
        if guest.mobile:
            clean_mobile = re.sub(r"[\s\-\(\)]", "", guest.mobile)
            if clean_mobile.startswith("+91"):
                clean_mobile = clean_mobile[3:]
            elif clean_mobile.startswith("0") and len(clean_mobile) == 11:
                clean_mobile = clean_mobile[1:]
            if not (clean_mobile.replace("+", "").isdigit() and 10 <= len(clean_mobile.replace("+", "")) <= 13):
                errors.append(f"{label}: mobile number '{guest.mobile}' is invalid. Please enter a valid 10-digit number.")
        if guest.email:
            if not re.match(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$", guest.email):
                errors.append(f"{label}: email address '{guest.email}' is invalid.")
    if not req.guests:
        errors.append("Add at least one guest.")
    if len(req.guests) > get_setting(CODE, "max_guests"):
        errors.append(f"At most {get_setting(CODE, 'max_guests')} guests per request.")

    return errors


def _submit(req, is_resubmit):
    """Start (or restart) approvals. Returns an error string or None."""
    req.department = g.user.department
    req.submitted_at = datetime.now()
    req.status = "pending"
    db.session.flush()
    if not req.req_no:
        req.req_no = f"{get_setting(CODE, 'request_prefix')}-{req.submitted_at:%Y}-{req.id:05d}"
    try:
        outcome = approvals.start(CODE, req.id, g.user, req.approval_context())
    except approvals.ApprovalError as exc:
        return str(exc)
    log_activity(CODE, req.id, g.user, "Resubmitted" if is_resubmit else "Submitted")
    # Always notify Admin Desk on new request submission
    needs = []
    if req.need_guest_house: needs.append("Guest house")
    if req.need_hotel: needs.append("Hotel")
    if req.need_vehicle: needs.append("Vehicle")
    if req.need_food: needs.append("Food")
    if req.need_ticket: needs.append("Ticket")
    needs_str = ", ".join(needs) if needs else "None"

    first_arr = req.first_arrival.strftime('%d %b %Y %H:%M') if req.first_arrival else '-'
    last_dep = req.last_departure.strftime('%d %b %Y %H:%M') if req.last_departure else '-'

    desk_body = (
        f"Dear Admin,\n\n"
        f"A new guest requisition {req.req_no} has come, please check.\n\n"
        f"Request No: {req.req_no}\n"
            f"Applicant: {req.applicant.name} ({req.department or '-'})\n"
        f"Visit Type: {req.visit_type} - {req.purpose}\n"
        f"Guests: {len(req.guests)} guest(s)\n"
        f"Stay: {first_arr} to {last_dep}\n"
        f"Requirements: {needs_str}\n"
        f"Status: Awaiting approval\n\n"
        f"Best regards,\nAdmin"
    )
    notify(_desk(), CODE, req.id, f"New request {req.req_no} has come, please check", _link(req),
           desk_body, kind="update", include_link_in_email=False)

    # Acknowledge to requester
    ack_body = (
        f"Dear {req.applicant.name},\n\n"
        f"Your guest requisition {req.req_no} has been submitted successfully.\n\n"
        f"Visit: {req.visit_type} - {req.purpose}\n"
        f"Stay: {first_arr} to {last_dep}\n"
        f"Status: Pending approval\n\n"
        f"You will be notified as each approver in your hierarchy reviews the request.\n\n"
        f"Best regards,\nAdmin"
    )
    hierarchy = get_applicant_hierarchy(req)
    notify([req.applicant], CODE, req.id, f"Requisition {req.req_no} submitted", _link(req),
           ack_body, kind="update", cc_people=hierarchy, include_link_in_email=False)

    if outcome == "approved":  # empty chain
        on_approval(req.id, "approved", g.user, "No approval steps configured")

    return None


def _form_page(req, errors=(), copy_of=None):
    for e in errors:
        flash(e, "error")
    with db.session.no_autoflush:
        guests = req.guests or [Guest()]
        chain = approvals.plan(CODE, g.user, req.approval_context())
        vt = get_visit_types()
        if req.visit_type and req.visit_type not in vt:
            vt = [req.visit_type] + [x for x in vt if x != req.visit_type]
        now = datetime.now()
        allow_backdated = get_setting(CODE, "allow_backdated")
        min_notice = get_setting(CODE, "min_notice_hours")
        min_arrival = None if allow_backdated else (now + timedelta(hours=min_notice)).strftime("%Y-%m-%dT%H:%M")
        min_departure = None if allow_backdated else now.strftime("%Y-%m-%dT%H:%M")
        return render_template("guest_house/request_form.html", req=req, guests=guests, chain=chain, copy_of=copy_of,
                               visit_types=vt, max_guests=get_setting(CODE, "max_guests"),
                               allow_backdated=allow_backdated, min_arrival=min_arrival, min_departure=min_departure,
                               locations=get_locations(), food_locations=get_food_locations(),
                               airports=get_airports(), railway_stations=get_railway_stations())


@bp.route("/requests/new", methods=["GET", "POST"])
@P("use")
def new_request():
    req = GuestRequest(applicant_id=g.user.employee_id, expenses_by="Company")
    if request.method == "POST":
        errors = _read_form(req)
        if errors:
            return _form_page(req, errors)
        db.session.add(req)
        error = _submit(req, is_resubmit=False)
        if error:
            db.session.rollback()
            return _form_page(req, [error])
        db.session.commit()
        flash(f"Request {req.req_no} submitted.", "success")
        return redirect(url_for("guest_house.request_view", req_id=req.id))

    source = db.session.get(GuestRequest, request.args.get("copy", type=int) or 0)
    if source and source.applicant_id == g.user.employee_id:  # "raise again" for recurring visitors
        for field in ("visit_type", "purpose", "organisation", "expenses_by", "cost_centre", *NEEDS,
                      "vehicle_note", "food_note", "ticket_note", "other_note"):
            setattr(req, field, getattr(source, field))
        req.guests = [Guest(name=s.name, gender=s.gender, mobile=s.mobile, email=s.email,
                            organisation=s.organisation, designation=s.designation) for s in source.guests]
        return _form_page(req, copy_of=source)
    return _form_page(req)


@bp.route("/requests/<int:req_id>/edit", methods=["GET", "POST"])
@P("use")
def edit_request(req_id):
    req = _get(req_id)
    if req.applicant_id != g.user.employee_id or req.status != "returned":
        abort(403)
    if request.method == "POST":
        errors = _read_form(req)
        error = errors or _submit(req, is_resubmit=True)
        if error:
            page = _form_page(req, errors or [error])
            db.session.rollback()
            return page
        db.session.commit()
        flash(f"{req.req_no} resubmitted.", "success")
        return redirect(url_for("guest_house.request_view", req_id=req.id))
    return _form_page(req)


@bp.get("/requests/<int:req_id>")
def request_view(req_id):
    req = _get(req_id)
    if not _can_view(req):
        abort(403)
    task = approvals.current_task(CODE, req.id)
    activity = Activity.query.filter_by(app_code=CODE, ref_id=req.id).order_by(Activity.created_at).all()
    if not (task and approvals.can_act(task, g.user)):  # keep "approval needed" unread until acted on
        mark_read(g.user, CODE, req.id)
        db.session.commit()
    return render_template(
        "guest_house/request_view.html", req=req, task=task, timeline=approvals.timeline(CODE, req.id),
        can_decide=bool(task and approvals.can_act(task, g.user)), activity=activity,
        is_desk=can(g.user, CODE, "desk"), can_cancel=_can_cancel(req), stay_types=STAY_TYPES,
        expenses_by=get_expenses_by())


@bp.post("/requests/<int:req_id>/update-expenses")
@P("desk")
def update_expenses(req_id):
    req = _get(req_id)
    val = request.form.get("expenses_by")
    valid_expenses = set(get_expenses_by())
    if val in valid_expenses:
        req.expenses_by = val
        req.cost_centre = request.form.get("cost_centre", "").strip()
        db.session.commit()
        log_activity(CODE, req.id, g.user, f"Updated expense bearer to {req.expenses_by}")
        flash("Expenses borne by updated.", "success")
    else:
        flash("Invalid expense bearer.", "error")
    return redirect(url_for("guest_house.request_view", req_id=req.id))


@bp.get("/requests/<int:req_id>/print")
def print_request(req_id):
    req = _get(req_id)
    if not _can_view(req):
        abort(403)
    approved = [t for t in approvals.timeline(CODE, req.id) if t.status == "approved"]
    return render_template("guest_house/print.html", req=req, approved=approved)


@bp.post("/requests/<int:req_id>/decide")
def decide(req_id):
    req = _get(req_id)
    task = approvals.current_task(CODE, req.id)
    if task is None or req.status != "pending":
        flash("This request is no longer awaiting approval.", "error")
        return redirect(url_for("guest_house.request_view", req_id=req.id))
    try:
        outcome = approvals.act(task, g.user, request.form.get("action"), request.form.get("remarks", ""))
    except approvals.ApprovalError as exc:
        flash(str(exc), "error")
        return redirect(url_for("guest_house.request_view", req_id=req.id))
    if outcome == "pending":
        log_activity(CODE, req.id, g.user, f"Approved: {task.label}", task.remarks)
    db.session.commit()
    flash(f"{req.req_no}: " + ("approved, moved to the next approver." if outcome == "pending"
                               else STATUSES[outcome] + "."), "success")
    return redirect(request.form.get("next") or url_for("guest_house.approvals_page"))


def _can_cancel(req):
    if req.status not in ("pending", "returned", "approved", "arranged") or req.anyone_checked_in:
        return False
    return req.applicant_id == g.user.employee_id or can(g.user, CODE, "desk")


@bp.post("/requests/<int:req_id>/cancel")
def cancel_request(req_id):
    req = _get(req_id)
    reason = request.form.get("reason", "").strip()
    if not _can_cancel(req):
        abort(403)
    if not reason:
        flash("Give a reason for cancelling.", "error")
        return redirect(url_for("guest_house.request_view", req_id=req.id))
    was_booked = req.status in BOOKED
    req.status, req.cancelled_at, req.cancel_reason = "cancelled", datetime.now(), reason
    approvals.cancel(CODE, req.id)  # rooms and vehicles free up automatically (status leaves BOOKED)
    log_activity(CODE, req.id, g.user, "Cancelled", reason)
    # Open "approval needed" notes for this request are void now.
    Notification.query.filter_by(app_code=CODE, ref_id=req.id, kind="action", read_at=None) \
        .update({"read_at": datetime.now()})
    hotels = {gst.hotel.name for gst in req.guests if gst.stay_type == "hotel" and gst.hotel}
    body = (f"Cancelled by {g.user.name}. Reason: {reason}\n"
            + (f"Cancel hotel bookings at: {', '.join(sorted(hotels))}\n" if hotels else "")
            + ("Release / cancel vehicle trips and hired vehicles." if req.trips else ""))
    people = (_desk() if was_booked else []) + [req.applicant]
    notify([p for p in people if p.employee_id != g.user.employee_id], CODE, req.id, f"{req.req_no} cancelled",
           _link(req), body)
    db.session.commit()
    flash(f"{req.req_no} cancelled.", "success")
    return redirect(url_for("guest_house.request_view", req_id=req.id))


@bp.get("/approvals")
def approvals_page():
    tasks = approvals.pending_for(g.user, CODE)
    pending = [(t, db.session.get(GuestRequest, t.ref_id)) for t in tasks]
    done = ApprovalTask.query.filter(ApprovalTask.app_code == CODE, ApprovalTask.acted_by_id == g.user.employee_id) \
        .order_by(ApprovalTask.acted_at.desc()).limit(30).all()
    history = [(t, db.session.get(GuestRequest, t.ref_id)) for t in done]
    return render_template("guest_house/approvals.html", pending=pending, history=history)


# ------------------------------------------------------------------ admin desk
@bp.get("/desk")
@P("desk")
def desk():
    now = datetime.now()
    today = now.date()

    # Parse date parameters
    date_param = request.args.get("date") or request.args.get("day")
    try:
        start_date = date.fromisoformat(date_param) if date_param else today
    except Exception:
        start_date = today

    days_count = 7
    try:
        if request.args.get("days"):
            days_count = max(3, min(30, int(request.args.get("days"))))
    except Exception:
        days_count = 7

    dates = [start_date + timedelta(days=i) for i in range(days_count)]
    prev_date = start_date - timedelta(days=days_count)
    next_date = start_date + timedelta(days=days_count)

    window_start = datetime.combine(start_date, datetime.min.time())
    window_end = datetime.combine(dates[-1] + timedelta(days=1), datetime.min.time())
    booking_statuses = ("approved", "arranged", "completed")

    # 1. Actionable queues
    to_arrange = GuestRequest.query.filter_by(status="approved").order_by(GuestRequest.decided_at).all()
    arranged = GuestRequest.query.filter_by(status="arranged").all()
    arranged.sort(key=lambda r: r.first_arrival or datetime.max)
    in_house = Guest.query.join(GuestRequest).filter(
        GuestRequest.status.in_(("arranged", "completed")),
        Guest.checked_in_at.isnot(None),
        Guest.checked_out_at.is_(None)
    ).all()
    awaiting_approval = GuestRequest.query.filter_by(status="pending").order_by(GuestRequest.id).all()

    # 2. Rooms Occupancy & Vacancy Grid
    houses = GuestHouse.query.order_by(GuestHouse.name).all()
    rooms = Room.query.join(GuestHouse).order_by(GuestHouse.name, Room.room_no).all()

    gh_guests = Guest.query.join(GuestRequest).filter(
        Guest.stay_type == "guest_house",
        Guest.room_id.isnot(None),
        GuestRequest.status.in_(booking_statuses),
        Guest.departure >= window_start,
        Guest.arrival < window_end
    ).all()

    room_grid = {}
    for h in houses:
        h_rooms = [r for r in rooms if r.guest_house_id == h.id]
        room_list = []
        for r in h_rooms:
            day_data = []
            for d in dates:
                d_start = datetime.combine(d, datetime.min.time())
                d_end = d_start + timedelta(days=1)
                r_guests = [
                    g for g in gh_guests
                    if g.room_id == r.id and (g.span(now)[0] < d_end and g.span(now)[1] > d_start)
                ]
                if not r.is_active:
                    st = "maintenance"
                elif r_guests:
                    st = "booked"
                else:
                    st = "vacant"

                occupied_beds = len(r_guests)
                available_beds = max(0, r.capacity - occupied_beds) if r.is_active else 0
                day_data.append({
                    "date": d,
                    "is_today": (d == today),
                    "status": st,
                    "guests": r_guests,
                    "occupied_beds": occupied_beds,
                    "available_beds": available_beds
                })
            room_list.append({
                "room": r,
                "days": day_data
            })
        room_grid[h] = room_list

    # 3. Vehicles Availability & Vacancy Grid
    vehicles = Vehicle.query.order_by(Vehicle.reg_no).all()
    trips = Trip.query.join(GuestRequest).filter(
        GuestRequest.status.in_(booking_statuses),
        Trip.end >= window_start,
        Trip.start < window_end
    ).all()

    vehicle_grid = []
    for v in vehicles:
        day_data = []
        for d in dates:
            d_start = datetime.combine(d, datetime.min.time())
            d_end = d_start + timedelta(days=1)
            v_trips = [
                t for t in trips
                if t.source == "company" and t.vehicle_id == v.id and t.start < d_end and t.end > d_start
            ]
            if not v.is_active:
                st = "maintenance"
            elif v_trips:
                st = "booked"
            else:
                st = "vacant"

            day_data.append({
                "date": d,
                "is_today": (d == today),
                "status": st,
                "trips": v_trips
            })
        vehicle_grid.append({
            "vehicle": v,
            "days": day_data
        })

    hired_trips = [t for t in trips if t.source == "hired"]

    # 4. Hotels Bookings Grid
    hotels = Hotel.query.order_by(Hotel.name).all()
    hotel_guests = Guest.query.join(GuestRequest).filter(
        Guest.stay_type == "hotel",
        GuestRequest.status.in_(booking_statuses),
        Guest.departure >= window_start,
        Guest.arrival < window_end
    ).all()

    hotel_grid = []
    for h in hotels:
        day_data = []
        for d in dates:
            d_start = datetime.combine(d, datetime.min.time())
            d_end = d_start + timedelta(days=1)
            h_guests = [
                g for g in hotel_guests
                if g.hotel_id == h.id and (g.span(now)[0] < d_end and g.span(now)[1] > d_start)
            ]
            day_data.append({
                "date": d,
                "is_today": (d == today),
                "status": "booked" if h_guests else "vacant",
                "guests": h_guests
            })
        hotel_grid.append({
            "hotel": h,
            "days": day_data
        })

    # 5. Summary statistics for today
    today_start = datetime.combine(today, datetime.min.time())
    today_end = today_start + timedelta(days=1)

    today_rooms_total = len(rooms)
    today_rooms_occupied = sum(
        1 for r in rooms
        if any(g for g in gh_guests if g.room_id == r.id and g.span(now)[0] < today_end and g.span(now)[1] > today_start)
    )
    today_rooms_maintenance = sum(1 for r in rooms if not r.is_active)
    today_rooms_vacant = max(0, today_rooms_total - today_rooms_occupied - today_rooms_maintenance)
    today_occupancy_pct = round((today_rooms_occupied / today_rooms_total * 100)) if today_rooms_total else 0

    today_vehicles_total = len(vehicles)
    today_vehicles_booked = sum(
        1 for v in vehicles
        if any(t for t in trips if t.source == "company" and t.vehicle_id == v.id and t.start < today_end and t.end > today_start)
    )
    today_vehicles_free = max(0, today_vehicles_total - today_vehicles_booked)

    stats = {
        "rooms_total": today_rooms_total,
        "rooms_occupied": today_rooms_occupied,
        "rooms_vacant": today_rooms_vacant,
        "rooms_maintenance": today_rooms_maintenance,
        "occupancy_pct": today_occupancy_pct,
        "vehicles_total": today_vehicles_total,
        "vehicles_booked": today_vehicles_booked,
        "vehicles_free": today_vehicles_free,
        "in_house_count": len(in_house),
        "to_arrange_count": len(to_arrange)
    }

    return render_template(
        "guest_house/desk.html",
        to_arrange=to_arrange,
        arranged=arranged,
        in_house=in_house,
        awaiting_approval=awaiting_approval,
        now=now,
        today=today,
        start_date=start_date,
        days_count=days_count,
        dates=dates,
        prev_date=prev_date,
        next_date=next_date,
        room_grid=room_grid,
        vehicle_grid=vehicle_grid,
        hired_trips=hired_trips,
        hotel_grid=hotel_grid,
        stats=stats
    )


def get_applicant_hierarchy(req):
    """Returns list of unique Employee objects representing the applicant's hierarchy (approval chain + reporting managers)."""
    hierarchy = {}
    applicant = req.applicant
    if not applicant:
        return []

    # 1. Reporting manager chain
    curr = applicant.manager
    seen_mgrs = {applicant.employee_id}
    while curr and curr.employee_id not in seen_mgrs:
        seen_mgrs.add(curr.employee_id)
        if curr.is_active and curr.email:
            hierarchy[curr.employee_id] = curr
        curr = curr.manager

    # 2. Approval tasks / approvers who approved or are candidates in the approval chain
    try:
        from core.models import ApprovalTask
        tasks = ApprovalTask.query.filter_by(app_code=CODE, ref_id=req.id).all()
        for t in tasks:
            if t.acted_by and t.acted_by.is_active and t.acted_by.email and t.acted_by.employee_id != applicant.employee_id:
                hierarchy[t.acted_by.employee_id] = t.acted_by
            for cand in t.candidate_people:
                if cand.is_active and cand.email and cand.employee_id != applicant.employee_id:
                    hierarchy[cand.employee_id] = cand
    except Exception:
        pass

    # 3. Approval org chart planned nodes for this applicant
    try:
        from core import approvals
        path = approvals.route(CODE, applicant)
        for node in path:
            for m in node.members:
                if m.is_active and m.email and m.employee_id != applicant.employee_id:
                    hierarchy[m.employee_id] = m
    except Exception:
        pass

    return list(hierarchy.values())


@bp.route("/requests/<int:req_id>/arrange", methods=["GET", "POST"])
@P("desk")
def arrange(req_id):
    req = _get(req_id)
    if req.status not in BOOKED:
        flash("Only approved requests can be arranged.", "error")
        return redirect(url_for("guest_house.request_view", req_id=req.id))
    if request.method == "POST":
        errors = _read_arrangement(req)
        finalize = request.form.get("action") == "finalize"
        if finalize and not errors:
            errors = _missing_for_finalize(req)
        if errors:
            for e in errors:
                flash(e, "error")
            page = _arrange_page(req)
            db.session.rollback()
            return page
        first_time = (req.status == "approved" and finalize) or (not req.arrangement_version)
        if finalize or req.status == "arranged":
            req.status = "arranged"
            req.arranged_by_id, req.arranged_at = g.user.employee_id, datetime.now()
            req.arrangement_version = (req.arrangement_version or 0) + 1
        ver = req.arrangement_version or 1
        action_label = f"Arrangement confirmed (v{ver})" if first_time else f"Arrangement updated (v{ver})"
        log_activity(CODE, req.id, g.user, action_label)
        db.session.flush()
        if req.status == "arranged":
            # Check what was arranged:
            has_gh = any(g.stay_type == "guest_house" for g in req.guests)
            has_vehicle = bool(req.trips)
            has_food = bool(req.food_arrangement and req.food_arrangement.strip())
            # Rule: send email when vehicle, guest house, or food is arranged.
            # In case of hotel only (no GH, vehicle, or food): do NOT send email.
            should_send_mail = (has_gh or has_vehicle or has_food)

            subject_title = f"{req.req_no}: arrangements {'confirmed' if first_time else 'updated'}"
            details = render_template("guest_house/arrangement_mail.txt", req=req)

            if should_send_mail:
                hierarchy = get_applicant_hierarchy(req)
                notify([req.applicant], CODE, req.id, subject_title, _link(req), details, cc_people=hierarchy, include_link_in_email=False)
                guest_emails = [x.email.strip() for x in req.guests if x.email and '@' in x.email and '.' in x.email.split('@')[-1]]
                if guest_emails:
                    send_mail(guest_emails, "Your visit: arrangements", details)
            else:
                # In case of hotel only: do NOT send email to anyone, create in-app notification only
                notify([req.applicant], CODE, req.id, subject_title, _link(req), details, email=False)

            # The desk's "arrangement needed" note is done.
            Notification.query.filter_by(app_code=CODE, ref_id=req.id, kind="action", read_at=None) \
                .filter(Notification.employee_id != req.applicant_id).update({"read_at": datetime.now()})
        db.session.commit()
        if finalize:
            if should_send_mail:
                flash(f"Arrangement {'confirmed' if first_time else 'updated'} (Version {ver}). Email sent to requester and CC'd to hierarchy.", "success")
            else:
                flash(f"Arrangement {'confirmed' if first_time else 'updated'} (Version {ver}). Hotel-only booking: in-app updated, no email sent.", "success")
        else:
            flash(f"Arrangement changes saved without sending email (Version {ver}).", "success")
        return redirect(url_for("guest_house.request_view", req_id=req.id))
    return _arrange_page(req)


def _arrange_page(req):
    with db.session.no_autoflush:
        return _render_arrange(req)


def _render_arrange(req):
    rooms = Room.query.join(GuestHouse).filter(Room.is_active, GuestHouse.is_active) \
        .order_by(GuestHouse.name, Room.room_no).all()
    # For each guest: which rooms are taken by someone else during their stay
    busy = {}
    for guest in req.guests:
        if guest.arrival and guest.departure:
            busy[guest.id] = {r.id: room_conflicts(r.id, guest.arrival, guest.departure, req.id)[:1] for r in rooms}
    vehicles = Vehicle.query.filter_by(is_active=True).order_by(Vehicle.reg_no).all()
    return render_template("guest_house/arrange.html", req=req, rooms=rooms, busy=busy, vehicles=vehicles,
                           hotels=Hotel.query.filter_by(is_active=True).order_by(Hotel.name).all(),
                           stay_types=STAY_TYPES, trip_types=TRIP_TYPES, expenses_by=get_expenses_by(),
                           locations=get_locations(), food_locations=get_food_locations(),
                           airports=get_airports(), railway_stations=get_railway_stations())


def _read_arrangement(req):
    with db.session.no_autoflush:
        return _read_arrangement_fields(req)


def _read_arrangement_fields(req):
    f = request.form
    errors = []
    req.food_arrangement = f.get("food_arrangement", "").strip()
    req.ticket_arrangement = f.get("ticket_arrangement", "").strip()
    req.desk_remarks = f.get("desk_remarks", "").strip()
    if "expenses_by" in f:
        valid_expenses = set(get_expenses_by())
        chosen = f.get("expenses_by")
        if chosen in valid_expenses:
            req.expenses_by = chosen
        req.cost_centre = f.get("cost_centre", "").strip()

    for guest in req.guests:
        p = f"g{guest.id}_"
        if guest.checked_out_at:
            continue  # history is frozen once the guest has left
        arrival, departure = _parse_dt(f.get(p + "arrival")), _parse_dt(f.get(p + "departure"))
        if arrival and departure and departure > arrival:
            if not guest.checked_in_at:
                guest.arrival = arrival
            guest.departure = departure  # extensions / early departures
        else:
            errors.append(f"{guest.name}: check the arrival / departure.")
        guest.stay_type = f.get(p + "stay_type") if f.get(p + "stay_type") in STAY_TYPES else None
        guest.remarks = f.get(p + "remarks", "").strip()
        guest.room_id = guest.hotel_id = None
        if guest.stay_type == "guest_house":
            room = db.session.get(Room, f.get(p + "room_id", type=int) or 0)
            if room is None or not room.is_active:
                errors.append(f"{guest.name}: choose an available guest house room.")
                continue
            guest.room_id, guest.room = room.id, room
            clash = room_conflicts(room.id, guest.arrival, guest.departure, req.id)
            if clash:
                c = clash[0]
                errors.append(f"{guest.name}: room {room} is held by {c.name} ({c.request.req_no}) "
                              f"until {c.span()[1]:%d %b %H:%M}.")
        elif guest.stay_type == "hotel":
            hotel = db.session.get(Hotel, f.get(p + "hotel_id", type=int) or 0)
            if hotel is None:
                errors.append(f"{guest.name}: choose a hotel.")
            guest.hotel_id = hotel.id if hotel else None
            guest.hotel_booking_ref = f.get(p + "booking_ref", "").strip()
            guest.hotel_room_no = f.get(p + "hotel_room_no", "").strip()
            guest.hotel_cost = _num(f.get(p + "hotel_cost"))

    # Sharing inside this request: never more people in a room at once than it has beds.
    in_rooms = [x for x in req.guests if x.stay_type == "guest_house" and x.room_id and x.arrival and x.departure]
    for guest in in_rooms:
        together = [o for o in in_rooms if o.room_id == guest.room_id
                    and o.arrival < guest.departure and guest.arrival < o.departure]
        if len(together) > guest.room.capacity:
            errors.append(f"Room {guest.room} has {guest.room.capacity} bed(s) but {len(together)} guests overlap in it.")
            break

    # Trips are replaced wholesale from the form rows.
    cols = ["t_type", "t_pickup", "t_drop", "t_start", "t_end", "t_source", "t_vehicle", "t_vendor",
            "t_hired_no", "t_hired_type", "t_driver", "t_driver_phone", "t_cost", "t_remarks"]
    new_trips = []
    for n, row in enumerate(zip(*(f.getlist(c) for c in cols)), 1):
        (ttype, pickup, drop, start, end, source, vehicle_id, vendor, hired_no, hired_type,
         driver, driver_phone, cost, remarks) = row
        if not (start or end or pickup or drop):
            continue
        trip = Trip(trip_type=ttype if ttype in TRIP_TYPES else TRIP_TYPES[0], pickup=pickup.strip(), drop=drop.strip(),
                    start=_parse_dt(start), end=_parse_dt(end), source=source if source in ("company", "hired") else "company",
                    vendor=vendor.strip(), hired_vehicle_no=hired_no.strip().upper(), hired_vehicle_type=hired_type.strip(),
                    driver_name=driver.strip(), driver_phone=driver_phone.strip(), cost=_num(cost), remarks=remarks.strip())
        new_trips.append(trip)
        if trip.driver_phone:
            clean_dphone = re.sub(r"[\s\-\(\)]", "", trip.driver_phone)
            if clean_dphone.startswith("+91"):
                clean_dphone = clean_dphone[3:]
            elif clean_dphone.startswith("0") and len(clean_dphone) == 11:
                clean_dphone = clean_dphone[1:]
            if not (clean_dphone.replace("+", "").isdigit() and 10 <= len(clean_dphone.replace("+", "")) <= 13):
                errors.append(f"Trip {n}: driver phone '{trip.driver_phone}' is invalid. Please enter a valid 10-digit number.")
        if not trip.start or not trip.end or trip.end <= trip.start:
            errors.append(f"Trip {n}: start and end time are required and end must be after start.")
            continue
        if trip.source == "company":
            vehicle = db.session.get(Vehicle, int(vehicle_id)) if vehicle_id.isdigit() else None
            if vehicle is None or not vehicle.is_active:
                errors.append(f"Trip {n}: choose a company vehicle, or switch to hired.")
                continue
            trip.vehicle_id, trip.vehicle = vehicle.id, vehicle
            trip.driver_name = trip.driver_name or vehicle.driver_name
            trip.driver_phone = trip.driver_phone or vehicle.driver_phone
            clash = vehicle_conflicts(vehicle.id, trip.start, trip.end, req.id)
            own = [t for t in new_trips[:-1] if t.vehicle_id == vehicle.id and t.start and t.end
                   and t.start < trip.end and trip.start < t.end]
            if clash:
                c = clash[0]
                errors.append(f"Trip {n}: {vehicle.reg_no} is booked for {c.request.req_no} "
                              f"{c.start:%d %b %H:%M}-{c.end:%H:%M}. Pick another vehicle or hire one.")
            elif own:
                errors.append(f"Trip {n}: {vehicle.reg_no} overlaps another trip in this request.")
        elif not (trip.vendor or trip.hired_vehicle_no):
            errors.append(f"Trip {n}: enter the hired vehicle's vendor or number.")
    req.trips = new_trips
    return errors


def _missing_for_finalize(req):
    errors = []
    if (req.need_guest_house or req.need_hotel) and any(not x.stay_type for x in req.guests):
        errors.append("Set the stay (guest house / hotel / not required) for every guest.")
    if req.need_vehicle and not req.trips:
        errors.append("Vehicle was requested - add at least one trip.")
    if req.need_food and not req.food_arrangement:
        errors.append("Food was requested - fill the food arrangement.")
    if req.need_ticket and not req.ticket_arrangement:
        errors.append("Ticket was requested - fill the ticket arrangement.")
    return errors


@bp.post("/guests/<int:guest_id>/<action>")
@P("desk")
def guest_status(guest_id, action):
    guest = db.session.get(Guest, guest_id) or abort(404)
    req = guest.request
    if req.status != "arranged":
        flash("Confirm the arrangement before checking guests in.", "error")
    elif action == "check-in" and not guest.checked_in_at:
        guest.checked_in_at = datetime.now()
        log_activity(CODE, req.id, g.user, f"Checked in: {guest.name}")
    elif action == "check-out" and guest.checked_in_at and not guest.checked_out_at:
        guest.checked_out_at = datetime.now()
        log_activity(CODE, req.id, g.user, f"Checked out: {guest.name}")
        if all(x.checked_out_at or x.stay_type in (None, "none") for x in req.guests):
            req.status, req.completed_at = "completed", datetime.now()
            log_activity(CODE, req.id, g.user, "Completed - all guests checked out")
    db.session.commit()
    return redirect(request.form.get("next") or url_for("guest_house.request_view", req_id=req.id))


@bp.post("/requests/<int:req_id>/complete")
@P("desk")
def complete(req_id):
    """Close a request (e.g. no-show, or visit done without stays). Releases anything still held."""
    req = _get(req_id)
    if req.status != "arranged":
        abort(400)
    now = datetime.now()
    for guest in req.guests:
        if guest.checked_in_at and not guest.checked_out_at:
            guest.checked_out_at = now
    req.status, req.completed_at = "completed", now
    log_activity(CODE, req.id, g.user, "Marked completed", request.form.get("remarks", ""))
    db.session.commit()
    return redirect(url_for("guest_house.request_view", req_id=req.id))


# ------------------------------------------------------------------ dashboard & reports
@bp.get("/dashboard")
@P("reports", "desk")
def dashboard():
    day = request.args.get("day")
    try:
        day = date.fromisoformat(day) if day else date.today()
    except ValueError:
        day = date.today()
    board = room_board(day)
    active_rooms = [r for r, _ in board if r.is_active and r.guest_house.is_active]
    occupied = [r for r, gs in board if gs]
    month_start = day.replace(day=1)
    month_req = GuestRequest.query.filter(GuestRequest.submitted_at >= month_start).all()
    start, end = datetime.combine(day, datetime.min.time()), datetime.combine(day + timedelta(days=1), datetime.min.time())
    live = Guest.query.join(GuestRequest).filter(GuestRequest.status.in_(BOOKED + ("completed",)))
    month_guests = live.filter(Guest.arrival >= month_start).all()
    trips_month = Trip.query.join(GuestRequest).filter(GuestRequest.status.in_(BOOKED + ("completed",)),
                                                       Trip.start >= month_start).all()
    by_dept = db.session.query(GuestRequest.department, func.count()).filter(GuestRequest.submitted_at >= month_start) \
        .group_by(GuestRequest.department).order_by(func.count().desc()).limit(8).all()
    upcoming = live.filter(Guest.arrival >= start, Guest.arrival < start + timedelta(days=7),
                           GuestRequest.status.in_(BOOKED)).order_by(Guest.arrival).all()
    stats = {
        "rooms": len(active_rooms),
        "occupied": len([r for r in occupied if r in active_rooms]),
        "maintenance": len(board) - len(active_rooms),
        "in_house": live.filter(Guest.checked_in_at.isnot(None), Guest.checked_out_at.is_(None)).count(),
        "arrivals": live.filter(Guest.arrival >= start, Guest.arrival < end).count(),
        "departures": live.filter(Guest.departure >= start, Guest.departure < end).count(),
        "pending": GuestRequest.query.filter_by(status="pending").count(),
        "to_arrange": GuestRequest.query.filter_by(status="approved").count(),
        "month_requests": len(month_req),
        "month_guests": len(month_guests),
        "month_rejected": len([r for r in month_req if r.status in ("rejected", "cancelled")]),
        "hotel_guests": len([x for x in month_guests if x.stay_type == "hotel"]),
        "hotel_cost": sum(x.hotel_cost or 0 for x in month_guests if x.stay_type == "hotel"),
        "company_trips": len([t for t in trips_month if t.source == "company"]),
        "hired_trips": len([t for t in trips_month if t.source == "hired"]),
        "hired_cost": sum(t.cost or 0 for t in trips_month if t.source == "hired"),
        "vehicles_out_today": len({t.vehicle_id for t in trips_month if t.vehicle_id and t.start < end and t.end > start}),
    }
    stats["free"] = stats["rooms"] - stats["occupied"]
    stats["occupancy"] = round(100 * stats["occupied"] / stats["rooms"]) if stats["rooms"] else 0
    houses = {}
    for room, guests in board:
        houses.setdefault(room.guest_house, []).append((room, guests))
    return render_template("guest_house/dashboard.html", day=day, stats=stats, houses=houses, by_dept=by_dept,
                           upcoming=upcoming, prev_day=day - timedelta(days=1), next_day=day + timedelta(days=1))


@bp.get("/reports")
@P("reports")
def reports():
    a = request.args
    today = date.today()
    try:
        d_from = date.fromisoformat(a.get("from") or today.replace(day=1).isoformat())
        d_to = date.fromisoformat(a.get("to") or today.isoformat())
    except ValueError:
        d_from, d_to = today.replace(day=1), today
    start, end = datetime.combine(d_from, datetime.min.time()), datetime.combine(d_to + timedelta(days=1), datetime.min.time())
    q = Guest.query.join(GuestRequest).filter(Guest.arrival < end, Guest.departure >= start)
    if a.get("status"):
        q = q.filter(GuestRequest.status == a["status"])
    if a.get("department"):
        q = q.filter(GuestRequest.department == a["department"])
    if a.get("stay"):
        q = q.filter(Guest.stay_type == a["stay"])
    rows = q.order_by(Guest.arrival).all()

    if a.get("format") == "csv":
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["Request", "Status", "Applicant", "Department", "Visit type", "Purpose", "Expenses by", "Guest",
                    "Organisation", "Mobile", "Arrival", "Departure", "Nights", "Stay", "Hotel cost", "Checked in",
                    "Checked out", "Vehicle trips"])
        for x in rows:
            r = x.request
            w.writerow([r.req_no, r.status_label, r.applicant.name, r.department, r.visit_type, r.purpose, r.expenses_by,
                        x.name, x.organisation, x.mobile, f"{x.arrival:%Y-%m-%d %H:%M}", f"{x.departure:%Y-%m-%d %H:%M}",
                        x.nights, x.stay_label, x.hotel_cost or "", x.checked_in_at or "", x.checked_out_at or "",
                        "; ".join(f"{t.trip_type} {t.vehicle_label}" for t in r.trips)])
        return Response(out.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": f"attachment; filename=guest-report-{d_from}-{d_to}.csv"})

    live = [x for x in rows if x.request.status in BOOKED + ("completed",)]
    summary = {
        "requests": len({x.request_id for x in rows}),
        "guests": len(rows),
        "room_nights": sum(x.nights for x in live if x.stay_type == "guest_house"),
        "hotel_nights": sum(x.nights for x in live if x.stay_type == "hotel"),
        "hotel_cost": sum(x.hotel_cost or 0 for x in live if x.stay_type == "hotel"),
    }
    departments = [d for (d,) in db.session.query(GuestRequest.department).distinct() if d]
    return render_template("guest_house/reports.html", rows=rows, summary=summary, d_from=d_from, d_to=d_to,
                           statuses=STATUSES, departments=sorted(departments), stay_types=STAY_TYPES)


# ------------------------------------------------------------------ masters
MASTERS = {
    "guest-houses": (GuestHouse, "Guest houses", [
        ("name", "Name", "text", True), ("location", "Location", "text", False),
        ("address", "Address", "text", False), ("contact_phone", "Caretaker phone", "text", False)]),
    "rooms": (Room, "Rooms", [
        ("guest_house_id", "Guest house", "guest_house", True), ("room_no", "Room no.", "text", True),
        ("room_type", "Type", ["Single", "Double", "Twin", "Suite", "Dormitory"], True),
        ("capacity", "Beds", "int", True), ("amenities", "Amenities", "text", False), ("remarks", "Remarks", "text", False)]),
    "hotels": (Hotel, "Hotels", [
        ("name", "Name", "text", True), ("city", "City", "text", False), ("address", "Address", "text", False),
        ("contact_person", "Contact person", "text", False), ("phone", "Phone", "text", False),
        ("email", "Email", "text", False), ("tariff", "Agreed tariff", "text", False)]),
    "vehicles": (Vehicle, "Vehicles", [
        ("reg_no", "Registration no.", "text", True), ("model", "Model", "text", False),
        ("vehicle_type", "Type", ["Sedan", "SUV", "MUV", "Tempo Traveller", "Bus", "Hatchback"], True),
        ("seats", "Seats", "int", True), ("ownership", "Ownership", ["Company", "Leased", "Pool"], True),
        ("driver_name", "Driver", "text", False), ("driver_phone", "Driver phone", "text", False)]),
    "visit-purposes": (VisitPurpose, "Visit purposes", [
        ("name", "Purpose / Type", "text", True),
        ("description", "Description", "text", False)]),
    "expense-borne-by": (ExpenseBorneBy, "Expenses borne by", [
        ("name", "Name", "text", True),
        ("description", "Description", "text", False)]),
    "locations": (Location, "Pickup & drop locations", [
        ("point_name", "Point name", "text", True),
        ("city", "City", "text", False),
        ("state", "State", "text", False),
        ("location_type", "Type", ["Domestic", "Outstation"], True)]),
    "food-locations": (FoodLocation, "Food locations", [
        ("name", "Location / Dining name", "text", True),
        ("category", "Category", ["Plant Canteen", "Guest House Dining", "VIP Lounge", "Field Delivery / Site", "Other"], True),
        ("description", "Description / Remarks", "text", False)]),
    "airports": (Airport, "Airports", [
        ("name", "Airport name", "text", True),
        ("code", "Airport code (IATA)", "text", False),
        ("city", "City", "text", False),
        ("state", "State", "text", False)]),
    "railway-stations": (RailwayStation, "Railway stations", [
        ("name", "Station name", "text", True),
        ("code", "Station code", "text", False),
        ("city", "City", "text", False),
        ("state", "State", "text", False)]),
}


@bp.route("/masters/<kind>", methods=["GET", "POST"])
@P("masters")
def masters(kind):
    model, title, fields = MASTERS.get(kind) or MASTERS.get(kind.replace('_', '-')) or abort(404)
    if request.method == "POST":
        item = db.session.get(model, request.form.get("id", type=int) or 0) or model()
        if request.form.get("action") == "toggle":
            item.is_active = not item.is_active
        elif request.form.get("action") == "delete":
            if item.id:
                db.session.delete(item)
                try:
                    db.session.commit()
                    flash("Deleted.", "success")
                except IntegrityError:
                    db.session.rollback()
                    flash("Cannot delete this entry because other records depend on it. Deactivate it instead.", "error")
            return redirect(url_for("guest_house.masters", kind=kind))
        else:
            for name, label, ftype, required in fields:
                raw = request.form.get(name, "").strip()
                if required and not raw:
                    flash(f"{label} is required.", "error")
                    return redirect(url_for("guest_house.masters", kind=kind, edit=item.id or None))
                if ftype in ("int", "guest_house"):
                    if raw and not raw.isdigit():
                        flash(f"{label} must be a number.", "error")
                        return redirect(url_for("guest_house.masters", kind=kind))
                    raw = int(raw) if raw else None
                setattr(item, name, raw or None)
            db.session.add(item)
        try:
            db.session.commit()
            flash("Saved.", "success")
        except IntegrityError:
            db.session.rollback()
            flash("That entry already exists.", "error")
        return redirect(url_for("guest_house.masters", kind=kind))
    items = model.query.all()
    items.sort(key=lambda i: (not i.is_active, str(i)))
    editing = db.session.get(model, request.args.get("edit", type=int) or 0)
    return render_template("guest_house/masters.html", kind=kind, title=title, fields=fields, items=items,
                           editing=editing, masters=MASTERS, guest_houses=GuestHouse.query.order_by(GuestHouse.name).all())

