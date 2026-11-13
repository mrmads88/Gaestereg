"""Forventede gæster: koder, links, beskeden til gæsten og opslag ved skærmen.

Gæsten får en 6-cifret kode og et link til en side med QR-koden. Værter uden login får et personligt
invitationslink (signeret, uden udløb), som kan laves om, hvis det er kommet i forkerte hænder.
"""
import logging
import secrets
from datetime import timedelta

import segno
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner, URLSafeSerializer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import Host, Invitation, Notification, Tenant, utcnow
from .notify import deliver, valid_email
from .timeutil import local_day_label, local_hhmm

log = logging.getLogger("gaestereg.invitations")

GUEST_PASS_MAX_AGE = 60 * 24 * 3600
_host_links = URLSafeSerializer(settings.secret_key, salt="host-invite")
_guest_pass = TimestampSigner(settings.secret_key, salt="guest-pass")


# ---------- links ----------

def host_token(h: Host) -> str:
    return _host_links.dumps([h.id, h.link_version])


def host_from_token(db: Session, token: str) -> Host | None:
    try:
        hid, version = _host_links.loads(token)
    except (BadSignature, ValueError, TypeError):
        return None
    h = db.get(Host, hid)
    return h if h is not None and h.link_version == version and h.active else None


def guest_token(inv: Invitation) -> str:
    return _guest_pass.sign(str(inv.id).encode()).decode()


def invitation_from_guest_token(db: Session, token: str) -> Invitation | None:
    try:
        iid = int(_guest_pass.unsign(token, max_age=GUEST_PASS_MAX_AGE).decode())
    except (BadSignature, SignatureExpired, ValueError):
        return None
    return db.get(Invitation, iid)


def qr_svg(data: str, scale: int = 8) -> str:
    # omitsize: viewBox i stedet for fast bredde/højde, så QR-koden kan skaleres med CSS.
    return segno.make(data, error="m", micro=False).svg_inline(scale=scale, border=2, dark="#111111", omitsize=True)


# ---------- create ----------

def new_code(db: Session, tenant_id: int) -> str:
    """6 cifre, unikke blandt kundens ventende invitationer."""
    used = set(db.scalars(select(Invitation.code).where(Invitation.tenant_id == tenant_id,
                                                         Invitation.status == "pending")))
    while True:
        c = f"{secrets.randbelow(1_000_000):06d}"
        if c not in used:
            return c


def create(db: Session, t: Tenant, host: Host | None, data: dict, created_by: str) -> Invitation:
    inv = Invitation(tenant_id=t.id, host_id=host.id if host else None, host_name=host.name if host else "Receptionen",
                     guest_name=" ".join(data["guest_name"].split()), guest_phone=data.get("guest_phone", "").strip(),
                     guest_email=data.get("guest_email", "").strip().lower(),
                     guest_company=" ".join(data.get("guest_company", "").split()),
                     expected_at=data["expected_at"], code=new_code(db, t.id), created_by=created_by)
    db.add(inv)
    db.commit()
    return inv


def guest_messages(inv: Invitation, t: Tenant, base_url: str) -> list[Notification]:
    first = inv.guest_name.split(" ")[0] if inv.guest_name else ""
    host_first = inv.host_name.split(" ")[0]
    when = f"{local_day_label(inv.expected_at)} kl. {local_hhmm(inv.expected_at)}"
    link = f"{base_url.rstrip('/')}/g/{guest_token(inv)}" if base_url else ""
    sms = (f"Hej {first}. Du er ventet hos {t.name} {when} af {host_first}. "
           f"Tjek ind med koden {inv.code} på skærmen i receptionen." + (f" QR-kode: {link}" if link else ""))
    body = (f"Hej {first}\n\n{host_first} venter dig hos {t.name} {when}.\n\n"
            f"Når du kommer, så tjek ind på skærmen i receptionen med koden {inv.code}, eller vis QR-koden her:\n"
            f"{link}\n\nSå får {host_first} besked med det samme.\n\nVenlig hilsen\n{t.name}")
    out = []
    if inv.guest_phone:
        out.append(Notification(tenant_id=t.id, channel="sms", recipient=inv.guest_phone, body=sms))
    if inv.guest_email and valid_email(inv.guest_email):
        out.append(Notification(tenant_id=t.id, channel="email", recipient=inv.guest_email,
                                subject=f"Du er ventet hos {t.name} {when}", body=body))
    return out


def send_to_guest(invitation_id: int, base_url: str) -> None:
    """Baggrundsopgave: send kode og link til gæsten."""
    from .db import SessionLocal
    db = SessionLocal()
    try:
        inv = db.get(Invitation, invitation_id)
        if inv is None or inv.status != "pending":
            return
        t = db.get(Tenant, inv.tenant_id)
        rows = guest_messages(inv, t, base_url)
        for n in rows:
            db.add(n)
        db.commit()
        for n in rows:
            deliver(n, t)
            db.commit()
    finally:
        db.close()


# ---------- check-in ----------

def find_by_code(db: Session, t: Tenant, code: str) -> Invitation | None:
    """En ventende invitation med koden, forventet fra i går til i morgen (så en gæst kan komme lidt skævt)."""
    code = "".join(c for c in code if c.isdigit())
    if len(code) != 6:
        return None
    now = utcnow()
    return db.scalar(select(Invitation).where(
        Invitation.tenant_id == t.id, Invitation.code == code, Invitation.status == "pending",
        Invitation.expected_at >= now - timedelta(hours=36), Invitation.expected_at <= now + timedelta(hours=36)))


def out(inv: Invitation, base_url: str = "") -> dict:
    from .timeutil import local_iso
    return {"id": inv.id, "host_id": inv.host_id, "host_name": inv.host_name, "guest_name": inv.guest_name,
            "guest_phone": inv.guest_phone, "guest_email": inv.guest_email, "guest_company": inv.guest_company,
            "expected_at": local_iso(inv.expected_at), "code": inv.code, "status": inv.status,
            "created_by": inv.created_by,
            "guest_url": f"{base_url.rstrip('/')}/g/{guest_token(inv)}" if base_url else ""}
