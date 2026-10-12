import hmac
import secrets
from functools import wraps

from flask import abort, current_app, flash, g, redirect, request, session, url_for

from core.db import db
from core.models import Employee

OPEN_ENDPOINTS = {"auth.login", "auth.send_otp", "auth.verify_otp", "auth.password_login", "static", "favicon"}


def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_urlsafe(32)
    return session["_csrf"]


def init_app(app):
    @app.before_request
    def _load_user_and_guard():
        g.user = db.session.get(Employee, session["emp_id"]) if "emp_id" in session else None
        if g.user is not None and not (g.user.is_active or g.user.is_superadmin):
            session.clear()
            g.user = None
            flash("Your account is inactive.", "error")

        if request.method == "POST" and current_app.config["CSRF_ENABLED"]:
            sent = request.form.get("_csrf") or request.headers.get("X-CSRF-Token", "")
            if not hmac.compare_digest(sent, session.get("_csrf", "")):
                # Stale page (e.g. back button after signing in): send them back with a fresh form.
                flash("That form had expired - please try again.", "error")
                return redirect(url_for("main.home") if g.user else url_for("auth.login"))

        if g.user is None and request.endpoint not in OPEN_ENDPOINTS:
            return redirect(url_for("auth.login", next=request.full_path.rstrip("?") if request.method == "GET" else None))

    @app.context_processor
    def _template_globals():
        from core.access import can, visible_apps
        from core.models import Notification
        from core.notify import unread
        from core.registry import APPS
        user = g.get("user")
        return {"csrf_token": csrf_token, "can": can, "APPS": APPS, "visible_apps": visible_apps, "current_user": user,
                "unread_count": lambda: unread(user).count() if user else 0,
                "recent_notes": lambda: Notification.query.filter_by(employee_id=user.employee_id)
                .order_by(Notification.id.desc()).limit(8).all() if user else [],
                "app_admin_anywhere": lambda: bool(user) and any(can(user, c, "admin") for c in APPS)}


def superadmin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not g.user.is_superadmin:
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def permission_required(app_code, *perms):
    """Allow the view when the user holds any of perms in app_code (and the app is live for them)."""
    def deco(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            from core.access import can
            from core.registry import get_setting
            if not any(can(g.user, app_code, p) for p in perms):
                abort(403)
            if not get_setting(app_code, "enabled") and not can(g.user, app_code, "admin"):
                flash("This application is currently switched off.", "error")
                return redirect(url_for("main.home"))
            return view(*args, **kwargs)
        return wrapped
    return deco
