"""Employees sign in with an emailed OTP (like Docket); local accounts (super admins) with a password."""
import hashlib
import hmac
import secrets
import time
from datetime import datetime

from flask import Blueprint, current_app, flash, g, redirect, render_template, request, session, url_for

from core.db import db
from core.mail import send_mail
from core.models import Employee

bp = Blueprint("auth", __name__)
MAX_OTP_ATTEMPTS = 5


def _otp_mac(emp_id, code, expires):
    # Only an HMAC goes into the (client-readable) session cookie, never the OTP itself.
    msg = f"{emp_id}:{code}:{expires}".encode()
    return hmac.new(current_app.config["SECRET_KEY"].encode(), msg, hashlib.sha256).hexdigest()


def _sign_in(emp):
    nxt = session.get("next")
    session.clear()
    session["emp_id"] = emp.employee_id
    emp.last_login_at = datetime.now()
    db.session.commit()
    return redirect(nxt if nxt and nxt.startswith("/") and not nxt.startswith("//") else url_for("main.home"))


@bp.get("/login")
def login():
    if g.user:
        return redirect(url_for("main.home"))
    if request.args.get("next"):
        session["next"] = request.args["next"]
    return render_template("login.html")


@bp.post("/login/otp")
def send_otp():
    emp = db.session.get(Employee, request.form.get("emp_id", "").strip())
    if emp is None or not emp.is_active:
        flash("Employee ID not found or inactive. Contact the administrator.", "error")
        return redirect(url_for("auth.login"))
    if not emp.email:
        flash("No email is registered for this employee ID. Contact the administrator.", "error")
        return redirect(url_for("auth.login"))

    code = f"{secrets.randbelow(1_000_000):06d}"
    expires = int(time.time()) + current_app.config["OTP_TTL_SECONDS"]
    session.update(otp_emp=emp.employee_id, otp_exp=expires, otp_mac=_otp_mac(emp.employee_id, code, expires), otp_tries=0)

    sent = send_mail([emp.email], "Your Docket sign-in code", f"Your one-time code is {code}. It expires in 5 minutes.")
    masked = emp.email[:3] + "***@" + emp.email.split("@")[-1]
    if sent:
        flash(f"Code sent to {masked}.", "success")
    elif current_app.config["OTP_SHOW_ON_SCREEN"]:
        flash(f"Mail is not configured (dev mode). Your code is {code}.", "info")
    else:
        current_app.logger.warning("OTP mail to %s failed", emp.email)
        flash("We could not send the code. Try again or contact the administrator.", "error")
        return redirect(url_for("auth.login"))
    return redirect(url_for("auth.verify_otp"))


@bp.route("/login/verify", methods=["GET", "POST"])
def verify_otp():
    emp_id = session.get("otp_emp")
    if not emp_id:
        return redirect(url_for("auth.login"))
    if request.method == "GET":
        return render_template("login.html", otp_for=emp_id)

    session["otp_tries"] = session.get("otp_tries", 0) + 1
    code = request.form.get("otp", "").strip()
    expired = time.time() > session.get("otp_exp", 0)
    if expired or session["otp_tries"] > MAX_OTP_ATTEMPTS:
        for k in ("otp_emp", "otp_exp", "otp_mac", "otp_tries"):
            session.pop(k, None)
        flash("Code expired or too many attempts. Request a new one.", "error")
        return redirect(url_for("auth.login"))
    if not hmac.compare_digest(_otp_mac(emp_id, code, session["otp_exp"]), session.get("otp_mac", "")):
        flash("Incorrect code.", "error")
        return redirect(url_for("auth.verify_otp"))
    emp = db.session.get(Employee, emp_id)
    if emp is None or not emp.is_active:
        return redirect(url_for("auth.login"))
    return _sign_in(emp)


@bp.post("/login/password")
def password_login():
    emp = db.session.get(Employee, request.form.get("username", "").strip())
    if emp is None or not emp.check_password(request.form.get("password", "")):
        flash("Invalid username or password.", "error")
        return redirect(url_for("auth.login"))
    if not (emp.is_active or emp.is_superadmin):
        flash("Account disabled.", "error")
        return redirect(url_for("auth.login"))
    return _sign_in(emp)


@bp.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@bp.post("/stop-impersonating")
def stop_impersonating():
    admin_id = session.get("impersonator")
    emp = db.session.get(Employee, admin_id) if admin_id else None
    if emp is None or not emp.is_superadmin:
        return redirect(url_for("main.home"))
    session.clear()
    session["emp_id"] = emp.employee_id
    return redirect(url_for("admin.employees"))
