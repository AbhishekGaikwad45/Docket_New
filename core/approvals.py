"""Generic approval engine driven by each app's approval org chart (core.models.ApprovalNode).

Routing (same idea as Docket's department branches):
- Applicant sits in the chart -> the request starts at the level above their (deepest) box.
- Otherwise it starts at the deepest box tagged with the applicant's department,
  else at a box marked "everyone else". No match -> submission is blocked with a clear message.
- From there it climbs parent by parent to the top. Levels with an unmet condition are passed over.
Rules:
- The applicant is never their own approver (that level is skipped).
- Someone who already approved earlier in the same round is auto-approved at later levels.
- Any person in a level can act; app admins can act on anyone's behalf.
- Reject / send back need remarks. Send back lets the applicant edit and resubmit (new round).
"""
from datetime import datetime

from flask import url_for
from sqlalchemy import func

from core.access import can
from core.db import db
from core.models import ApprovalNode, ApprovalTask
from core.notify import notify
from core.registry import APPS

OPEN = ("waiting", "pending")


class ApprovalError(Exception):
    pass


def route(app_code, applicant):
    """Boxes from the entry point up to the top, or raise ApprovalError. [] when the app has no chart."""
    nodes = ApprovalNode.query.filter_by(app_code=app_code).all()
    if not nodes:
        return []
    deepest = lambda ns: max(ns, key=lambda n: (n.depth, -n.id))  # noqa: E731
    mine = [n for n in nodes if applicant in n.members]
    if mine:
        start = deepest(mine).parent
    else:
        entries = [n for n in nodes if applicant.department and applicant.department in n.entry_list] \
            or [n for n in nodes if n.entry_all]
        if not entries:
            raise ApprovalError(f'No approval route for department "{applicant.department or "-"}". '
                                "Ask the application admin to add it to the approval org chart.")
        start = deepest(entries)
    path, seen = [], set()
    while start is not None and start.id not in seen:
        seen.add(start.id)
        path.append(start)
        start = start.parent
    return path


def plan(app_code, applicant, context):
    """Dry run: [{label, approvers, note, error}] - also shown on the request form."""
    try:
        path = route(app_code, applicant)
    except ApprovalError as exc:
        return [{"label": "Route", "approvers": [], "note": "", "error": str(exc)}]
    rows = []
    for node in path:
        if node.condition and not context.get(node.condition):
            continue
        people = [e for e in node.members if e.is_active]
        approvers = [e for e in people if e.employee_id != applicant.employee_id]
        row = {"label": node.label, "approvers": approvers, "note": "", "error": ""}
        if not people:
            row["error"] = f'Nobody active in "{node.label}". Ask the application admin to update the approval org chart.'
        elif not approvers:
            row["note"] = "Skipped - you are the approver"
        rows.append(row)
    return rows


def start(app_code, ref_id, applicant, context):
    """Create tasks for a (re)submission. Returns 'pending' or 'approved' (nothing to approve)."""
    rows = plan(app_code, applicant, context)
    for row in rows:
        if row["error"]:
            raise ApprovalError(row["error"])
    cancel(app_code, ref_id)
    last = db.session.query(func.max(ApprovalTask.round)).filter_by(app_code=app_code, ref_id=ref_id).scalar()
    rnd = (last or 0) + 1
    for i, row in enumerate(rows):
        ids = [e.employee_id for e in row["approvers"]]
        db.session.add(ApprovalTask(
            app_code=app_code, ref_id=ref_id, round=rnd, position=i, label=row["label"],
            candidates="," + ",".join(ids) + ",", status="waiting" if ids else "skipped", note=row["note"],
        ))
    db.session.flush()
    return _advance(app_code, ref_id, rnd)


def _advance(app_code, ref_id, rnd):
    tasks = ApprovalTask.query.filter_by(app_code=app_code, ref_id=ref_id, round=rnd).order_by(ApprovalTask.position).all()
    approved_by = {t.acted_by_id for t in tasks if t.status == "approved" and t.acted_by_id}
    now = datetime.now()
    for task in tasks:
        if task.status != "waiting":
            continue
        already = approved_by.intersection(task.candidate_ids)
        if already:
            task.status, task.acted_by_id, task.acted_at = "approved", sorted(already)[0], now
            task.note = "Auto-approved - already approved at an earlier level"
            continue
        task.status, task.activated_at = "pending", now
        record = _record(task)
        earlier_approved = [t for t in tasks if t.status == "approved" and t.acted_by and t.position < task.position]
        earlier_info = ""
        if earlier_approved:
            e_parts = [f"{t.label}" for t in earlier_approved]
            earlier_info = f"\nApproved earlier at: {', '.join(e_parts)}"

        body_msg = (
            f"Dear Approver,\n\n"
            f"A requisition is pending your approval.\n\n"
            f"Request: {record.approval_title}\n"
            f"Level: {task.label}{earlier_info}\n\n"
            f"Please check and provide your approval in Docket.\n\n"
            f"Best regards,\nAdmin"
        )
        notify(task.candidate_people, app_code, ref_id, f"Approval needed: {record.approval_title}",
               _url(record), body_msg, kind="action", include_link_in_email=False)
        return "pending"
    return "approved"


def act(task, actor, action, remarks=""):
    """action: approve / reject / return. Returns the record outcome: pending / approved / rejected / returned."""
    if not can_act(task, actor):
        raise ApprovalError("You cannot act on this approval.")
    if action not in ("approve", "reject", "return"):
        raise ApprovalError("Unknown action.")
    remarks = (remarks or "").strip()
    if action != "approve" and not remarks:
        raise ApprovalError("Remarks are required to reject or send back.")

    task.status = {"approve": "approved", "reject": "rejected", "return": "returned"}[action]
    task.acted_by_id, task.acted_at, task.remarks = actor.employee_id, datetime.now(), remarks
    if actor.employee_id not in task.candidate_ids:
        task.note = "Acted on behalf by application admin"
    # Their "approval needed" notification is done with.
    from core.notify import mark_read
    for person in task.candidate_people:
        mark_read(person, task.app_code, task.ref_id)

    if action == "approve":
        outcome = _advance(task.app_code, task.ref_id, task.round)
        if outcome == "pending":
            record = _record(task)
            next_task = ApprovalTask.query.filter_by(app_code=task.app_code, ref_id=task.ref_id, round=task.round, status="pending").first()
            next_label = next_task.label if next_task else "next level"
            next_people = next_task.candidate_people if next_task else []
            next_names = " / ".join(p.name for p in next_people) if next_people else next_label

            applicant_msg = (
                f"Dear {record.applicant.name},\n\n"
                f"Your requisition {getattr(record, 'req_no', record.approval_title)} has been approved at level: {task.label}.\n\n"
                f"Current Status: Pending approval at {next_label} ({next_names}).\n\n"
                f"Best regards,\nAdmin"
            )
            cc_people = []
            try:
                if task.app_code == "guest_house":
                    from modules.guest_house.views import get_applicant_hierarchy
                    cc_people = get_applicant_hierarchy(record)
            except Exception:
                pass
            if not cc_people:
                all_tasks = ApprovalTask.query.filter_by(app_code=task.app_code, ref_id=task.ref_id, round=task.round).all()
                seen = {record.applicant.employee_id}
                if getattr(record.applicant, "manager", None) and record.applicant.manager.employee_id not in seen:
                    seen.add(record.applicant.manager.employee_id)
                    cc_people.append(record.applicant.manager)
                for t in all_tasks:
                    if t.acted_by and t.acted_by.employee_id not in seen:
                        seen.add(t.acted_by.employee_id)
                        cc_people.append(t.acted_by)

            notify([record.applicant], task.app_code, task.ref_id,
                   f"{record.approval_title}: approved at {task.label}", _url(record),
                   applicant_msg, email=True, cc_people=cc_people, include_link_in_email=False)
    else:
        ApprovalTask.query.filter_by(app_code=task.app_code, ref_id=task.ref_id, round=task.round, status="waiting") \
            .update({"status": "cancelled"})
        outcome = task.status
    if outcome != "pending" and APPS[task.app_code].on_approval:
        APPS[task.app_code].on_approval(task.ref_id, outcome, actor, remarks)
    return outcome


def cancel(app_code, ref_id):
    ApprovalTask.query.filter(ApprovalTask.app_code == app_code, ApprovalTask.ref_id == ref_id,
                              ApprovalTask.status.in_(OPEN)).update({"status": "cancelled"}, synchronize_session=False)


def can_act(task, emp):
    return task.status == "pending" and (emp.employee_id in task.candidate_ids or can(emp, task.app_code, "admin"))


def pending_for(emp, app_code=None):
    q = ApprovalTask.query.filter(ApprovalTask.status == "pending",
                                  ApprovalTask.candidates.contains(f",{emp.employee_id},", autoescape=True))
    if app_code:
        q = q.filter(ApprovalTask.app_code == app_code)
    return q.order_by(ApprovalTask.activated_at).all()


def current_task(app_code, ref_id):
    return ApprovalTask.query.filter_by(app_code=app_code, ref_id=ref_id, status="pending").first()


def timeline(app_code, ref_id):
    return ApprovalTask.query.filter_by(app_code=app_code, ref_id=ref_id) \
        .order_by(ApprovalTask.round, ApprovalTask.position).all()


def _record(task):
    return APPS[task.app_code].approval_record(task.ref_id)


def _url(record):
    try:
        return url_for(record.approval_endpoint, **record.approval_args)
    except RuntimeError:  # no request context (CLI)
        return ""
