from datetime import datetime

from flask import Blueprint, abort, current_app, g, jsonify, redirect, render_template, request, url_for
from sqlalchemy import or_

from core import approvals
from core.access import visible_apps
from core.db import db
from core.models import Employee, Notification
from core.notify import unread
from core.registry import APPS

bp = Blueprint("main", __name__)
OPEN_STATUSES = {"pending", "returned", "approved", "arranged"}  # requests still moving


@bp.get("/")
def home():
    apps = visible_apps(g.user)
    # Red counts = things to act on + unread updates ("approval needed" notes are already counted as tasks).
    badges = {app.code: (app.badge(g.user) if app.badge else 0) + unread(g.user, app.code).filter_by(kind="update").count()
              for app in apps}
    tasks_badge = len(approvals.pending_for(g.user)) + unread(g.user).filter_by(kind="update").count()
    return render_template("home.html", apps=apps, badges=badges, task_count=tasks_badge,
                           banner=current_app.config["BANNER_TEXT"], banner_url=current_app.config["BANNER_URL"])


def _my_requests():
    rows = []
    for app in visible_apps(g.user):
        if app.user_requests:
            rows += [(app, rec) for rec in app.user_requests(g.user)]
    rows.sort(key=lambda r: r[1].updated_at, reverse=True)
    return rows


@bp.get("/tasks")
def tasks():
    """Requests & Tasks: approvals waiting on me, my own requests, and updates."""
    tab = request.args.get("tab", "pending")
    pending = []
    for task in approvals.pending_for(g.user):
        app = APPS.get(task.app_code)
        record = app.approval_record(task.ref_id) if app and app.approval_record else None
        if record is not None:
            pending.append((task, app, record))
    mine = _my_requests()
    status = request.args.get("status", "open")
    shown = [r for r in mine if status == "all" or (r[1].status in OPEN_STATUSES) == (status == "open")]
    unread_refs = {(n.app_code, n.ref_id) for n in unread(g.user)}
    notes = Notification.query.filter_by(employee_id=g.user.employee_id).order_by(Notification.id.desc()).limit(100).all()
    return render_template("tasks.html", tab=tab, pending=pending, mine=shown, status=status,
                           open_count=len([r for r in mine if r[1].status in OPEN_STATUSES]),
                           unread_refs=unread_refs, notes=notes, updates_count=unread(g.user).count())


@bp.get("/notifications/<int:note_id>")
def open_notification(note_id):
    note = db.session.get(Notification, note_id)
    if note is None or note.employee_id != g.user.employee_id:
        abort(404)
    note.read_at = note.read_at or datetime.now()
    db.session.commit()
    return redirect(note.url if note.url.startswith("/") else url_for("main.tasks", tab="updates"))


@bp.post("/notifications/read-all")
def read_all():
    unread(g.user).update({"read_at": datetime.now()})
    db.session.commit()
    return redirect(request.referrer or url_for("main.tasks", tab="updates"))


@bp.get("/api/employees")
def search_employees():
    """Employee picker suggestions."""
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify([])
    like = f"%{q}%"
    people = Employee.query.filter(
        Employee.status == "Active",
        or_(Employee.name.ilike(like), Employee.employee_id.ilike(like),
            Employee.designation.ilike(like), Employee.department.ilike(like)),
    ).order_by(Employee.name).limit(15).all()
    return jsonify([p.to_brief() for p in people])


@bp.get("/people/<emp_id>")
def person(emp_id):
    emp = db.session.get(Employee, emp_id) or abort(404)
    reports = Employee.query.filter_by(reporting_manager_id=emp.employee_id, status="Active").order_by(Employee.name).all()
    return render_template("person.html", emp=emp, reports=reports)
