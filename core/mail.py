import smtplib
from email.message import EmailMessage

from flask import current_app


def send_mail(to, subject, body):
    """Best effort. Returns True when handed to SMTP. Without SMTP_SERVER mail is only logged."""
    # ponytail: synchronous send inside the request; move to a queue if SMTP gets slow
    recipients = sorted({addr for addr in to if addr})
    cfg = current_app.config
    if not recipients:
        return False
    if not cfg["SMTP_SERVER"]:
        current_app.logger.info("[mail not configured] to=%s | %s\n%s", recipients, subject, body)
        return False
    msg = EmailMessage()
    msg["From"] = cfg["SMTP_SENDER"]
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(cfg["SMTP_SERVER"], cfg["SMTP_PORT"], timeout=10) as smtp:
            if cfg["SMTP_USE_TLS"]:
                smtp.starttls()
            if cfg["SMTP_USERNAME"]:
                smtp.login(cfg["SMTP_USERNAME"], cfg["SMTP_PASSWORD"])
            smtp.send_message(msg)
        return True
    except Exception:
        current_app.logger.exception("Mail to %s failed", recipients)
        return False
