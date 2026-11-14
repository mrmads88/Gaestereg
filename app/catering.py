"""Forplejning (fase 5b): køkkener, menuer og bestillinger knyttet til bookinger.

Et køkken hører til et firma eller til huset (partneren), ligesom lokaler. Et firma kan bestille fra sine egne og husets
køkkener. Bestillingen er knyttet til en booking (højst én pr. booking), og navn og pris kopieres ind på linjerne.
Køkkenet ser ikke mødets titel (diskretion), kun lokale, tid, firma, arrangør, antal og varer.
Køkkensiden (/kitchen/<token>) svarer fra hukommelsen, så skærmen i køkkenet ikke holder databasen vågen.
"""
import json
import logging
import time
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import or_, select, true
from sqlalchemy.orm import Session

from . import modules
from .db import SessionLocal
from .media import delete_media, media_url
from .models import (Booking, CateringLine, CateringOrder, Kitchen, MenuItem, Notification, Room, Tenant, utcnow)
from .notify import deliver, valid_email
from .timeutil import TZ, from_local, local_iso, to_local

log = logging.getLogger("gaestereg.catering")
STATUS_DA = {"new": "Ny", "confirmed": "Bekræftet", "delivered": "Leveret", "cancelled": "Annulleret"}


def kr(oere: int) -> str:
    """45000 -> '450,00 kr.'"""
    whole, frac = divmod(int(oere), 100)
    return f"{whole:,}".replace(",", ".") + f",{frac:02d} kr."


# ---------- hvem må bestille hvad ----------

def kitchens_for_tenant(db: Session, t: Tenant, active_only: bool = True) -> list[Kitchen]:
    conds = []
    if modules.tenant_has(t, "catering"):
        conds.append(Kitchen.tenant_id == t.id)
    if t.partner_id is not None and modules.partner_has(t.partner, "catering"):
        conds.append(Kitchen.partner_id == t.partner_id)
    if not conds:
        return []
    q = select(Kitchen).where(or_(*conds))
    if active_only:
        q = q.where(Kitchen.active == true())
    return list(db.scalars(q.order_by(Kitchen.name)))


def can_order(t: Tenant, k: Kitchen) -> bool:
    if k.tenant_id is not None:
        return k.tenant_id == t.id and modules.tenant_has(t, "catering")
    return k.partner_id is not None and k.partner_id == t.partner_id and modules.partner_has(t.partner, "catering")


def items_of(db: Session, kitchen_ids: list[int], active_only: bool = True) -> list[MenuItem]:
    if not kitchen_ids:
        return []
    q = select(MenuItem).where(MenuItem.kitchen_id.in_(kitchen_ids))
    if active_only:
        q = q.where(MenuItem.active == true())
    return list(db.scalars(q.order_by(MenuItem.sort_order, MenuItem.category, MenuItem.name)))


# ---------- serializers ----------

def item_out(i: MenuItem) -> dict:
    return {"id": i.id, "kitchen_id": i.kitchen_id, "name": i.name, "description": i.description,
            "category": i.category, "price": i.price, "price_text": kr(i.price), "unit": i.unit,
            "photo_url": media_url(i.photo_path), "tags": json.loads(i.tags or "[]"), "active": i.active,
            "sort_order": i.sort_order}


def kitchen_public(k: Kitchen, items: list[MenuItem]) -> dict:
    """Det, den der bestiller, ser. Ikke køkkenets mail, telefon eller ordrelink."""
    return {"id": k.id, "name": k.name, "kind": k.kind, "note": k.note, "lead_hours": k.lead_hours,
            "items": [item_out(i) for i in items if i.kitchen_id == k.id]}


def kitchen_admin(k: Kitchen, items: list[MenuItem], base_url: str = "") -> dict:
    return {**kitchen_public(k, items), "email": k.email, "phone": k.phone, "active": k.active,
            "tenant_id": k.tenant_id, "partner_id": k.partner_id,
            "kitchen_url": f"{base_url.rstrip('/')}/kitchen/{k.order_token}"}


def lines_of(db: Session, order_ids: list[int]) -> dict[int, list[CateringLine]]:
    out: dict[int, list[CateringLine]] = {}
    if not order_ids:
        return out
    for ln in db.scalars(select(CateringLine).where(CateringLine.order_id.in_(order_ids)).order_by(CateringLine.id)):
        out.setdefault(ln.order_id, []).append(ln)
    return out


def order_out(o: CateringOrder, lines: list[CateringLine], kitchen: Kitchen | None) -> dict:
    return {"id": o.id, "booking_id": o.booking_id, "kitchen_id": o.kitchen_id,
            "kitchen": kitchen.name if kitchen else "", "deliver_at": local_iso(o.deliver_at),
            "status": o.status, "status_text": STATUS_DA.get(o.status, o.status), "note": o.note,
            "cost_center": o.cost_center, "total": o.total, "total_text": kr(o.total),
            "lines": [{"item_id": ln.menu_item_id, "name": ln.name, "unit": ln.unit, "unit_price": ln.unit_price,
                       "qty": ln.qty, "sum_text": kr(ln.unit_price * ln.qty)} for ln in lines]}


def orders_for_bookings(db: Session, booking_ids: list[int]) -> dict[int, dict]:
    """Aktive bestillinger pr. booking-id, klar til JSON."""
    if not booking_ids:
        return {}
    orders = list(db.scalars(select(CateringOrder).where(CateringOrder.booking_id.in_(booking_ids),
                                                          CateringOrder.status != "cancelled")))
    lines = lines_of(db, [o.id for o in orders])
    kitchens = {k.id: k for k in db.scalars(select(Kitchen).where(Kitchen.id.in_({o.kitchen_id for o in orders})))} \
        if orders else {}
    return {o.booking_id: order_out(o, lines.get(o.id, []), kitchens.get(o.kitchen_id)) for o in orders}


# ---------- bestilling ----------

def _deliver_time(booking: Booking, hhmm: str) -> datetime:
    if not hhmm:
        return booking.start_at
    day = to_local(booking.start_at).date().isoformat()
    try:
        at = from_local(f"{day}T{hhmm}")
    except ValueError:
        raise HTTPException(422, "Ugyldigt tidspunkt for levering")
    if at < booking.start_at - timedelta(hours=1) or at > booking.end_at:
        raise HTTPException(422, "Forplejningen skal leveres mellem en time før mødet og mødets slutning")
    return at


def place(db: Session, booking: Booking, t: Tenant, data) -> tuple[CateringOrder | None, str]:
    """Opret, ret eller annullér bestillingen til en booking. Returnerer (bestilling, hændelse), hvor hændelsen er
    'new', 'changed', 'cancelled' eller '' (ingen ændring). Committer ikke."""
    existing = db.scalar(select(CateringOrder).where(CateringOrder.booking_id == booking.id))
    if existing is not None and existing.status == "cancelled":
        db.query(CateringLine).filter(CateringLine.order_id == existing.id).delete()
        db.delete(existing)
        db.flush()
        existing = None
    if data is None or not data.items:
        if existing is None:
            return None, ""
        _check_lead(db.get(Kitchen, existing.kitchen_id), existing.deliver_at, allow_late=True)
        existing.status = "cancelled"
        existing.updated_at = utcnow()
        return existing, "cancelled"

    k = db.get(Kitchen, data.kitchen_id)
    if k is None or not k.active or not can_order(t, k):
        raise HTTPException(404, "Køkkenet findes ikke")
    at = _deliver_time(booking, data.deliver_at)
    _check_lead(k, at)
    menu = {i.id: i for i in items_of(db, [k.id])}
    qty: dict[int, int] = {}
    for x in data.items:
        if x.item_id not in menu:
            raise HTTPException(422, "En af varerne findes ikke længere på menuen. Opdatér siden")
        qty[x.item_id] = qty.get(x.item_id, 0) + x.qty
    if existing is not None:
        if existing.kitchen_id != k.id:
            raise HTTPException(409, "Annullér den nuværende bestilling, før du bestiller fra et andet køkken")
        db.query(CateringLine).filter(CateringLine.order_id == existing.id).delete()
        o, event = existing, "changed"
        o.status = "new"  # køkkenet skal bekræfte ændringen
    else:
        o = CateringOrder(booking_id=booking.id, kitchen_id=k.id, tenant_id=t.id)
        db.add(o)
        event = "new"
    o.deliver_at, o.note, o.cost_center = at, data.note.strip(), data.cost_center.strip()
    o.updated_at = utcnow()
    db.flush()
    total = 0
    for iid, n in qty.items():
        i = menu[iid]
        db.add(CateringLine(order_id=o.id, menu_item_id=i.id, name=i.name, unit=i.unit, unit_price=i.price, qty=n))
        total += i.price * n
    o.total = total
    return o, event


def _check_lead(k: Kitchen | None, at: datetime, allow_late: bool = False) -> None:
    if k is None or allow_late:
        return
    if at < utcnow() + timedelta(hours=k.lead_hours) - timedelta(minutes=1):
        h = k.lead_hours
        raise HTTPException(422, f"{k.name} skal have bestillingen senest {h} time{'r' if h != 1 else ''} før levering")


def cancel_for_booking(db: Session, booking: Booking) -> CateringOrder | None:
    """Kaldes, når en booking aflyses. Returnerer bestillingen, hvis køkkenet skal have besked."""
    o = db.scalar(select(CateringOrder).where(CateringOrder.booking_id == booking.id,
                                              CateringOrder.status != "cancelled"))
    if o is not None:
        o.status = "cancelled"
        o.updated_at = utcnow()
    return o


# ---------- besked til køkkenet ----------

EVENT_DA = {"new": "Ny bestilling", "changed": "Ændret bestilling", "cancelled": "Annulleret bestilling"}


def kitchen_message(db: Session, o: CateringOrder, event: str, base_url: str) -> tuple[str, str, str]:
    """(emne, tekst, kort SMS). Uden mødets titel."""
    b = db.get(Booking, o.booking_id)
    room = db.get(Room, b.room_id) if b else None
    t = db.get(Tenant, o.tenant_id) if o.tenant_id else None
    k = db.get(Kitchen, o.kitchen_id)
    when = to_local(o.deliver_at)
    place_txt = (room.name + (f" ({room.location})" if room.location else "")) if room else "?"
    head = f"{EVENT_DA[event]}: {when:%d.%m} kl. {when:%H:%M} i {place_txt}"
    lines = [f"{ln.qty} × {ln.name} ({ln.unit})" for ln in db.scalars(
        select(CateringLine).where(CateringLine.order_id == o.id).order_by(CateringLine.id))]
    link = f"{base_url.rstrip('/')}/kitchen/{k.order_token}" if k and base_url else ""
    body = "\n".join(filter(None, [
        head, "",
        f"Firma: {t.name}" if t else "",
        f"Bestilt af: {b.organizer}" if b and b.organizer else "",
        f"Deltagere: {b.attendees}" if b and b.attendees else "",
        "", *lines, "",
        f"Bemærkninger: {o.note}" if o.note else "",
        f"Omkostningssted: {o.cost_center}" if o.cost_center else "",
        f"I alt: {kr(o.total)}" if event != "cancelled" else "",
        "", f"Alle bestillinger: {link}" if link else ""]))
    sms = f"{head}. " + (", ".join(lines[:4]) + ("…" if len(lines) > 4 else "") if event != "cancelled" else "") + \
        (f" {link}" if link else "")
    return f"{head} · {t.name if t else ''}".strip(" ·"), body, sms[:600]


def notify_kitchen(order_id: int, event: str, base_url: str = "") -> None:
    """Køres som baggrundsopgave efter commit. Sender mail og/eller SMS til køkkenet og gemmer forsøget."""
    if not event:
        return
    with SessionLocal() as db:
        o = db.get(CateringOrder, order_id)
        k = db.get(Kitchen, o.kitchen_id) if o else None
        t = db.get(Tenant, o.tenant_id) if o and o.tenant_id else None
        if o is None or k is None or t is None:
            return
        subject, body, sms = kitchen_message(db, o, event, base_url)
        rows = []
        if k.email and valid_email(k.email):
            rows.append(Notification(tenant_id=t.id, channel="email", recipient=k.email, subject=subject, body=body))
        if k.phone:
            rows.append(Notification(tenant_id=t.id, channel="sms", recipient=k.phone, subject=subject, body=sms))
        for n in rows:
            db.add(n)
        db.commit()
        for n in rows:
            deliver(n, t)
            db.commit()


# ---------- køkkenets side ----------

_kitchen_cache: dict[tuple[str, str], tuple[float, dict]] = {}
KITCHEN_CACHE_SECONDS = 6 * 3600


def clear_cache() -> None:
    _kitchen_cache.clear()


def kitchen_by_token(db: Session, token: str) -> Kitchen:
    k = db.scalar(select(Kitchen).where(Kitchen.order_token == token))
    if k is None:
        raise HTTPException(404, "Linket virker ikke længere. Bed om et nyt.")
    if not modules.owner_has(db, k.tenant_id, k.partner_id, "catering"):
        raise HTTPException(404, "Forplejning er ikke slået til. Kontakt jeres leverandør.")
    return k


def kitchen_day(token: str, day: str | None) -> dict:
    """Køkkenets bestillinger for en dag, fra hukommelsen når muligt. Mødetitler er udeladt."""
    from .rooms import day_bounds  # undgå cirkulær import
    d = day or datetime.now(TZ).date().isoformat()
    hit = _kitchen_cache.get((token, d))
    if hit and time.monotonic() - hit[0] < KITCHEN_CACHE_SECONDS:
        return hit[1]
    try:
        start, end = day_bounds(d)
    except ValueError:
        raise HTTPException(422, "Ugyldig dato")
    with SessionLocal() as db:
        k = kitchen_by_token(db, token)
        orders = list(db.scalars(select(CateringOrder).where(
            CateringOrder.kitchen_id == k.id, CateringOrder.deliver_at >= start, CateringOrder.deliver_at < end)
            .order_by(CateringOrder.deliver_at)))
        lines = lines_of(db, [o.id for o in orders])
        bookings = {b.id: b for b in db.scalars(select(Booking).where(
            Booking.id.in_(select(CateringOrder.booking_id).where(
                CateringOrder.kitchen_id == k.id, CateringOrder.deliver_at >= start, CateringOrder.deliver_at < end))))}
        room_ids = {b.room_id for b in bookings.values()}
        rooms = {r.id: r for r in db.scalars(select(Room).where(Room.id.in_(room_ids)))} if room_ids else {}
        tenant_ids = {o.tenant_id for o in orders if o.tenant_id}
        firms = {t.id: t.name for t in db.scalars(select(Tenant).where(Tenant.id.in_(tenant_ids)))} if tenant_ids else {}
        out = []
        for o in orders:
            b = bookings.get(o.booking_id)
            r = rooms.get(b.room_id) if b else None
            out.append({**order_out(o, lines.get(o.id, []), k),
                        "room": r.name if r else "", "location": r.location if r else "",
                        "firm": firms.get(o.tenant_id, ""), "organizer": b.organizer if b else "",
                        "attendees": b.attendees if b else 0,
                        "meeting": f"{to_local(b.start_at):%H:%M}–{to_local(b.end_at):%H:%M}" if b else ""})
        data = {"day": d, "kitchen": {"name": k.name, "kind": k.kind}, "orders": out}
    _kitchen_cache[(token, d)] = (time.monotonic(), data)
    return data


# ---------- oprydning ----------

def delete_kitchens(db: Session, ks: list[Kitchen]) -> None:
    """Slet køkkener med menu og bestillinger. Bookingerne bliver. Committer ikke (billeder slettes med det samme)."""
    files = []
    for k in ks:
        files += [i.photo_path for i in db.scalars(select(MenuItem).where(MenuItem.kitchen_id == k.id)).all()]
        orders = select(CateringOrder.id).where(CateringOrder.kitchen_id == k.id)
        db.query(CateringLine).filter(CateringLine.order_id.in_(orders)).delete(synchronize_session=False)
        db.query(CateringOrder).filter(CateringOrder.kitchen_id == k.id).delete(synchronize_session=False)
        db.delete(k)  # menuen slettes af databasen
    db.flush()
    for f in files:
        delete_media(f)
