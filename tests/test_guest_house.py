"""End-to-end: hierarchy -> approvals -> desk allocation -> clashes -> cancel -> reports. Run: pytest -q"""
import io
from datetime import datetime, timedelta

import pytest

from app import create_app
from core import approvals, sync
from core.db import db
from core.demo import seed
from core.models import ApprovalNode, Employee, Notification
from modules.guest_house.models import ExpenseBorneBy, GuestRequest, Room, Vehicle, VisitPurpose


@pytest.fixture()
def app(tmp_path):
    app = create_app({"SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 't.db'}", "CSRF_ENABLED": False,
                      "TESTING": True, "SERVER_NAME": "localhost"})
    with app.app_context():
        db.create_all()
        seed()
        yield app


def as_user(client, emp_id):
    with client.session_transaction() as s:
        s.clear()
        s["emp_id"] = emp_id
    return client


def dt(days, hour=10):
    return (datetime.now().replace(minute=0, second=0, microsecond=0) + timedelta(days=days)).replace(hour=hour) \
        .strftime("%Y-%m-%dT%H:%M")


def submit(client, guests=5, start=3, end=5, **extra):
    data = {"visit_type": "Audit", "purpose": "IMS RC audit", "organisation": "Auditors Ltd", "expenses_by": "Company",
            "need_guest_house": "1", "need_hotel": "0", "need_vehicle": "1", "vehicle_note": "Pickup at station",
            "need_food": "1", "food_note": "Veg", "need_ticket": "0"}
    data.update(extra)
    rows = {k: [] for k in ("g_name", "g_gender", "g_mobile", "g_email", "g_org", "g_designation", "g_arrival", "g_departure")}
    for i in range(guests):
        for k, v in {"g_name": f"Guest {i + 1}", "g_gender": "Male", "g_mobile": "9876543210", "g_email": "",
                     "g_org": "", "g_designation": "Auditor", "g_arrival": dt(start), "g_departure": dt(end)}.items():
            rows[k].append(v)
    return client.post("/apps/guest_house/requests/new", data={**data, **rows})


def decide(client, req_id, action="approve", remarks=""):
    return client.post(f"/apps/guest_house/requests/{req_id}/decide", data={"action": action, "remarks": remarks})


def arrange_form(req, rooms, trips=(), action="finalize"):
    data = {"action": action, "food_arrangement": "Veg lunch at canteen", "ticket_arrangement": "", "desk_remarks": ""}
    for gst, room in zip(req.guests, rooms):
        p = f"g{gst.id}_"
        data.update({p + "arrival": gst.arrival.strftime("%Y-%m-%dT%H:%M"), p + "departure": gst.departure.strftime("%Y-%m-%dT%H:%M"),
                     p + "stay_type": "guest_house", p + "room_id": str(room.id), p + "remarks": ""})
    cols = ["t_type", "t_pickup", "t_drop", "t_start", "t_end", "t_source", "t_vehicle", "t_vendor", "t_hired_no",
            "t_hired_type", "t_driver", "t_driver_phone", "t_cost", "t_remarks"]
    for c in cols:
        data[c] = [t.get(c, "") for t in trips]
    return data


def latest():
    db.session.expire_all()
    return GuestRequest.query.order_by(GuestRequest.id.desc()).first()


def test_full_flow(app):
    c = app.test_client()
    room = {r.room_no: r for r in Room.query.all()}
    innova = Vehicle.query.filter_by(reg_no="MH08AB1234").one()

    # Engineer raises for 5 guests (more than the paper form's 4 rows)
    assert submit(as_user(c, "1007")).status_code == 302
    req = latest()
    assert len(req.guests) == 5 and req.status == "pending" and req.req_no.startswith("GR-")

    # Chain: reporting manager -> HOD -> Admin Head; Unit Head step skipped (no hotel asked)
    decide(as_user(c, "1005"), req.id)  # HOD can't jump the queue
    assert approvals.current_task("guest_house", req.id).label == "Manager - Marine"
    for approver in ("1006", "1005", "1003"):
        decide(as_user(c, approver), req.id)
    req = latest()
    assert req.status == "approved"

    # Desk: 5 guests in 102(2) 102 103(2) 103 101(1). 3 people in a 2-bed room is refused.
    desk = as_user(c, "1004")
    bad = arrange_form(req, [room["102"]] * 3 + [room["103"], room["101"]])
    assert "bed(s)" in desk.post(f"/apps/guest_house/requests/{req.id}/arrange", data=bad).get_data(as_text=True)
    trip = {"t_type": "Pickup", "t_pickup": "Station", "t_drop": "GH", "t_start": dt(3, 8), "t_end": dt(3, 11),
            "t_source": "company", "t_vehicle": str(innova.id)}
    good = arrange_form(req, [room["102"], room["102"], room["103"], room["103"], room["101"]], [trip])
    desk.post(f"/apps/guest_house/requests/{req.id}/arrange", data=good)
    req = latest()
    assert req.status == "arranged" and req.trips[0].driver_name == "Suresh"

    # Second request, overlapping dates: room 102 and the Innova are taken
    submit(as_user(c, "1009"), guests=1, start=4, end=6)
    req2 = latest()
    for approver in ("1008", "1003"):  # IT branch: IT HOD -> Admin Head
        decide(as_user(c, approver), req2.id)
    req2 = latest()
    assert req2.status == "approved"
    clash = desk.post(f"/apps/guest_house/requests/{req2.id}/arrange",
                      data=arrange_form(req2, [room["102"]], [{**trip, "t_start": dt(3, 10), "t_end": dt(3, 12)}]))
    text = clash.get_data(as_text=True)
    assert "is held by" in text and "is booked for" in text
    hired = {"t_type": "Pickup", "t_start": dt(4, 9), "t_end": dt(4, 12), "t_source": "hired", "t_vendor": "City Travels",
             "t_hired_no": "mh08zz0001", "t_cost": "1800"}
    desk.post(f"/apps/guest_house/requests/{req2.id}/arrange", data=arrange_form(req2, [room["104"]], [hired]))
    req2 = latest()
    assert req2.status == "arranged" and req2.trips[0].hired_vehicle_no == "MH08ZZ0001"

    # Applicant cancels request 1 -> room 102 frees up for request 2
    as_user(c, "1007").post(f"/apps/guest_house/requests/{req.id}/cancel", data={"reason": "Audit postponed"})
    assert db.session.get(GuestRequest, req.id).status == "cancelled"
    desk = as_user(c, "1004")
    desk.post(f"/apps/guest_house/requests/{req2.id}/arrange", data=arrange_form(req2, [room["102"]], [hired]))
    assert latest().guests[0].room.room_no == "102"

    # Check-in / check-out completes the request
    gid = latest().guests[0].id
    desk.post(f"/apps/guest_house/guests/{gid}/check-in")
    desk.post(f"/apps/guest_house/guests/{gid}/check-out")
    assert latest().status == "completed"

    # Pages render for the right people; others are refused
    for url in ("/", "/tasks", "/tasks?tab=mine", "/tasks?tab=updates", "/apps/guest_house/dashboard", "/apps/guest_house/desk", "/apps/guest_house/masters/rooms",
                f"/apps/guest_house/requests/{req.id}", f"/apps/guest_house/requests/{req.id}/print",
                "/apps/guest_house/approvals", "/apps/guest_house/requests/new"):
        assert desk.get(url).status_code == 200, url
    admin = as_user(c, "admin")
    for url in ("/admin/", "/admin/employees", "/admin/sync", "/admin/apps",
                "/admin/apps/guest_house", "/admin/apps/guest_house?tab=approvals&preview=1007",
                "/admin/apps/guest_house?tab=settings",
                "/apps/guest_house/reports", "/people/1007"):
        assert admin.get(url).status_code == 200, url
    csv_body = admin.get("/apps/guest_house/reports?format=csv&from=2000-01-01&to=2100-01-01").get_data(as_text=True)
    assert "Guest 1" in csv_body and "MH08ZZ0001" in csv_body
    pooja = as_user(c, "1009")
    assert pooja.get("/apps/guest_house/desk").status_code == 403
    assert pooja.get(f"/apps/guest_house/requests/{req.id}").status_code == 403  # not hers, not an approver


def test_chart_routing_notifications_return_and_reject(app):
    c = app.test_client()
    # HOD is in the chart: starts one level above his box. Hotel asked -> conditional top level applies.
    submit(as_user(c, "1005"), guests=1, need_hotel="1", need_guest_house="0")
    req = latest()
    assert [t.label for t in approvals.timeline("guest_house", req.id)] == \
        ["Admin Head approval", "Unit Head approval (hotel stays)"]
    decide(as_user(c, "1003"), req.id)
    decide(as_user(c, "1001"), req.id)
    assert latest().status == "approved"
    # Applicant was told at each step; the desk got an action item
    titles = [n.title for n in Notification.query.filter_by(employee_id="1005")]
    assert any("approved at Admin Head" in t for t in titles) and any(t.endswith("approved") for t in titles)
    assert Notification.query.filter_by(employee_id="1004", kind="action", read_at=None).count() == 1
    assert "dot-new" in as_user(c, "1005").get("/tasks?tab=mine").get_data(as_text=True)
    as_user(c, "1005").get(f"/apps/guest_house/requests/{req.id}")  # opening it clears the red dot
    assert Notification.query.filter_by(employee_id="1005", read_at=None).count() == 0

    # Send back needs remarks, then applicant edits & resubmits (round 2)
    submit(as_user(c, "1007"), guests=2)
    req = latest()
    decide(as_user(c, "1006"), req.id, "return")  # no remarks -> refused
    assert latest().status == "pending"
    decide(as_user(c, "1006"), req.id, "return", "Add guest designations")
    assert latest().status == "returned"
    form = as_user(c, "1007").get(f"/apps/guest_house/requests/{req.id}/edit")
    assert form.status_code == 200
    c.post(f"/apps/guest_house/requests/{req.id}/edit", data={
        "visit_type": "Audit", "purpose": "Audit v2", "expenses_by": "Company", "need_guest_house": "1",
        "g_name": ["A"], "g_gender": [""], "g_mobile": [""], "g_email": [""], "g_org": [""], "g_designation": ["Lead"],
        "g_arrival": [dt(3)], "g_departure": [dt(4)]})
    req = latest()
    assert req.status == "pending" and len(req.guests) == 1
    decide(as_user(c, "1006"), req.id, "reject", "Not needed")
    assert latest().status == "rejected"


def test_validation_and_blocking(app):
    c = as_user(app.test_client(), "1007")
    r = submit(c, guests=1, start=-2, end=1)  # arrival in the past
    assert "too soon or in the past" in r.get_data(as_text=True)
    r = submit(c, guests=1, start=3, end=2)
    assert "departure must be after arrival" in r.get_data(as_text=True)
    # Department missing from the org chart blocks submission with a clear message
    db.session.get(Employee, "1007").department = "New Dept"
    db.session.commit()
    r = submit(c, guests=1)
    assert "No approval route for department" in r.get_data(as_text=True)
    assert GuestRequest.query.count() == 0


def test_org_chart_editing(app):
    admin = as_user(app.test_client(), "admin")
    url = "/admin/apps/guest_house?tab=approvals"
    top = ApprovalNode.query.filter_by(parent_id=None).one()
    marine = ApprovalNode.query.filter_by(label="HOD - Marine Operations").one()
    admin.post(url, data={"action": "add", "parent_id": marine.id})
    new = ApprovalNode.query.filter_by(label="New level").one()
    admin.post(url, data={"action": "update", "node_id": new.id, "label": "Marine Supervisors", "parent_id": marine.id,
                          "condition": "", "entry_departments": ["Marine Operations"]})
    admin.post(url, data={"action": "add_member", "node_id": new.id, "employee_id": "1007"})
    db.session.expire_all()
    assert new.label == "Marine Supervisors" and [m.employee_id for m in new.members] == ["1007"]
    # Can't put a box under its own child
    admin.post(url, data={"action": "update", "node_id": marine.id, "label": marine.label, "parent_id": new.id, "condition": ""})
    db.session.expire_all()
    assert marine.parent_id != new.id
    # Deleting a level keeps the levels below it (they move up)
    admin.post(url, data={"action": "delete", "node_id": marine.id})
    db.session.expire_all()
    assert db.session.get(ApprovalNode, new.id).parent.label == "Admin Head approval"
    assert db.session.get(ApprovalNode, top.id) is not None


def test_sync_rules(app):
    csv_text = ("Employee  ID,EMPLOYEE_NAME,Designation,Department,Email ID,Employee Status,Reporting Manager\n"
                "2001,Asha N,Manager,IT,ASHA@X.COM,Active,\n"
                "2002,Ben K,Engineer,IT,,Active,Asha N (2001)\n"
                "1007,Vikas Changed,Engineer,Marine Operations,,Active,\n")
    header, rows = sync.read_file("emp.csv", io.BytesIO(csv_text.encode()))
    recs = sync.normalize(header, rows, "associates")
    assert recs[0]["department"] == "Information Technology" and recs[0]["email"] == "asha@x.com"
    db.session.get(Employee, "1007").source = "staff"
    stats = sync.upsert(recs)
    assert stats["inserted"] == 2 and stats["kept_staff"] == 1 and stats["managers_linked"] == 1
    assert db.session.get(Employee, "2002").reporting_manager_id == "2001"
    assert db.session.get(Employee, "1007").name == "Vikas More"  # staff record not overwritten
    stats = sync.upsert([{**recs[0], "email": None}])
    assert db.session.get(Employee, "2001").email == "asha@x.com"  # blank email never wipes a saved one


def test_visit_purpose_master(app):
    admin = as_user(app.test_client(), "admin")
    url = "/apps/guest_house/masters/visit-purposes"
    res = admin.get(url)
    assert res.status_code == 200
    assert "Visit purposes" in res.get_data(as_text=True)

    # Add new purpose
    admin.post(url, data={"name": "Client Presentation", "description": "Client visit"})
    p = VisitPurpose.query.filter_by(name="Client Presentation").first()
    assert p is not None
    assert p.is_active is True

    # Toggle active
    admin.post(url, data={"action": "toggle", "id": p.id})
    db.session.refresh(p)
    assert p.is_active is False

    # Delete purpose
    admin.post(url, data={"action": "delete", "id": p.id})
    assert VisitPurpose.query.filter_by(name="Client Presentation").first() is None

    # Test vehicle master delete
    veh_url = "/apps/guest_house/masters/vehicles"
    admin.post(veh_url, data={"reg_no": "MH08TEST99", "vehicle_type": "Sedan", "seats": "4", "ownership": "Company"})
    v = Vehicle.query.filter_by(reg_no="MH08TEST99").first()
    assert v is not None
    admin.post(veh_url, data={"action": "delete", "id": v.id})
    assert Vehicle.query.filter_by(reg_no="MH08TEST99").first() is None

    # Test expense-borne-by master
    exp_url = "/apps/guest_house/masters/expense-borne-by"
    res = admin.get(exp_url)
    assert res.status_code == 200
    assert "Expenses borne by" in res.get_data(as_text=True)

    admin.post(exp_url, data={"name": "Joint Venture"})
    eb = ExpenseBorneBy.query.filter_by(name="Joint Venture").first()
    assert eb is not None
    assert eb.is_active is True

    admin.post(exp_url, data={"action": "toggle", "id": eb.id})
    db.session.refresh(eb)
    assert eb.is_active is False

    admin.post(exp_url, data={"action": "delete", "id": eb.id})
    assert ExpenseBorneBy.query.filter_by(name="Joint Venture").first() is None

    # Test desk updating expenses_by on a request
    req = GuestRequest.query.first()
    if req:
        admin.post(f"/apps/guest_house/requests/{req.id}/update-expenses", data={"expenses_by": "Guest / Visitor", "cost_centre": ""})
        db.session.refresh(req)
        assert req.expenses_by == "Guest / Visitor"


def test_backdated_dates_validation(app):
    c = as_user(app.test_client(), "1007")
    # 1. Backdated arrival
    res = submit(c, guests=1, start=-2, end=3)
    assert "arrival is too soon or in the past" in res.get_data(as_text=True)

    # 2. Backdated departure
    res = submit(c, guests=1, start=-5, end=-2)
    assert "departure is in the past" in res.get_data(as_text=True)

    # 3. Departure before arrival
    res = submit(c, guests=1, start=5, end=2)
    assert "departure must be after arrival" in res.get_data(as_text=True)


def test_travel_ticket_mode_validation(app):
    c = as_user(app.test_client(), "1007")
    # 1. Travel ticket required but missing travel mode
    res = submit(c, guests=1, start=3, end=5, need_ticket="1", ticket_note="")
    assert "Select the travel mode (Air / Rail / Flight)" in res.get_data(as_text=True)

    # 2. Travel ticket required with travel_mode = Air
    res = submit(c, guests=1, start=3, end=5, need_ticket="1", travel_mode="Air", ticket_note="Mumbai to Delhi\n<!--TRAVEL_MODE:Air-->")
    assert res.status_code == 302
    req = latest()
    assert req.need_ticket is True
    assert req.travel_mode == "Air"
    assert "Mumbai to Delhi" in req.ticket_note







