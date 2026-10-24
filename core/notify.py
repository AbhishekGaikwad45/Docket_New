"""In-app notifications (bell + red badges), mirrored to email."""
from datetime import datetime
from urllib.parse import urljoin

from flask import has_request_context, request

from core.db import db
from core.mail import send_mail
from core.models import Notification


def notify(people, app_code, ref_id, title, url="", body="", kind="update", email=True, cc_people=None, include_link_in_email=True):
    """kind: 'action' = someone must act, 'update' = for information."""
    people_map = {}
    for p in (people or []):
        if p is None:
            continue
        emp_id = getattr(p, "employee_id", None)
        if emp_id:
            people_map[emp_id] = p
        else:
            people_map[id(p)] = p

    for p in people_map.values():
        emp_id = getattr(p, "employee_id", None)
        if emp_id:
            db.session.add(Notification(employee_id=emp_id, app_code=app_code, ref_id=ref_id, kind=kind,
                                        title=title, body=body, url=url))

    if cc_people:
        cc_map = {}
        for p in cc_people:
            if p is None:
                continue
            emp_id = getattr(p, "employee_id", None)
            if emp_id and emp_id in people_map:
                continue
            if emp_id:
                cc_map[emp_id] = p
            else:
                cc_map[id(p)] = p
        for p in cc_map.values():
            emp_id = getattr(p, "employee_id", None)
            if emp_id:
                db.session.add(Notification(employee_id=emp_id, app_code=app_code, ref_id=ref_id, kind="update",
                                            title=title, body=body, url=url))

    if email:
        link = urljoin(request.host_url, url) if url and has_request_context() else url
        email_body = f"{body}\n\n{link}".strip() if (include_link_in_email and link) else body.strip()
        send_mail(people, f"[Docket] {title}", email_body, cc=cc_people)


def unread(emp, app_code=None):
    q = Notification.query.filter_by(employee_id=emp.employee_id, read_at=None)
    if app_code:
        q = q.filter_by(app_code=app_code)
    return q


def mark_read(emp, app_code, ref_id):
    """Opening a record clears its notifications."""
    unread(emp, app_code).filter_by(ref_id=ref_id).update({"read_at": datetime.now()})
