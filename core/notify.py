"""In-app notifications (bell + red badges), mirrored to email."""
from datetime import datetime
from urllib.parse import urljoin

from flask import has_request_context, request

from core.db import db
from core.mail import send_mail
from core.models import Notification


def notify(people, app_code, ref_id, title, url="", body="", kind="update", email=True):
    """kind: 'action' = someone must act, 'update' = for information."""
    people = {p.employee_id: p for p in people if p is not None}.values()
    for p in people:
        db.session.add(Notification(employee_id=p.employee_id, app_code=app_code, ref_id=ref_id, kind=kind,
                                    title=title, body=body, url=url))
    if email:
        link = urljoin(request.host_url, url) if url and has_request_context() else url
        send_mail([p.email for p in people], f"[Docket] {title}", f"{body}\n\n{link}".strip())


def unread(emp, app_code=None):
    q = Notification.query.filter_by(employee_id=emp.employee_id, read_at=None)
    if app_code:
        q = q.filter_by(app_code=app_code)
    return q


def mark_read(emp, app_code, ref_id):
    """Opening a record clears its notifications."""
    unread(emp, app_code).filter_by(ref_id=ref_id).update({"read_at": datetime.now()})
