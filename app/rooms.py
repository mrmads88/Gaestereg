"""Mødelokaler og bookinger (fase 5a).

Lokaler hører til et firma eller til huset (partneren). Et firma kan booke sine egne lokaler og husets lokaler.
Lokaleskærmens tilstand caches i hukommelsen, så skærmens polling ikke vækker databasen. Cachen tømmes ved
enhver ændring af lokaler eller bookinger (clear_cache).
"""
import json
import time
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import or_, select, true
from sqlalchemy.orm import Session

from .media import media_url
from .models import Booking, Partner, Room, Tenant, utcnow
from .timeutil import TZ, from_local, local_iso, to_local

PRIVACY = ("title", "organizer", "busy")
MAX_MINUTES = 12 * 60


# ---------- hvem må hvad ----------

def rooms_for_tenant(db: Session, t: Tenant, active_only: bool = True) -> list[Room]:
    """Lokaler et firma kan booke: firmaets egne og husets (partnerens)."""
    cond = Room.tenant_id == t.id
    if t.partner_id is not None:
        cond = or_(cond, Room.partner_id == t.partner_id)
    q = select(Room).where(cond)
    if active_only:
        q = q.where(Room.active == true())
    return list(db.scalars(q.order_by(Room.sort_order, Room.name)))


def can_book(t: Tenant, room: Room) -> bool:
    return room.tenant_id == t.id or (room.partner_id is not None and room.partner_id == t.partner_id)


# ---------- diskretion ----------

def privacy_for(db: Session, room: Room, booking: Booking) -> str:
    """Det mest specifikke vinder: lokaleskærmen, så det bookende firma, så huset. Standard er "busy"."""
    if room.privacy in PRIVACY:
        return room.privacy
    t = db.get(Tenant, booking.tenant_id) if booking.tenant_id else None
    if t is not None and t.meeting_privacy in PRIVACY:
        return t.meeting_privacy
    pid = room.partner_id or (t.partner_id if t is not None else None)
    p = db.get(Partner, pid) if pid else None
    if p is not None and p.meeting_privacy in PRIVACY:
        return p.meeting_privacy
    return "busy"


def public_label(db: Session, room: Room, b: Booking) -> dict:
    """Det, en lokaleskærm (eller et andet firma) må se om et møde."""
    level = privacy_for(db, room, b)
    t = db.get(Tenant, b.tenant_id) if b.tenant_id else None
    firm = t.name if t is not None else ""
    if level == "title":
        return {"title": b.title or "Møde", "organizer": b.organizer, "firm": firm}
    if level == "organizer":
        return {"title": "Optaget", "organizer": b.organizer, "firm": firm}
    return {"title": "Optaget", "organizer": "", "firm": ""}


# ---------- bookinger ----------

def parse_slot(start: str, end: str) -> tuple[datetime, datetime]:
    try:
        s, e = from_local(start), from_local(end)
    except ValueError:
        raise HTTPException(422, "Ugyldig dato eller tid")
    if e <= s:
        raise HTTPException(422, "Sluttidspunktet skal være efter starttidspunktet")
    if (e - s) > timedelta(minutes=MAX_MINUTES):
        raise HTTPException(422, "En booking kan højst vare 12 timer")
    if e < utcnow() - timedelta(minutes=5):
        raise HTTPException(422, "Tidspunktet er allerede passeret")
    return s, e


def check_free(db: Session, room: Room, start: datetime, end: datetime, ignore_id: int | None = None) -> None:
    q = select(Booking).where(Booking.room_id == room.id, Booking.status == "confirmed",
                              Booking.start_at < end, Booking.end_at > start)
    if ignore_id:
        q = q.where(Booking.id != ignore_id)
    clash = db.scalar(q)
    if clash is not None:
        raise HTTPException(409, f"{room.name} er optaget {to_local(clash.start_at):%H:%M}–{to_local(clash.end_at):%H:%M}")


def day_bounds(day: str | None) -> tuple[datetime, datetime]:
    """Et lokalt døgn som UTC-interval."""
    d = datetime.fromisoformat(day).date() if day else datetime.now(TZ).date()
    start = datetime(d.year, d.month, d.day, tzinfo=TZ)
    end = start + timedelta(days=1)
    return start.astimezone(timezone.utc).replace(tzinfo=None), end.astimezone(timezone.utc).replace(tzinfo=None)


def bookings_between(db: Session, room_ids: list[int], start: datetime, end: datetime) -> list[Booking]:
    if not room_ids:
        return []
    return list(db.scalars(select(Booking).where(Booking.room_id.in_(room_ids), Booking.status == "confirmed",
                                                 Booking.start_at < end, Booking.end_at > start)
                          .order_by(Booking.start_at)))


# ---------- serializers ----------

def room_out(r: Room, base_url: str = "") -> dict:
    return {"id": r.id, "name": r.name, "location": r.location, "description": r.description,
            "capacity": r.capacity, "photo_url": media_url(r.photo_path), "setups": json.loads(r.setups or "[]"),
            "equipment": json.loads(r.equipment or "[]"), "privacy": r.privacy, "active": r.active,
            "tenant_id": r.tenant_id, "partner_id": r.partner_id,
            "screen_url": f"{base_url.rstrip('/')}/room/{r.screen_token}" if base_url else f"/room/{r.screen_token}"}


def booking_out(db: Session, b: Booking, room: Room, full: bool) -> dict:
    """full=True: den, der kigger, må se alt (eget firma, huset eller leverandøren). Ellers som på lokaleskærmen."""
    base = {"id": b.id, "room_id": b.room_id, "start": local_iso(b.start_at), "end": local_iso(b.end_at),
            "tenant_id": b.tenant_id, "source": b.source}
    if full:
        t = db.get(Tenant, b.tenant_id) if b.tenant_id else None
        return {**base, "title": b.title, "organizer": b.organizer, "firm": t.name if t else "",
                "attendees": b.attendees, "setup": b.setup, "equipment": json.loads(b.equipment or "[]"),
                "note": b.note, "host_id": b.host_id, "full": True}
    return {**base, **public_label(db, room, b), "full": False}


# ---------- lokaleskærmens cache ----------

_screen_cache: dict[str, tuple[float, dict]] = {}
SCREEN_CACHE_SECONDS = 6 * 3600


def clear_cache() -> None:
    _screen_cache.clear()


def screen_state(db_factory, token: str) -> dict:
    """Lokalets bookinger i dag og i morgen, som skærmen må vise dem. Fra hukommelsen, når det er muligt.
    Skærmen regner selv ud, om lokalet er ledigt nu, ud fra tiderne og sit eget ur."""
    hit = _screen_cache.get(token)
    today = datetime.now(TZ).date().isoformat()
    if hit and time.monotonic() - hit[0] < SCREEN_CACHE_SECONDS and hit[1]["day"] == today:
        return hit[1]
    with db_factory() as db:
        room = db.scalar(select(Room).where(Room.screen_token == token))
        if room is None or not room.active:
            raise HTTPException(404, "Lokaleskærmen er ikke sat op")
        start, _ = day_bounds(today)
        owner = db.get(Tenant, room.tenant_id) if room.tenant_id else None
        partner = db.get(Partner, room.partner_id) if room.partner_id else None
        house = select(Tenant).where(Tenant.partner_id == room.partner_id, Tenant.house_screen == true())
        brand = owner or (db.scalar(house) if partner else None)
        data = {"day": today, "room": {"name": room.name, "location": room.location, "capacity": room.capacity,
                                        "photo_url": media_url(room.photo_path)},
                "brand": {"name": (owner.name if owner else partner.name if partner else ""),
                          "color": brand.color if brand else "#12352e",
                          "logo_url": media_url(brand.logo_path) if brand else ""},
                "bookings": [{"start": local_iso(b.start_at), "end": local_iso(b.end_at), **public_label(db, room, b)}
                             for b in bookings_between(db, [room.id], start, start + timedelta(days=2))]}
    _screen_cache[token] = (time.monotonic(), data)
    return data
