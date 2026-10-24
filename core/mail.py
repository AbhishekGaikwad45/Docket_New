import smtplib
from email.message import EmailMessage
from email.utils import formataddr, parseaddr, getaddresses

from flask import current_app


def _format_target(target):
    """Normalizes an email target (Employee/User object, or string) to a valid 'Name <email>' or 'email' string."""
    if not target:
        return None
    name = ""
    email = ""
    if hasattr(target, "email"):
        name = getattr(target, "name", "") or ""
        email = (target.email or "").strip()
    elif isinstance(target, str):
        target = target.strip()
        parsed_name, parsed_email = parseaddr(target)
        if parsed_email:
            name, email = parsed_name, parsed_email
        elif "@" in target:
            email = target
    else:
        return None

    if not email or "@" not in email or "." not in email.split("@")[-1]:
        return None

    name = name.strip()
    return formataddr((name, email)) if name else email


def send_mail(to, subject, body, cc=None):
    """Best effort. Returns True when handed to SMTP. Without SMTP_SERVER mail is only logged."""
    to_formatted = []
    for item in (to or []):
        formatted = _format_target(item)
        if formatted and formatted not in to_formatted:
            to_formatted.append(formatted)

    cc_formatted = []
    for item in (cc or []):
        formatted = _format_target(item)
        if formatted and formatted not in cc_formatted and formatted not in to_formatted:
            cc_formatted.append(formatted)

    # Edge case: if caller specifically passed CC items that had identical string as to, keep them
    if not cc_formatted and cc:
        for item in cc:
            formatted = _format_target(item)
            if formatted and formatted not in cc_formatted:
                cc_formatted.append(formatted)

    cfg = current_app.config
    if not to_formatted and not cc_formatted:
        return False
    if not cfg.get("SMTP_SERVER"):
        current_app.logger.info("[mail not configured] to=%s | cc=%s | %s\n%s", to_formatted, cc_formatted, subject, body)
        return False

    msg = EmailMessage()
    msg["From"] = cfg.get("SMTP_SENDER") or "docket@jsw.in"
    if to_formatted:
        msg["To"] = ", ".join(to_formatted)
    if cc_formatted:
        msg["Cc"] = ", ".join(cc_formatted)
    msg["Subject"] = subject
    msg.set_content(body)

    # Extract unique envelope addresses (RCPT TO) so SMTP server never complains about duplicates
    all_headers = msg.get_all("To", []) + msg.get_all("Cc", [])
    parsed = getaddresses(all_headers)
    envelope_recipients = list(dict.fromkeys(addr.strip() for _, addr in parsed if addr and "@" in addr))

    if not envelope_recipients:
        return False

    try:
        with smtplib.SMTP(cfg["SMTP_SERVER"], cfg["SMTP_PORT"], timeout=10) as smtp:
            if cfg.get("SMTP_USE_TLS"):
                smtp.starttls()
            if cfg.get("SMTP_USERNAME"):
                smtp.login(cfg["SMTP_USERNAME"], cfg["SMTP_PASSWORD"])
            smtp.send_message(msg, to_addrs=envelope_recipients)
        return True
    except Exception:
        current_app.logger.exception("Mail to %s (cc: %s) failed", to_formatted, cc_formatted)
        return False
