"""Sends SMS (GatewayAPI) and e-mail (SMTP) to hosts when a guest checks in.

NOTIFY_MODE=test  -> messages are stored with status "test" and never sent.
NOTIFY_MODE=live  -> messages are sent; failures are stored with status "fejl".
"""
import logging
import re
import smtplib
from email.message import EmailMessage
from email.utils import formataddr

import httpx

from .config import settings
from .db import SessionLocal
from .models import Host, Notification, Tenant, Visit
from .timeutil import local_hhmm

log = logging.getLogger("gaestereg.notify")


class _Keep(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def render(template: str, ctx: dict) -> str:
    try:
        return template.format_map(_Keep(ctx))
    except (ValueError, IndexError):
        # A stray "{" in a custom template must never stop a notification.
        out = template
        for k, v in ctx.items():
            out = out.replace("{" + k + "}", str(v))
        return out


def normalize_msisdn(phone: str, default_cc: str = "45") -> str:
    """'+45 12 34 56 78' / '0045 12345678' / '12345678' -> '4512345678'."""
    p = (phone or "").strip()
    digits = re.sub(r"\D", "", p)
    if p.startswith("00"):
        digits = digits[2:]
    elif not p.startswith("+") and len(digits) == 8:
        digits = default_cc + digits
    return digits


def valid_email(addr: str) -> bool:
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", (addr or "").strip()))


def context_for(visit: Visit, tenant: Tenant, host_name: str) -> dict:
    return {
        "gaest": visit.guest_name or "En gæst",
        "telefon": visit.guest_phone or "ikke oplyst",
        "firma": visit.guest_company or "ikke oplyst",
        "vaert": host_name,
        "vaert_fornavn": (host_name or "").split(" ")[0] if host_name else "",
        "tid": local_hhmm(visit.checked_in_at),
        "kunde": tenant.name,
    }


def build_messages(visit: Visit, tenant: Tenant, host: Host | None) -> list[Notification]:
    """Decide who gets what. Returns unsaved Notification rows."""
    out: list[Notification] = []
    if host is not None:
        ctx = context_for(visit, tenant, host.name)
        targets = [("sms", host.phone, host.notify_sms), ("email", host.email, host.notify_email)]
    else:
        ctx = context_for(visit, tenant, "receptionen")
        ctx["vaert_fornavn"] = "receptionen"
        targets = [("sms", tenant.reception_phone, True), ("email", tenant.reception_email, True)]

    for channel, addr, wanted in targets:
        if not wanted or not (addr or "").strip():
            continue
        if channel == "sms":
            out.append(Notification(tenant_id=tenant.id, visit_id=visit.id, channel="sms",
                                    recipient=addr.strip(), body=render(tenant.sms_template, ctx)))
        else:
            out.append(Notification(tenant_id=tenant.id, visit_id=visit.id, channel="email",
                                    recipient=addr.strip(), subject=render(tenant.email_subject, ctx),
                                    body=render(tenant.email_template, ctx)))
    return out


# ---------- providers ----------

def send_sms(sender: str, phone: str, text: str) -> None:
    if not settings.sms_configured:
        raise RuntimeError("SMS er ikke sat op (GATEWAYAPI_TOKEN mangler)")
    msisdn = normalize_msisdn(phone)
    if len(msisdn) < 8:
        raise ValueError(f"Ugyldigt mobilnummer: {phone}")
    sender = re.sub(r"[^A-Za-z0-9 ]", "", sender or "")[:11] or "Reception"
    r = httpx.post(
        settings.gatewayapi_url,
        auth=(settings.gatewayapi_token, ""),
        json={"sender": sender, "message": text, "recipients": [{"msisdn": int(msisdn)}]},
        timeout=15,
    )
    if r.status_code >= 300:
        raise RuntimeError(f"GatewayAPI svarede {r.status_code}: {r.text[:300]}")


def send_email(to: str, subject: str, body: str, from_name: str, html: str | None = None) -> None:
    if not settings.smtp_configured:
        raise RuntimeError("E-mail er ikke sat op (SMTP_HOST/SMTP_FROM mangler)")
    if not valid_email(to):
        raise ValueError(f"Ugyldig e-mailadresse: {to}")
    msg = EmailMessage()
    msg["From"] = formataddr((from_name, settings.smtp_from))
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as s:
        if settings.smtp_starttls:
            s.starttls()
        if settings.smtp_user:
            s.login(settings.smtp_user, settings.smtp_password)
        s.send_message(msg)


def deliver(n: Notification, tenant: Tenant) -> None:
    """Send one notification and record the outcome on the row."""
    if settings.notify_mode != "live":
        n.status = "test"
        return
    try:
        if n.channel == "sms":
            send_sms(tenant.sms_sender, n.recipient, n.body)
        else:
            send_email(n.recipient, n.subject, n.body, tenant.name)
        n.status = "sendt"
        n.error = ""
    except Exception as e:  # noqa: BLE001 - we log every failure on the row
        log.warning("Notification %s failed: %s", n.id, e)
        n.status = "fejl"
        n.error = str(e)[:500]


def notify_visit(visit_id: int) -> None:
    """Background task: build and deliver all messages for a check-in."""
    db = SessionLocal()
    try:
        visit = db.get(Visit, visit_id)
        if visit is None:
            return
        tenant = db.get(Tenant, visit.tenant_id)
        host = db.get(Host, visit.host_id) if visit.host_id else None
        rows = build_messages(visit, tenant, host)
        for n in rows:
            db.add(n)
        db.commit()
        for n in rows:
            deliver(n, tenant)
            db.commit()
    finally:
        db.close()
