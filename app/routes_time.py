"""Tidsregistrering: stempling på skærmen (PIN) og telefonen (/t/<token>), og admin-fanen "Tid". Se timereg.py."""
import secrets
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import integrations, invitations, modules, ratelimit, timereg
from .auth import Principal, current
from .db import get_db
from .media import media_url
from .models import Host, Tenant, TimeEntry, utcnow
from .routes_admin import _host as admin_host, get_tenant_for
from .routes_kiosk import tenant_by_token
from .timeutil import TZ, local_iso

STATIC = Path(__file__).parent / "static"

pages = APIRouter(include_in_schema=False)
public = APIRouter(tags=["tid"])
admin = APIRouter(prefix="/api/admin", tags=["tid"], dependencies=[Depends(current)])

PIN_LIMIT, PIN_WINDOW = 5, 15 * 60  # forkerte PIN pr. medarbejder
SCREEN_LIMIT = 30  # forkerte PIN pr. skærm


class KioskClockIn(BaseModel):
    host_id: int
    pin: str = Field(max_length=12)


class EntryIn(BaseModel):
    host_id: int
    start: datetime
    end: datetime | None = None
    break_min: int = Field(0, ge=0, le=600)
    note: str = Field("", max_length=300)


class EntryPatch(BaseModel):
    start: datetime | None = None
    end: datetime | None = None
    break_min: int | None = Field(None, ge=0, le=600)
    note: str | None = Field(None, max_length=300)


class ApproveIn(BaseModel):
    monday: date
    host_ids: list[int] | None = None
    approve: bool = True


class SettingsIn(BaseModel):
    time_kiosk: bool | None = None
    time_break_min: int | None = Field(None, ge=0, le=120)


class HostTimeIn(BaseModel):
    time_enabled: bool | None = None
    time_norm_min: int | None = Field(None, ge=0, le=60 * 60)


def _to_utc(dt: datetime) -> datetime:
    """Tider fra admin er lokal tid (uden zone) eller med zone. Gemmes som UTC uden zone."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.astimezone(timezone.utc).replace(tzinfo=None, microsecond=0)


def _who(p: Principal) -> str:
    return (p.user.name or p.user.email) if p.user else "Leverandøren"


def _greeting(state: str, h: Host, e: TimeEntry, total: int) -> dict:
    return {"state": state, "name": h.name, "first": h.name.split()[0], "at": local_iso(e.end_at or e.start_at),
            "hhmm": local_iso(e.end_at or e.start_at)[11:16], "today_min": total, "today": timereg.hm(total)}


# ---------- skærmen ----------

@public.post("/api/kiosk/{token}/time")
def kiosk_clock(token: str, body: KioskClockIn, db: Session = Depends(get_db)):
    t = tenant_by_token(token, db)
    if not (t.time_kiosk and modules.tenant_has(t, "time")):
        raise HTTPException(404, "Tidsregistrering er ikke slået til")
    screen_key, key = f"time-screen:{token}", f"time-pin:{body.host_id}"
    ratelimit.check(screen_key, SCREEN_LIMIT, PIN_WINDOW)
    ratelimit.check(key, PIN_LIMIT, PIN_WINDOW)
    h = db.get(Host, body.host_id)
    if h is None or h.tenant_id != t.id or not h.active or not h.time_enabled:
        raise HTTPException(404, "Medarbejderen findes ikke")
    if not timereg.check_pin(h, body.pin.strip()):
        ratelimit.hit(key)
        ratelimit.hit(screen_key)
        raise HTTPException(401, "Forkert PIN" if h.time_pin else "Du har ingen PIN endnu. Spørg din administrator.")
    ratelimit.clear(key)
    state, e = timereg.clock(db, h, "kiosk")
    db.commit()
    return _greeting(state, h, e, timereg.day_total(db, h, timereg.today()))


# ---------- medarbejderens telefon ----------

def _staff(db: Session, token: str) -> tuple[Host, Tenant]:
    h = invitations.host_from_token(db, token)
    if h is None:
        raise HTTPException(404, "Linket virker ikke længere. Bed din administrator om et nyt.")
    t = db.get(Tenant, h.tenant_id)
    if not h.time_enabled or not modules.tenant_has(t, "time"):
        raise HTTPException(404, "Tidsregistrering er ikke slået til for dig")
    return h, t


@pages.get("/t/{token}")
def time_page(token: str):
    return FileResponse(STATIC / "time.html", headers={"Cache-Control": "no-cache"})


@public.get("/api/time/{token}")
def my_time(token: str, week: date | None = None, db: Session = Depends(get_db)):
    h, t = _staff(db, token)
    monday = timereg.monday_of(week or timereg.today())
    return {**timereg.personal(db, h, monday), "firm": t.name, "color": t.color, "logo_url": media_url(t.logo_path)}


@public.post("/api/time/{token}/clock")
def my_clock(token: str, db: Session = Depends(get_db)):
    h, _ = _staff(db, token)
    ratelimit.check(f"time-phone:{h.id}", 20, 60)  # mod dobbeltklik og gentagne tryk
    ratelimit.hit(f"time-phone:{h.id}")
    state, e = timereg.clock(db, h, "phone")
    db.commit()
    return _greeting(state, h, e, timereg.day_total(db, h, timereg.today()))


# ---------- admin ----------

def _tenant(db: Session, tid: int, p: Principal) -> Tenant:
    t = get_tenant_for(db, tid, p)
    if not p.is_platform:
        modules.require_tenant(t, "time")
    return t


def _entry(db: Session, eid: int, p: Principal) -> tuple[TimeEntry, Tenant]:
    e = db.get(TimeEntry, eid)
    if e is None:
        raise HTTPException(404, "Posten findes ikke")
    return e, _tenant(db, e.tenant_id, p)


def _check_times(start: datetime, end: datetime | None) -> None:
    if end is not None and end <= start:
        raise HTTPException(422, "Ud skal være efter ind")
    if end is not None and end - start > timedelta(hours=24):
        raise HTTPException(422, "En post kan højst vare 24 timer")
    if start > utcnow() + timedelta(minutes=5):
        raise HTTPException(422, "Tiden ligger i fremtiden")


@admin.get("/tenants/{tid}/time/week")
def admin_week(tid: int, monday: date | None = None, db: Session = Depends(get_db), p: Principal = Depends(current)):
    t = _tenant(db, tid, p)
    data = timereg.week(db, t, timereg.monday_of(monday or timereg.today()))
    data["settings"] = {"time_kiosk": t.time_kiosk, "time_break_min": t.time_break_min}
    data["staff"] = [{"id": h.id, "name": h.name, "title": h.title, "active": h.active, "time_enabled": h.time_enabled,
                      "time_norm_min": h.time_norm_min, "has_pin": bool(h.time_pin)} for h in t.hosts]
    return data


@admin.patch("/tenants/{tid}/time/settings")
def admin_settings(tid: int, body: SettingsIn, db: Session = Depends(get_db), p: Principal = Depends(current)):
    t = _tenant(db, tid, p)
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(t, k, v)
    db.commit()
    return {"time_kiosk": t.time_kiosk, "time_break_min": t.time_break_min}


@admin.patch("/hosts/{hid}/time")
def admin_host_time(hid: int, body: HostTimeIn, db: Session = Depends(get_db), p: Principal = Depends(current)):
    h = admin_host(db, hid, p)
    _tenant(db, h.tenant_id, p)
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(h, k, v)
    db.commit()
    return {"id": h.id, "time_enabled": h.time_enabled, "time_norm_min": h.time_norm_min, "has_pin": bool(h.time_pin)}


@admin.post("/hosts/{hid}/time/pin")
def admin_new_pin(hid: int, db: Session = Depends(get_db), p: Principal = Depends(current)):
    """Ny 4-cifret PIN til skærmen. Vises kun her, én gang."""
    h = admin_host(db, hid, p)
    _tenant(db, h.tenant_id, p)
    pin = f"{secrets.randbelow(10000):04d}"
    timereg.set_pin(h, pin)
    h.time_enabled = True
    db.commit()
    ratelimit.clear(f"time-pin:{h.id}")
    return {"pin": pin, "name": h.name}


@admin.get("/hosts/{hid}/time/link")
def admin_phone_link(hid: int, db: Session = Depends(get_db), p: Principal = Depends(current)):
    h = admin_host(db, hid, p)
    _tenant(db, h.tenant_id, p)
    return {"path": f"/t/{invitations.host_token(h)}"}


@admin.post("/tenants/{tid}/time/entries")
def admin_add(tid: int, body: EntryIn, db: Session = Depends(get_db), p: Principal = Depends(current)):
    t = _tenant(db, tid, p)
    h = db.get(Host, body.host_id)
    if h is None or h.tenant_id != t.id:
        raise HTTPException(404, "Medarbejderen findes ikke")
    start, end = _to_utc(body.start), _to_utc(body.end) if body.end else None
    _check_times(start, end)
    e = TimeEntry(tenant_id=t.id, host_id=h.id, name=h.name, start_at=start, end_at=end, break_min=body.break_min,
                  note=body.note.strip(), source="admin")
    db.add(e)
    db.flush()
    timereg.log_edit(e, _who(p), "oprettet", {}, timereg.snapshot(e))
    db.commit()
    return timereg.entry_out(e)


@admin.patch("/time/entries/{eid}")
def admin_edit(eid: int, body: EntryPatch, db: Session = Depends(get_db), p: Principal = Depends(current)):
    e, _ = _entry(db, eid, p)
    if e.approved_at is not None:
        raise HTTPException(409, "Ugen er godkendt. Genåbn den for at rette.")
    before = timereg.snapshot(e)
    data = body.model_dump(exclude_unset=True)
    start = _to_utc(data["start"]) if data.get("start") else e.start_at
    end = _to_utc(data["end"]) if data.get("end") else (None if "end" in data else e.end_at)
    _check_times(start, end)
    e.start_at, e.end_at = start, end
    if data.get("break_min") is not None:
        e.break_min = data["break_min"]
    if data.get("note") is not None:
        e.note = data["note"].strip()
    after = timereg.snapshot(e)
    if after != before:
        timereg.log_edit(e, _who(p), "rettet", before, after)
    db.commit()
    return timereg.entry_out(e)


@admin.delete("/time/entries/{eid}")
def admin_delete(eid: int, db: Session = Depends(get_db), p: Principal = Depends(current)):
    e, _ = _entry(db, eid, p)
    if e.approved_at is not None:
        raise HTTPException(409, "Ugen er godkendt. Genåbn den for at slette.")
    db.delete(e)
    db.commit()
    return {"ok": True}


@admin.post("/tenants/{tid}/time/approve")
def admin_approve(tid: int, body: ApproveIn, db: Session = Depends(get_db), p: Principal = Depends(current)):
    """Godkend (eller genåbn) en uge for alle eller udvalgte medarbejdere. Åbne stemplinger kan ikke godkendes."""
    t = _tenant(db, tid, p)
    monday = timereg.monday_of(body.monday)
    rows = [e for e in timereg.entries(db, t.id, monday, monday + timedelta(days=6))
            if body.host_ids is None or e.host_id in body.host_ids]
    if body.approve:
        if any(e.end_at is None for e in rows):
            raise HTTPException(409, "Der er stemplinger uden udstempling i ugen. Ret dem først.")
        now, who = utcnow(), _who(p)
        n = 0
        for e in rows:
            if e.approved_at is None:
                e.approved_at, e.approved_by = now, who
                n += 1
    else:
        n = 0
        for e in rows:
            if e.approved_at is not None:
                timereg.log_edit(e, _who(p), "genåbnet", {"approved_by": e.approved_by}, {})
                e.approved_at, e.approved_by = None, ""
                n += 1
    db.commit()
    if body.approve and n:
        totals: dict[str, int] = {}
        for e in rows:
            totals[e.name] = totals.get(e.name, 0) + timereg.minutes(e)
        integrations.emit(db, "time.week_approved", {"week": {
            "monday": monday.isoformat(), "number": monday.isocalendar()[1], "approved_by": _who(p),
            "employees": [{"name": k, "minutes": v, "hours": round(v / 60, 2)} for k, v in sorted(totals.items())]}}, tenant=t)
    return {"changed": n}


@admin.get("/tenants/{tid}/time/export.csv")
def admin_export(tid: int, start: date, end: date, db: Session = Depends(get_db), p: Principal = Depends(current)):
    t = _tenant(db, tid, p)
    if end < start or (end - start).days > 400:
        raise HTTPException(422, "Vælg en periode på højst et år")
    return Response(timereg.export_csv(db, t, start, end), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="arbejdstid-{start}-{end}.csv"'})

