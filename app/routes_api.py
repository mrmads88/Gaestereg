"""Offentlig API (v1) for andre systemer (ServiceNow, Salesforce, HR, BI ...). Adgang med en API-nøgle fra admin:

    Authorization: Bearer nodd_...

En nøgle hører til et firma eller et hus (husets nøgle ser alle husets firmaer). Kræver modulet "integrations".
Rettigheder: "read" (læse) og "people:write" (opdatere personlisten). Højst 120 kald pr. minut pr. nøgle.
"""
import hashlib
import json
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import modules, ratelimit, timereg
from .db import get_db
from .models import ApiKey, Booking, Host, Partner, Room, Tenant, TimeEntry, Visit, utcnow
from .timeutil import TZ, local_iso

router = APIRouter(prefix="/api/v1", tags=["api v1"])


class Caller:
    def __init__(self, key: ApiKey, tenant: Tenant | None, partner: Partner | None):
        self.key, self.tenant, self.partner = key, tenant, partner
        self.scopes = set(json.loads(key.scopes or "[]"))

    def tenant_ids(self, db: Session, tenant_id: int | None = None) -> list[int]:
        ids = [self.tenant.id] if self.tenant else list(db.scalars(select(Tenant.id).where(Tenant.partner_id == self.partner.id)).all())
        if tenant_id is not None:
            if tenant_id not in ids:
                raise HTTPException(404, "Firmaet findes ikke")
            return [tenant_id]
        return ids

    def where(self, col, db: Session, tenant_id: int | None = None):
        """Filter på firma: ét firma, eller husets firmaer som underforespørgsel (ingen lange IN-lister)."""
        if tenant_id is not None:
            self.tenant_ids(db, tenant_id)
            return col == tenant_id
        if self.tenant:
            return col == self.tenant.id
        return col.in_(select(Tenant.id).where(Tenant.partner_id == self.partner.id))

    def need(self, scope: str) -> None:
        if scope not in self.scopes:
            raise HTTPException(403, f"Nøglen har ikke rettigheden {scope}")


def caller(request: Request, db: Session = Depends(get_db)) -> Caller:
    auth = request.headers.get("authorization", "")
    key = auth[7:].strip() if auth.lower().startswith("bearer ") else request.headers.get("x-api-key", "").strip()
    if not key.startswith("nodd_"):
        raise HTTPException(401, "Mangler API-nøgle (Authorization: Bearer nodd_...)")
    k = db.scalar(select(ApiKey).where(ApiKey.key_hash == hashlib.sha256(key.encode()).hexdigest()))
    if k is None or k.revoked_at is not None:
        raise HTTPException(401, "Ugyldig eller tilbagekaldt API-nøgle")
    ratelimit.check(f"api:{k.id}", 120, 60)
    ratelimit.hit(f"api:{k.id}")
    t = db.get(Tenant, k.tenant_id) if k.tenant_id else None
    p = db.get(Partner, k.partner_id) if k.partner_id else None
    if (t is None and p is None) or not (modules.tenant_has(t, "integrations") if t else modules.partner_has(p, "integrations")):
        raise HTTPException(403, "Integrationer og API er ikke slået til. Kontakt din leverandør.")
    if k.last_used_at is None or utcnow() - k.last_used_at > timedelta(minutes=5):
        k.last_used_at = utcnow()  # højst hvert 5. minut, så hvert kald ikke skriver i databasen
        db.commit()
    return Caller(k, t, p)


def _day_utc(d: date, end: bool = False) -> datetime:
    from datetime import timezone
    x = datetime(d.year, d.month, d.day, tzinfo=TZ) + (timedelta(days=1) if end else timedelta())
    return x.astimezone(timezone.utc).replace(tzinfo=None)


def _range(frm: date | None, to: date | None, default_days: int = 7) -> tuple[date, date]:
    to = to or timereg.today()
    frm = frm or to - timedelta(days=default_days - 1)
    if frm > to or (to - frm).days > 366:
        raise HTTPException(422, "Vælg en periode på højst et år")
    return frm, to


@router.get("/me")
def me(c: Caller = Depends(caller), db: Session = Depends(get_db)):
    """Hvem nøglen hører til, og hvilke firmaer den ser."""
    ids = c.tenant_ids(db)
    names = dict(db.execute(select(Tenant.id, Tenant.name).where(Tenant.id.in_(ids))).all()) if ids else {}
    return {"key": {"name": c.key.name, "prefix": c.key.prefix, "scopes": sorted(c.scopes)},
            "account": {"type": "company", "id": c.tenant.id, "name": c.tenant.name} if c.tenant else
            {"type": "building", "id": c.partner.id, "name": c.partner.name},
            "companies": [{"id": i, "name": names.get(i, "")} for i in ids]}


@router.get("/visits")
def visits(from_: date | None = Query(None, alias="from"), to: date | None = None, tenant_id: int | None = None, kind: str | None = None,
           limit: int = 500, c: Caller = Depends(caller), db: Session = Depends(get_db)):
    """Besøg og pakker i perioden (standard: de sidste 7 dage). Kun det, der ikke er slettet efter firmaets regler."""
    c.need("read")
    frm, to = _range(from_, to)
    q = select(Visit).where(c.where(Visit.tenant_id, db, tenant_id),
                            Visit.checked_in_at >= _day_utc(frm), Visit.checked_in_at < _day_utc(to, True))
    if kind in ("guest", "delivery"):
        q = q.where(Visit.kind == kind)
    rows = db.scalars(q.order_by(Visit.checked_in_at.desc()).limit(max(1, min(limit, 1000)))).all()
    return {"from": frm.isoformat(), "to": to.isoformat(), "count": len(rows),
            "visits": [{"id": v.id, "company_id": v.tenant_id, "kind": v.kind, "guest_name": v.guest_name,
                        "guest_company": v.guest_company, "host": {"id": v.host_id, "name": v.host_name},
                        "checked_in_at": local_iso(v.checked_in_at), "checked_out_at": local_iso(v.checked_out_at)}
                       for v in rows]}


@router.get("/hosts")
def hosts(tenant_id: int | None = None, c: Caller = Depends(caller), db: Session = Depends(get_db)):
    """Personerne (dem gæsterne kan vælge) med kontaktoplysninger. Firmaets egne data."""
    c.need("read")
    rows = db.scalars(select(Host).where(c.where(Host.tenant_id, db, tenant_id)).order_by(Host.tenant_id, Host.sort_order, Host.id)).all()
    return {"hosts": [{"id": h.id, "company_id": h.tenant_id, "name": h.name, "title": h.title, "email": h.email,
                       "phone": h.phone, "active": h.active, "notify_sms": h.notify_sms, "notify_email": h.notify_email,
                       "time_tracking": h.time_enabled} for h in rows]}


class PersonIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    title: str = Field("", max_length=120)
    email: str = Field("", max_length=200)
    phone: str = Field("", max_length=40)
    active: bool = True


class SyncIn(BaseModel):
    tenant_id: int | None = None
    people: list[PersonIn] = Field(max_length=2000)
    deactivate_missing: bool = False


@router.post("/hosts/sync")
def sync_hosts(body: SyncIn, c: Caller = Depends(caller), db: Session = Depends(get_db)):
    """Opdatér personlisten fra fx HR eller Microsoft 365. Personer matches på e-mail (ellers navn). Nye oprettes,
    eksisterende opdateres. deactivate_missing: personer, der ikke er med, skjules (slettes ikke)."""
    c.need("people:write")
    if c.partner and body.tenant_id is None:
        raise HTTPException(422, "Angiv tenant_id (firmaet i huset)")
    tid = c.tenant_ids(db, body.tenant_id)[0]
    existing = db.scalars(select(Host).where(Host.tenant_id == tid)).all()
    by_email = {h.email.strip().lower(): h for h in existing if h.email.strip()}
    by_name = {h.name.strip().lower(): h for h in existing}
    order = max((h.sort_order for h in existing), default=-1)
    seen, created, updated = set(), 0, 0
    for p in body.people:
        email = p.email.strip().lower()
        h = by_email.get(email) if email else by_name.get(p.name.strip().lower())
        if h is None:
            order += 1
            h = Host(tenant_id=tid, name=p.name.strip(), title=p.title.strip(), email=p.email.strip(), phone=p.phone.strip(),
                     active=p.active, sort_order=order, notify_sms=bool(p.phone.strip()), notify_email=bool(email))
            db.add(h)
            created += 1
        else:
            changed = (h.name, h.title, h.email, h.phone, h.active) != (p.name.strip(), p.title.strip(), p.email.strip(), p.phone.strip(), p.active)
            h.name, h.title, h.email, h.phone, h.active = p.name.strip(), p.title.strip(), p.email.strip(), p.phone.strip(), p.active
            updated += int(changed)
        seen.add(id(h))
    deactivated = 0
    if body.deactivate_missing:
        for h in existing:
            if id(h) not in seen and h.active:
                h.active = False
                deactivated += 1
    db.commit()
    from .routes_kiosk import clear_config_cache
    clear_config_cache()  # skærmene viser de nye personer med det samme
    total = db.scalar(select(func.count()).select_from(Host).where(Host.tenant_id == tid))
    return {"created": created, "updated": updated, "deactivated": deactivated, "total": total}


@router.get("/bookings")
def bookings(from_: date | None = Query(None, alias="from"), to: date | None = None, tenant_id: int | None = None,
             c: Caller = Depends(caller), db: Session = Depends(get_db)):
    """Firmaets egne bookinger (med titler) i perioden (standard: i dag og 6 dage frem)."""
    c.need("read")
    frm = from_ or timereg.today()
    frm, to = _range(frm, to or frm + timedelta(days=6))
    rows = db.execute(select(Booking, Room).join(Room, Room.id == Booking.room_id).where(
        c.where(Booking.tenant_id, db, tenant_id), Booking.start_at >= _day_utc(frm), Booking.start_at < _day_utc(to, True))
        .order_by(Booking.start_at)).all()
    return {"bookings": [{"id": b.id, "company_id": b.tenant_id, "title": b.title, "organizer": b.organizer,
                          "attendees": b.attendees, "status": b.status, "start": local_iso(b.start_at),
                          "end": local_iso(b.end_at), "room": {"id": r.id, "name": r.name, "location": r.location}}
                         for b, r in rows]}


@router.get("/time-entries")
def time_entries(from_: date | None = Query(None, alias="from"), to: date | None = None, tenant_id: int | None = None,
                 c: Caller = Depends(caller), db: Session = Depends(get_db)):
    """Arbejdstid (fx til Salary, Danløn eller BI). Kræver modulet Tidsregistrering."""
    c.need("read")
    frm, to = _range(from_, to)
    ids = [i for i in c.tenant_ids(db, tenant_id) if modules.tenant_has(db.get(Tenant, i), "time")]
    rows = db.scalars(select(TimeEntry).where(c.where(TimeEntry.tenant_id, db, tenant_id), TimeEntry.start_at >= _day_utc(frm),
                                              TimeEntry.start_at < _day_utc(to, True)).order_by(TimeEntry.start_at)).all() if ids else []
    rows = [e for e in rows if e.tenant_id in ids]  # kun firmaer med Tidsregistrering
    return {"entries": [{"id": e.id, "company_id": e.tenant_id, "employee": {"id": e.host_id, "name": e.name},
                         "start": local_iso(e.start_at), "end": local_iso(e.end_at), "break_minutes": e.break_min,
                         "minutes": timereg.minutes(e), "approved": e.approved_at is not None, "source": e.source}
                        for e in rows]}
