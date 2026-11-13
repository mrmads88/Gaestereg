"""Public API used by the kiosk screen. Identified only by the tenant's secret kiosk token."""
import re
import time

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from . import presence
from .config import settings
from .db import SessionLocal, get_db
from .models import Host, Notification, Tenant, Visit, utcnow
from .notify import notify_visit
from .schemas import CheckinIn, tenant_public
from .timeutil import days_ago_utc, local_hhmm, start_of_local_day_utc

router = APIRouter(prefix="/api/kiosk", tags=["kiosk"])


def tenant_by_token(token: str, db: Session) -> Tenant:
    t = db.scalar(select(Tenant).where(Tenant.kiosk_token == token))
    if t is None or not t.active:
        raise HTTPException(404, "Denne skærm er ikke sat op")
    return t


def purge_old(db: Session, tenant: Tenant) -> int:
    """Delete visits (and their messages) older than the tenant's retention period."""
    cutoff = days_ago_utc(tenant.retention_days)
    old = (Visit.tenant_id == tenant.id, Visit.checked_in_at < cutoff)
    # Subquery i stedet for en liste af id'er: SQL Server tillader højst 2100 parametre pr. forespørgsel.
    db.execute(delete(Notification).where(Notification.visit_id.in_(select(Visit.id).where(*old))))
    n = db.execute(delete(Visit).where(*old)).rowcount
    db.execute(delete(Notification).where(Notification.tenant_id == tenant.id, Notification.created_at < cutoff))
    db.commit()
    return n


def short_name(full: str) -> str:
    parts = full.split()
    if len(parts) < 2:
        return full
    return f"{parts[0]} {parts[-1][0]}."


# Skærmen henter sin opsætning hvert minut. Svaret gemmes i hukommelsen, så databasen ikke
# vækkes hele tiden (Azure SQL's gratis-database går på pause, når den ikke bruges, og
# gratis-forbruget er begrænset). Cachen tømmes, når admin ændrer noget (se main.py).
# Én worker (startup.sh), så alle forespørgsler ser den samme cache.
_config_cache: dict[str, tuple[float, dict]] = {}


def clear_config_cache() -> None:
    _config_cache.clear()


@router.get("/{token}/config")
def config(token: str, pv: bool = False):
    if not pv:  # forhåndsvisningen i admin tæller ikke som en skærm
        presence.mark(token)
    hit = _config_cache.get(token)
    if hit and time.monotonic() - hit[0] < settings.kiosk_cache_seconds:
        return hit[1]
    with SessionLocal() as db:
        data = tenant_public(tenant_by_token(token, db))
    _config_cache[token] = (time.monotonic(), data)
    return data


@router.post("/{token}/checkin")
def checkin(token: str, body: CheckinIn, bg: BackgroundTasks, db: Session = Depends(get_db)):
    presence.mark(token)
    t = tenant_by_token(token, db)
    name = " ".join(body.guest_name.split())
    phone = body.guest_phone.strip()
    company = " ".join(body.guest_company.split())

    if t.name_required and len(name) < 2:
        raise HTTPException(422, "Skriv dit navn")
    if t.ask_phone and t.phone_required and len(re.sub(r"\D", "", phone)) < 8:
        raise HTTPException(422, "Skriv et gyldigt telefonnummer")
    if not t.ask_phone:
        phone = ""
    if not t.ask_company:
        company = ""

    host = None
    if body.host_id is not None:
        host = db.get(Host, body.host_id)
        if host is None or host.tenant_id != t.id or not host.active:
            raise HTTPException(404, "Personen findes ikke længere. Vælg igen")
    elif not t.allow_unknown_host:
        raise HTTPException(422, "Vælg hvem du skal besøge")

    host_name = host.name if host else "Receptionen"
    if body.preview:
        # Admin preview: show the whole flow without storing or sending anything.
        return {"visit_id": 0, "badge_no": "G-0000", "guest_name": name, "host_name": host_name,
                "time": local_hhmm(utcnow()), "preview": True}

    v = Visit(tenant_id=t.id, host_id=host.id if host else None, host_name=host_name,
              guest_name=name, guest_phone=phone, guest_company=company)
    db.add(v)
    db.commit()
    bg.add_task(notify_visit, v.id)
    purge_old(db, t)
    return {"visit_id": v.id, "badge_no": f"G-{v.id:04d}", "guest_name": name, "host_name": host_name,
            "time": local_hhmm(v.checked_in_at), "preview": False}


@router.get("/{token}/inside")
def inside(token: str, db: Session = Depends(get_db)):
    presence.mark(token)
    """Guests checked in today and not yet out. Short names only, since the screen is public."""
    t = tenant_by_token(token, db)
    rows = db.scalars(
        select(Visit).where(Visit.tenant_id == t.id, Visit.checked_out_at.is_(None),
                            Visit.checked_in_at >= start_of_local_day_utc())
        .order_by(Visit.checked_in_at.desc())
    )
    return [{"id": v.id, "name": short_name(v.guest_name or "Gæst"), "host_name": v.host_name,
             "time": local_hhmm(v.checked_in_at)} for v in rows]


@router.post("/{token}/checkout/{visit_id}")
def checkout(token: str, visit_id: int, db: Session = Depends(get_db)):
    presence.mark(token)
    t = tenant_by_token(token, db)
    v = db.get(Visit, visit_id)
    if v is None or v.tenant_id != t.id:
        raise HTTPException(404, "Besøget findes ikke")
    if v.checked_out_at is None:
        v.checked_out_at = utcnow()
        db.commit()
    return {"ok": True, "name": (v.guest_name or "").split(" ")[0]}
