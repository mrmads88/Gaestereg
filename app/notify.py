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


def join_names(names: list[str]) -> str:
    names = [n for n in names if n]
    if len(names) <= 1:
        return names[0] if names else ""
    return ", ".join(names[:-1]) + " og " + names[-1]


def context_for(visit: Visit, tenant: Tenant, host_name: str, guests: list[str] | None = None) -> dict:
    return {
        "gaest": join_names(guests) if guests else (visit.guest_name or "En gæst"),
        "telefon": visit.guest_phone or "ikke oplyst",
        "firma": visit.guest_company or "ikke oplyst",
        "vaert": host_name,
        "vaert_fornavn": (host_name or "").split(" ")[0] if host_name else "",
        "tid": local_hhmm(visit.checked_in_at),
        "kunde": tenant.name,
    }


def _with_reply_link(text: str, url: str, channel: str) -> str:
    if not url:
        return text
    if "{svarlink}" in text:
        return text.replace("{svarlink}", url)
    return text + ("\nSvar: " if channel == "sms" else "\n\nSvar din gæst her: ") + url


def build_messages(visit: Visit, tenant: Tenant, host: Host | None, base_url: str = "",
                   guests: list[str] | None = None) -> list[Notification]:
    """Decide who gets what. Returns unsaved Notification rows."""
    from . import replies
    out: list[Notification] = []
    reply_url = replies.link(base_url, visit.id) if host is not None and tenant.host_reply and visit.id else ""
    if host is not None:
        ctx = context_for(visit, tenant, host.name, guests)
        targets = [("sms", host.phone, host.notify_sms), ("email", host.email, host.notify_email)]
    else:
        ctx = context_for(visit, tenant, "receptionen", guests)
        ctx["vaert_fornavn"] = "receptionen"
        targets = [("sms", tenant.reception_phone, True), ("email", tenant.reception_email, True)]

    for channel, addr, wanted in targets:
        if not wanted or not (addr or "").strip():
            continue
        if channel == "sms":
            out.append(Notification(tenant_id=tenant.id, visit_id=visit.id, channel="sms", recipient=addr.strip(),
                                    body=_with_reply_link(render(tenant.sms_template, ctx), reply_url, "sms")))
        else:
            out.append(Notification(tenant_id=tenant.id, visit_id=visit.id, channel="email",
                                    recipient=addr.strip(), subject=render(tenant.email_subject, ctx),
                                    body=_with_reply_link(render(tenant.email_template, ctx), reply_url, "email")))
    if tenant.teams_webhook:
        who = host.name if host is not None else "receptionen"
        out.append(Notification(tenant_id=tenant.id, visit_id=visit.id, channel="teams", recipient="Teams",
                                subject=f"Gæst til {who}",
                                body=f"{ctx['gaest']} er ankommet kl. {ctx['tid']} og venter på {who}."
                                     + (f" Firma: {visit.guest_company}." if visit.guest_company else "")))
    return out


def _to_contacts(tenant: Tenant, visit: Visit, phone: str, email: str, sms: str, subject: str, body: str,
                 teams: str) -> list[Notification]:
    out = []
    if phone.strip():
        out.append(Notification(tenant_id=tenant.id, visit_id=visit.id, channel="sms", recipient=phone.strip(), body=sms))
    if email.strip():
        out.append(Notification(tenant_id=tenant.id, visit_id=visit.id, channel="email", recipient=email.strip(),
                                subject=subject, body=body))
    if tenant.teams_webhook:
        out.append(Notification(tenant_id=tenant.id, visit_id=visit.id, channel="teams", recipient="Teams",
                                subject=subject, body=teams))
    return out


def build_delivery(visit: Visit, tenant: Tenant, host: Host | None) -> list[Notification]:
    """En pakke er afleveret: til den valgte person, ellers godsmodtagelsen, ellers receptionen."""
    fra = f" fra {visit.guest_company}" if visit.guest_company else ""
    if host is not None:
        first = host.name.split(" ")[0]
        sms = f"Hej {first}. Der er en pakke til dig i receptionen{fra}."
        phone, email = (host.phone if host.notify_sms else ""), (host.email if host.notify_email else "")
    else:
        sms = f"Der er kommet en pakke{fra} til {tenant.name}."
        phone = tenant.delivery_phone or tenant.reception_phone
        email = tenant.delivery_email or tenant.reception_email
    body = sms + f"\n\nAfleveret kl. {local_hhmm(visit.checked_in_at)}." + (
        f" Bud: {visit.guest_name}." if visit.guest_name else "") + f"\n\n{tenant.name}"
    return _to_contacts(tenant, visit, phone, email, sms, "Pakke i receptionen", body, sms)


def build_escalation(visit: Visit, tenant: Tenant, guests: list[str], declined: bool = False) -> list[Notification]:
    """Værten har ikke svaret (eller har svaret, at de ikke kan). Receptionen får besked."""
    g = join_names(guests) or visit.guest_name or "En gæst"
    tid = local_hhmm(visit.checked_in_at)
    if declined:
        sms = f"{visit.host_name} kan ikke tage imod {g}, der venter i receptionen. Kan du hjælpe?"
    else:
        sms = f"{g} har ventet på {visit.host_name} siden kl. {tid} uden svar. Kan du hjælpe?"
    body = sms + (f"\n\nTelefon: {visit.guest_phone}" if visit.guest_phone else "") + f"\n\n{tenant.name}"
    return _to_contacts(tenant, visit, tenant.reception_phone, tenant.reception_email, sms,
                        f"Gæst venter: {g}", body, sms)


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


def send_teams(url: str, title: str, text: str) -> None:
    """Teams-kanal via en Workflows-webhook ("Post to a channel when a webhook request is received")."""
    card = {"type": "message", "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive", "content": {
        "type": "AdaptiveCard", "version": "1.4", "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "body": [{"type": "TextBlock", "text": title, "weight": "Bolder", "size": "Medium", "wrap": True},
                 {"type": "TextBlock", "text": text, "wrap": True}]}}]}
    r = httpx.post(url, json=card, timeout=15)
    if r.status_code >= 300:
        raise RuntimeError(f"Teams svarede {r.status_code}: {r.text[:300]}")


def deliver(n: Notification, tenant: Tenant) -> None:
    """Send one notification and record the outcome on the row."""
    if settings.notify_mode != "live":
        n.status = "test"
        return
    try:
        if n.channel == "sms":
            send_sms(tenant.sms_sender, n.recipient, n.body)
        elif n.channel == "teams":
            send_teams(tenant.teams_webhook, n.subject, n.body)
        else:
            send_email(n.recipient, n.subject, n.body, tenant.name)
        n.status = "sendt"
        n.error = ""
    except Exception as e:  # noqa: BLE001 - we log every failure on the row
        log.warning("Notification %s failed: %s", n.id, e)
        n.status = "fejl"
        n.error = str(e)[:500]


def _deliver_all(db, tenant: Tenant, rows: list[Notification]) -> None:
    for n in rows:
        db.add(n)
    db.commit()
    for n in rows:
        deliver(n, tenant)
        db.commit()


def _group(db, visit: Visit) -> list[Visit]:
    if not visit.group_ref:
        return [visit]
    from sqlalchemy import select
    return list(db.scalars(select(Visit).where(Visit.tenant_id == visit.tenant_id, Visit.group_ref == visit.group_ref)
                          .order_by(Visit.id)))


def notify_visit(visit_id: int, base_url: str = "") -> None:
    """Background task: build and deliver all messages for a check-in (one set per group)."""
    db = SessionLocal()
    try:
        visit = db.get(Visit, visit_id)
        if visit is None:
            return
        tenant = db.get(Tenant, visit.tenant_id)
        if visit.kind == "delivery":
            host = db.get(Host, visit.host_id) if visit.host_id else None
            _deliver_all(db, tenant, build_delivery(visit, tenant, host))
            return
        host = db.get(Host, visit.host_id) if visit.host_id else None
        guests = [v.guest_name for v in _group(db, visit)]
        _deliver_all(db, tenant, build_messages(visit, tenant, host, base_url, guests if len(guests) > 1 else None))
    finally:
        db.close()


def escalate(visit_id: int, declined: bool = False) -> None:
    """Påmindelse til receptionen. Kaldes af en timer (ingen svar) eller når værten svarer, at de ikke kan."""
    db = SessionLocal()
    try:
        visit = db.get(Visit, visit_id)
        if visit is None or (visit.host_reply and not declined) or visit.checked_out_at is not None:
            return
        tenant = db.get(Tenant, visit.tenant_id)
        rows = build_escalation(visit, tenant, [v.guest_name for v in _group(db, visit)], declined)
        if rows:
            _deliver_all(db, tenant, rows)
    except Exception as e:  # noqa: BLE001 - en timer må aldrig vælte appen
        log.warning("Påmindelse for besøg %s fejlede: %s", visit_id, e)
    finally:
        db.close()
