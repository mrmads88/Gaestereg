"""Mødelokaler (fase 5a): admin, bookingside via værtens link (/b/<token>) og lokaleskærmen (/room/<token>)."""
import json
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from . import catering, invitations, presence, ratelimit, rooms
from .auth import Principal, current
from .db import SessionLocal, get_db
from .media import delete_media, media_url, save_image
from .models import Booking, Partner, Room, Tenant, new_token, utcnow
from .routes_admin import get_tenant_for
from .schemas import BookingIn, CateringIn, QuickBookIn, RoomIn, RoomUpdate
from .timeutil import TZ, local_iso

STATIC = Path(__file__).parent / "static"
admin = APIRouter(prefix="/api/admin", tags=["lokaler"], dependencies=[Depends(current)])
public = APIRouter(tags=["lokaler"])
pages = APIRouter(include_in_schema=False)


def _base(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _clean(items: list[str]) -> str:
    return json.dumps([" ".join(x.split())[:60] for x in items if x.strip()], ensure_ascii=False)


# ---------- adgang ----------

def _manage_room(db: Session, rid: int, p: Principal) -> Room:
    """Lokaler må rettes af firmaets admins (firmaets lokaler) eller husets admins (husets lokaler)."""
    room = db.get(Room, rid)
    if room is None:
        raise HTTPException(404, "Lokalet findes ikke")
    if room.tenant_id is not None:
        get_tenant_for(db, room.tenant_id, p)
    elif not p.can_manage_partner(room.partner_id):
        raise HTTPException(404, "Lokalet findes ikke")
    return room


def _sees_booking(db: Session, p: Principal, b: Booking, room: Room) -> bool:
    """Fuld visning (titel, deltagere, noter): leverandøren og det firma, der har booket. Husets admins ser husets
    egne bookinger fuldt, men firmaernes møder kun som lokaleskærmen viser dem (diskretion: "fyringsrunde 1")."""
    if p.is_platform:
        return True
    if p.role == "tenant":
        return b.tenant_id is not None and b.tenant_id == p.tenant_id
    if b.tenant_id is None:
        return p.can_manage_partner(room.partner_id)
    t = db.get(Tenant, b.tenant_id)
    return t is not None and p.can_see(t) and rooms.privacy_for(db, room, b) == "title"


def _can_cancel(db: Session, p: Principal, b: Booking, room: Room) -> bool:
    """Det bookende firma, eller den der ejer lokalet (firmaets eller husets admins)."""
    if _sees_booking(db, p, b, room):
        return True
    try:
        _manage_room(db, room.id, p)
        return True
    except HTTPException:
        return False


def _rooms_in_scope(db: Session, p: Principal, tenant_id: int | None, partner_id: int | None) -> list[Room]:
    if tenant_id is not None:
        return rooms.rooms_for_tenant(db, get_tenant_for(db, tenant_id, p), active_only=False)
    if partner_id is not None:
        if db.get(Partner, partner_id) is None or not p.can_manage_partner(partner_id):
            raise HTTPException(404, "Partneren findes ikke")
        firm_ids = select(Tenant.id).where(Tenant.partner_id == partner_id)
        return list(db.scalars(select(Room).where(or_(Room.partner_id == partner_id, Room.tenant_id.in_(firm_ids)))
                               .order_by(Room.sort_order, Room.name)))
    raise HTTPException(422, "Vælg firma eller partner")


# ---------- admin: lokaler ----------

@admin.get("/rooms")
def list_rooms(request: Request, tenant_id: int | None = None, partner_id: int | None = None,
               db: Session = Depends(get_db), p: Principal = Depends(current)):
    out = []
    for r in _rooms_in_scope(db, p, tenant_id, partner_id):
        d = rooms.room_out(r, _base(request))
        d["can_manage"] = (r.tenant_id is not None and p.can_see(db.get(Tenant, r.tenant_id))) or \
            (r.partner_id is not None and p.can_manage_partner(r.partner_id))
        out.append(d)
    return out


@admin.post("/rooms")
def create_room(body: RoomIn, request: Request, db: Session = Depends(get_db), p: Principal = Depends(current)):
    if (body.tenant_id is None) == (body.partner_id is None):
        raise HTTPException(422, "Lokalet skal høre til enten et firma eller huset")
    if body.tenant_id is not None:
        get_tenant_for(db, body.tenant_id, p)
    elif db.get(Partner, body.partner_id) is None or not p.can_manage_partner(body.partner_id):
        raise HTTPException(404, "Partneren findes ikke")
    r = Room(tenant_id=body.tenant_id, partner_id=body.partner_id, name=body.name.strip(), location=body.location.strip(),
             description=body.description.strip(), capacity=body.capacity, setups=_clean(body.setups),
             equipment=_clean(body.equipment), privacy=body.privacy)
    db.add(r)
    db.commit()
    rooms.clear_cache()
    return rooms.room_out(r, _base(request))


@admin.patch("/rooms/{rid}")
def update_room(rid: int, body: RoomUpdate, request: Request, db: Session = Depends(get_db),
                p: Principal = Depends(current)):
    r = _manage_room(db, rid, p)
    for k, v in body.model_dump(exclude_unset=True).items():
        if k in ("setups", "equipment"):
            v = _clean(v or [])
        elif isinstance(v, str):
            v = v.strip()
        setattr(r, k, v)
    db.commit()
    rooms.clear_cache()
    return rooms.room_out(r, _base(request))


@admin.delete("/rooms/{rid}")
def delete_room(rid: int, db: Session = Depends(get_db), p: Principal = Depends(current)):
    r = _manage_room(db, rid, p)
    photo = r.photo_path
    db.delete(r)  # bookinger slettes af databasen
    db.commit()
    delete_media(photo)
    rooms.clear_cache()
    return {"ok": True}


@admin.post("/rooms/{rid}/photo")
async def room_photo(rid: int, request: Request, file: UploadFile = File(...), db: Session = Depends(get_db),
                     p: Principal = Depends(current)):
    r = _manage_room(db, rid, p)
    name = await save_image(file, "background")
    delete_media(r.photo_path)
    r.photo_path = name
    db.commit()
    rooms.clear_cache()
    return rooms.room_out(r, _base(request))


@admin.post("/rooms/{rid}/screen-link")
def new_screen_link(rid: int, request: Request, db: Session = Depends(get_db), p: Principal = Depends(current)):
    r = _manage_room(db, rid, p)
    r.screen_token = new_token()
    db.commit()
    rooms.clear_cache()
    return rooms.room_out(r, _base(request))


# ---------- admin: bookinger ----------

@admin.get("/bookings")
def list_bookings(tenant_id: int | None = None, partner_id: int | None = None, date: str | None = None,
                  db: Session = Depends(get_db), p: Principal = Depends(current)):
    scope = _rooms_in_scope(db, p, tenant_id, partner_id)
    by_id = {r.id: r for r in scope}
    try:
        start, end = rooms.day_bounds(date)
    except ValueError:
        raise HTTPException(422, "Ugyldig dato")
    bs = rooms.bookings_between(db, list(by_id), start, end)
    out = [rooms.booking_out(db, b, by_id[b.room_id], _sees_booking(db, p, b, by_id[b.room_id])) for b in bs]
    food = catering.orders_for_bookings(db, [b["id"] for b in out if b["full"]])
    return [{**b, "catering": food.get(b["id"])} for b in out]


def _notify(bg: BackgroundTasks, request: Request, order, event: str) -> None:
    if order is not None and event:
        bg.add_task(catering.notify_kitchen, order.id, event, _base(request))


def _create_booking(db: Session, t: Tenant, room: Room, body: BookingIn, source: str, host_id: int | None,
                    organizer: str) -> tuple[Booking, object, str]:
    if not room.active or not rooms.can_book(t, room):
        raise HTTPException(404, "Lokalet findes ikke")
    start, end = rooms.parse_slot(body.start, body.end)
    rooms.check_free(db, room, start, end)
    setups = json.loads(room.setups or "[]")
    if body.setup and body.setup not in setups:
        raise HTTPException(422, "Opstillingen findes ikke i dette lokale")
    if room.capacity and body.attendees > room.capacity:
        raise HTTPException(422, f"Der er plads til {room.capacity} i {room.name}")
    b = Booking(room_id=room.id, tenant_id=t.id, host_id=host_id, title=body.title.strip(),
                organizer=(body.organizer.strip() or organizer)[:120], start_at=start, end_at=end,
                attendees=body.attendees, setup=body.setup, note=body.note.strip(), source=source,
                equipment=_clean([x for x in body.equipment if x in json.loads(room.equipment or "[]")]))
    db.add(b)
    db.flush()
    order, event = catering.place(db, b, t, body.catering) if body.catering else (None, "")
    db.commit()
    rooms.clear_cache()
    return b, order, event


def _with_food(db: Session, b: Booking, room: Room) -> dict:
    return {**rooms.booking_out(db, b, room, True), "catering": catering.orders_for_bookings(db, [b.id]).get(b.id)}


@admin.post("/bookings")
def admin_book(body: BookingIn, request: Request, bg: BackgroundTasks, db: Session = Depends(get_db),
               p: Principal = Depends(current)):
    tid = body.tenant_id if body.tenant_id is not None else p.tenant_id
    if tid is None:
        raise HTTPException(422, "Vælg hvilket firma der booker")
    t = get_tenant_for(db, tid, p)
    room = db.get(Room, body.room_id)
    if room is None:
        raise HTTPException(404, "Lokalet findes ikke")
    by = (p.user.name or p.user.email) if p.user else "Leverandør"
    b, order, event = _create_booking(db, t, room, body, "admin", None, by)
    _notify(bg, request, order, event)
    return _with_food(db, b, room)


@admin.put("/bookings/{bid}/catering")
def admin_catering(bid: int, body: CateringIn, request: Request, bg: BackgroundTasks, db: Session = Depends(get_db),
                   p: Principal = Depends(current)):
    b = db.get(Booking, bid)
    room = db.get(Room, b.room_id) if b else None
    if b is None or room is None or b.status != "confirmed" or b.tenant_id is None or not _sees_booking(db, p, b, room):
        raise HTTPException(404, "Bookingen findes ikke")
    return _set_food(db, b, room, body, request, bg)


def _set_food(db: Session, b: Booking, room: Room, body: CateringIn, request: Request, bg: BackgroundTasks) -> dict:
    t = db.get(Tenant, b.tenant_id)
    order, event = catering.place(db, b, t, body)
    db.commit()
    rooms.clear_cache()
    _notify(bg, request, order, event)
    return _with_food(db, b, room)


@admin.delete("/bookings/{bid}")
def admin_cancel(bid: int, request: Request, bg: BackgroundTasks, db: Session = Depends(get_db),
                 p: Principal = Depends(current)):
    b = db.get(Booking, bid)
    room = db.get(Room, b.room_id) if b else None
    if b is None or room is None or not _can_cancel(db, p, b, room):
        raise HTTPException(404, "Bookingen findes ikke")
    _cancel(db, b, request, bg)
    return {"ok": True}


def _cancel(db: Session, b: Booking, request: Request, bg: BackgroundTasks) -> None:
    b.status = "cancelled"
    order = catering.cancel_for_booking(db, b)
    db.commit()
    rooms.clear_cache()
    _notify(bg, request, order, "cancelled")


# ---------- bookingside via værtens personlige link ----------

def _host(db: Session, token: str):
    h = invitations.host_from_token(db, token)
    if h is None:
        raise HTTPException(404, "Linket virker ikke længere. Bed din administrator om et nyt.")
    return h, db.get(Tenant, h.tenant_id)


@pages.get("/b/{token}")
def booking_page(token: str):
    return FileResponse(STATIC / "booking.html", headers={"Cache-Control": "no-cache"})


@public.get("/api/book/{token}")
def book_info(token: str, date: str | None = None, db: Session = Depends(get_db)):
    h, t = _host(db, token)
    rs = rooms.rooms_for_tenant(db, t)
    by_id = {r.id: r for r in rs}
    try:
        start, end = rooms.day_bounds(date)
    except ValueError:
        raise HTTPException(422, "Ugyldig dato")
    bs = rooms.bookings_between(db, list(by_id), start, end)
    food = catering.orders_for_bookings(db, [b.id for b in bs if b.tenant_id == t.id])
    ks = catering.kitchens_for_tenant(db, t)
    items = catering.items_of(db, [k.id for k in ks])
    return {"host": h.name, "firm": t.name, "color": t.color, "logo_url": media_url(t.logo_path),
            "date": date or datetime.now(TZ).date().isoformat(),
            "rooms": [rooms.room_out(r) for r in rs],
            "kitchens": [catering.kitchen_public(k, items) for k in ks if any(i.kitchen_id == k.id for i in items)],
            "bookings": [{**rooms.booking_out(db, b, by_id[b.room_id], b.tenant_id == t.id), "mine": b.host_id == h.id,
                          "catering": food.get(b.id)} for b in bs]}


@public.post("/api/book/{token}")
def book(token: str, body: BookingIn, request: Request, bg: BackgroundTasks, db: Session = Depends(get_db)):
    h, t = _host(db, token)
    ratelimit.check("book:" + str(h.id), 60, 3600)
    ratelimit.hit("book:" + str(h.id))
    room = db.get(Room, body.room_id)
    if room is None:
        raise HTTPException(404, "Lokalet findes ikke")
    b, order, event = _create_booking(db, t, room, body, "link", h.id, h.name)
    _notify(bg, request, order, event)
    return _with_food(db, b, room)


@public.put("/api/book/{token}/{bid}/catering")
def book_catering(token: str, bid: int, body: CateringIn, request: Request, bg: BackgroundTasks,
                  db: Session = Depends(get_db)):
    h, _ = _host(db, token)
    b = db.get(Booking, bid)
    if b is None or b.host_id != h.id or b.status != "confirmed":
        raise HTTPException(404, "Bookingen findes ikke")
    return _set_food(db, b, db.get(Room, b.room_id), body, request, bg)


@public.delete("/api/book/{token}/{bid}")
def book_cancel(token: str, bid: int, request: Request, bg: BackgroundTasks, db: Session = Depends(get_db)):
    h, _ = _host(db, token)
    b = db.get(Booking, bid)
    if b is None or b.host_id != h.id:
        raise HTTPException(404, "Bookingen findes ikke")
    _cancel(db, b, request, bg)
    return {"ok": True}


# ---------- lokaleskærmen ----------

@pages.get("/room/{token}")
def room_page(token: str):
    return FileResponse(STATIC / "room.html", headers={"Cache-Control": "no-cache"})


@public.get("/api/room/{token}/state")
def room_state(token: str):
    """Spørges hvert 30. sekund af skærmen. Svaret kommer fra hukommelsen, så databasen kan sove."""
    presence.mark("room:" + token)
    return rooms.screen_state(SessionLocal, token)


@public.post("/api/room/{token}/book")
def room_quick_book(token: str, body: QuickBookIn, db: Session = Depends(get_db)):
    """"Book nu" på skærmen ved døren: fra nu og 15, 30 eller 60 minutter frem (eller til næste møde)."""
    ratelimit.check("roombook:" + token, 12, 3600)
    room = db.scalar(select(Room).where(Room.screen_token == token))
    if room is None or not room.active:
        raise HTTPException(404, "Lokaleskærmen er ikke sat op")
    now = utcnow().replace(second=0, microsecond=0)
    end = now + timedelta(minutes=body.minutes)
    nxt = db.scalar(select(Booking).where(Booking.room_id == room.id, Booking.status == "confirmed",
                                          Booking.end_at > now, Booking.start_at < end).order_by(Booking.start_at))
    if nxt is not None:
        if nxt.start_at <= now + timedelta(minutes=10):
            raise HTTPException(409, "Lokalet er optaget lige nu")
        end = nxt.start_at
    ratelimit.hit("roombook:" + token)
    b = Booking(room_id=room.id, tenant_id=room.tenant_id, title="Booket på skærmen", organizer="",
                start_at=now, end_at=end, source="screen")
    db.add(b)
    db.commit()
    rooms.clear_cache()
    return {"ok": True, "start": local_iso(now), "end": local_iso(end)}
