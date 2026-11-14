"""Forplejning (fase 5b): køkkener og menuer i admin, bestillingsoversigt og køkkenets side (/kitchen/<token>)."""
import csv
import io
import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from . import catering, rooms
from .auth import Principal, current
from .db import get_db
from .media import delete_media, save_image
from .models import Booking, CateringLine, CateringOrder, Kitchen, MenuItem, Partner, Room, Tenant, new_token, utcnow
from .routes_admin import get_tenant_for
from .schemas import KitchenIn, KitchenUpdate, MenuItemIn, MenuItemUpdate, OrderStatusIn
from .timeutil import TZ, to_local

STATIC = Path(__file__).parent / "static"
admin = APIRouter(prefix="/api/admin", tags=["forplejning"], dependencies=[Depends(current)])
public = APIRouter(tags=["forplejning"])
pages = APIRouter(include_in_schema=False)

SAMPLE_MENU = [
    ("Morgenmad", "Morgenbrød med smør og ost", "Rundstykker, smør, ost og marmelade", 45, "pr. person", ["Vegetar"]),
    ("Morgenmad", "Frisk frugt", "Sæsonens frugt i stykker", 25, "pr. person", ["Vegansk", "Glutenfri"]),
    ("Frokost", "Sandwich", "Grovbrød med kylling, pesto og salat", 75, "stk.", []),
    ("Frokost", "Vegetarsandwich", "Grovbrød med hummus, bagte grøntsager og spinat", 75, "stk.", ["Vegetar"]),
    ("Frokost", "Dagens salat", "Stor salat med kerner og dressing", 85, "portion", ["Vegetar", "Glutenfri"]),
    ("Drikkevarer", "Kaffe og te", "Kande med kaffe eller te, mælk og sukker", 60, "kande", ["Vegetar"]),
    ("Drikkevarer", "Danskvand", "Med eller uden smag", 20, "flaske", ["Vegansk"]),
    ("Snacks", "Kage", "Dagens hjemmebagte kage", 35, "pr. person", ["Vegetar"]),
]


def _base(request: Request) -> str:
    return str(request.base_url).rstrip("/")


# ---------- adgang ----------

def _manage_kitchen(db: Session, kid: int, p: Principal) -> Kitchen:
    """Køkkener rettes af firmaets admins (firmaets køkken) eller husets admins (husets køkken)."""
    k = db.get(Kitchen, kid)
    if k is None:
        raise HTTPException(404, "Køkkenet findes ikke")
    if k.tenant_id is not None:
        get_tenant_for(db, k.tenant_id, p)
    elif not p.can_manage_partner(k.partner_id):
        raise HTTPException(404, "Køkkenet findes ikke")
    return k


def _manage_item(db: Session, iid: int, p: Principal) -> MenuItem:
    i = db.get(MenuItem, iid)
    if i is None:
        raise HTTPException(404, "Varen findes ikke")
    _manage_kitchen(db, i.kitchen_id, p)
    return i


def _scope_kitchens(db: Session, p: Principal, tenant_id: int | None, partner_id: int | None) -> list[Kitchen]:
    """Køkkener, man kan se fra et firma (egne og husets) eller fra en partner (husets og firmaernes)."""
    if tenant_id is not None:
        return catering.kitchens_for_tenant(db, get_tenant_for(db, tenant_id, p), active_only=False)
    if partner_id is not None:
        if db.get(Partner, partner_id) is None or not p.can_manage_partner(partner_id):
            raise HTTPException(404, "Partneren findes ikke")
        firm_ids = select(Tenant.id).where(Tenant.partner_id == partner_id)
        return list(db.scalars(select(Kitchen).where(or_(Kitchen.partner_id == partner_id,
                                                          Kitchen.tenant_id.in_(firm_ids))).order_by(Kitchen.name)))
    raise HTTPException(422, "Vælg firma eller partner")


def _can_manage(db: Session, p: Principal, k: Kitchen) -> bool:
    if k.tenant_id is not None:
        t = db.get(Tenant, k.tenant_id)
        return t is not None and p.can_see(t)
    return p.can_manage_partner(k.partner_id)


def _price(kroner: float) -> int:
    return int(round(kroner * 100))


def _changed() -> None:
    rooms.clear_cache()  # tømmer også køkkenets cache


# ---------- køkkener ----------

@admin.get("/kitchens")
def list_kitchens(request: Request, tenant_id: int | None = None, partner_id: int | None = None,
                  db: Session = Depends(get_db), p: Principal = Depends(current)):
    ks = _scope_kitchens(db, p, tenant_id, partner_id)
    items = catering.items_of(db, [k.id for k in ks], active_only=False)
    out = []
    for k in ks:
        manage = _can_manage(db, p, k)
        d = catering.kitchen_admin(k, items, _base(request)) if manage else catering.kitchen_public(k, items)
        out.append({**d, "can_manage": manage, "own": k.tenant_id is not None})
    return out


@admin.post("/kitchens")
def create_kitchen(body: KitchenIn, request: Request, db: Session = Depends(get_db), p: Principal = Depends(current)):
    if (body.tenant_id is None) == (body.partner_id is None):
        raise HTTPException(422, "Køkkenet skal høre til enten et firma eller huset")
    if body.tenant_id is not None:
        get_tenant_for(db, body.tenant_id, p)
    elif db.get(Partner, body.partner_id) is None or not p.can_manage_partner(body.partner_id):
        raise HTTPException(404, "Partneren findes ikke")
    k = Kitchen(tenant_id=body.tenant_id, partner_id=body.partner_id, name=body.name.strip(), kind=body.kind,
                email=body.email.strip(), phone=body.phone.strip(), lead_hours=body.lead_hours, note=body.note.strip())
    db.add(k)
    db.commit()
    _changed()
    return catering.kitchen_admin(k, [], _base(request))


@admin.patch("/kitchens/{kid}")
def update_kitchen(kid: int, body: KitchenUpdate, request: Request, db: Session = Depends(get_db),
                   p: Principal = Depends(current)):
    k = _manage_kitchen(db, kid, p)
    for f, v in body.model_dump(exclude_unset=True).items():
        setattr(k, f, v.strip() if isinstance(v, str) else v)
    db.commit()
    _changed()
    return catering.kitchen_admin(k, catering.items_of(db, [k.id], active_only=False), _base(request))


@admin.delete("/kitchens/{kid}")
def delete_kitchen(kid: int, db: Session = Depends(get_db), p: Principal = Depends(current)):
    k = _manage_kitchen(db, kid, p)
    catering.delete_kitchens(db, [k])
    db.commit()
    _changed()
    return {"ok": True}


@admin.post("/kitchens/{kid}/link")
def new_kitchen_link(kid: int, request: Request, db: Session = Depends(get_db), p: Principal = Depends(current)):
    k = _manage_kitchen(db, kid, p)
    k.order_token = new_token()
    db.commit()
    _changed()
    return catering.kitchen_admin(k, catering.items_of(db, [k.id], active_only=False), _base(request))


@admin.post("/kitchens/{kid}/sample-menu")
def sample_menu(kid: int, request: Request, db: Session = Depends(get_db), p: Principal = Depends(current)):
    """Et eksempel at rette i, så et nyt køkken hurtigt kommer i gang."""
    k = _manage_kitchen(db, kid, p)
    for n, (cat, name, desc, price, unit, tags) in enumerate(SAMPLE_MENU):
        db.add(MenuItem(kitchen_id=k.id, category=cat, name=name, description=desc, price=price * 100, unit=unit,
                        tags=json.dumps(tags, ensure_ascii=False), sort_order=n))
    db.commit()
    _changed()
    return catering.kitchen_admin(k, catering.items_of(db, [k.id], active_only=False), _base(request))


# ---------- menuen ----------

@admin.post("/kitchens/{kid}/items")
def create_item(kid: int, body: MenuItemIn, db: Session = Depends(get_db), p: Principal = Depends(current)):
    k = _manage_kitchen(db, kid, p)
    n = len(catering.items_of(db, [k.id], active_only=False))
    i = MenuItem(kitchen_id=k.id, name=body.name.strip(), description=body.description.strip(),
                 category=body.category.strip(), price=_price(body.price), unit=body.unit,
                 tags=json.dumps(body.tags, ensure_ascii=False), active=body.active, sort_order=n)
    db.add(i)
    db.commit()
    _changed()
    return catering.item_out(i)


@admin.patch("/menu-items/{iid}")
def update_item(iid: int, body: MenuItemUpdate, db: Session = Depends(get_db), p: Principal = Depends(current)):
    i = _manage_item(db, iid, p)
    for f, v in body.model_dump(exclude_unset=True).items():
        if f == "price":
            v = _price(v)
        elif f == "tags":
            v = json.dumps(v or [], ensure_ascii=False)
        elif isinstance(v, str):
            v = v.strip()
        setattr(i, f, v)
    db.commit()
    _changed()
    return catering.item_out(i)


@admin.delete("/menu-items/{iid}")
def delete_item(iid: int, db: Session = Depends(get_db), p: Principal = Depends(current)):
    i = _manage_item(db, iid, p)
    photo = i.photo_path
    db.delete(i)  # bestillinger beholder navn og pris
    db.commit()
    delete_media(photo)
    _changed()
    return {"ok": True}


@admin.post("/menu-items/{iid}/photo")
async def item_photo(iid: int, file: UploadFile = File(...), db: Session = Depends(get_db),
                     p: Principal = Depends(current)):
    i = _manage_item(db, iid, p)
    name = await save_image(file, "background")
    delete_media(i.photo_path)
    i.photo_path = name
    db.commit()
    _changed()
    return catering.item_out(i)


# ---------- bestillinger (overblik og faktureringsgrundlag) ----------

def _orders_in_scope(db: Session, p: Principal, tenant_id: int | None, partner_id: int | None, month: str):
    try:
        first = datetime.strptime(month, "%Y-%m").replace(tzinfo=TZ)
    except ValueError:
        raise HTTPException(422, "Ugyldig måned")
    nxt = first.replace(year=first.year + 1, month=1) if first.month == 12 else first.replace(month=first.month + 1)
    start, end = (rooms.day_bounds(first.date().isoformat())[0], rooms.day_bounds(nxt.date().isoformat())[0])
    if tenant_id is not None:
        t = get_tenant_for(db, tenant_id, p)
        own = select(Kitchen.id).where(Kitchen.tenant_id == t.id)
        cond = or_(CateringOrder.tenant_id == t.id, CateringOrder.kitchen_id.in_(own))
    elif partner_id is not None:
        if db.get(Partner, partner_id) is None or not p.can_manage_partner(partner_id):
            raise HTTPException(404, "Partneren findes ikke")
        firms = select(Tenant.id).where(Tenant.partner_id == partner_id)
        house = select(Kitchen.id).where(or_(Kitchen.partner_id == partner_id, Kitchen.tenant_id.in_(firms)))
        cond = or_(CateringOrder.tenant_id.in_(firms), CateringOrder.kitchen_id.in_(house))
    else:
        raise HTTPException(422, "Vælg firma eller partner")
    return list(db.scalars(select(CateringOrder).where(cond, CateringOrder.deliver_at >= start,
                                                       CateringOrder.deliver_at < end).order_by(CateringOrder.deliver_at)))


def _order_rows(db: Session, orders: list[CateringOrder]) -> list[dict]:
    lines = catering.lines_of(db, [o.id for o in orders])
    ids = {o.kitchen_id for o in orders}
    kitchens = {k.id: k for k in db.scalars(select(Kitchen).where(Kitchen.id.in_(ids)))} if ids else {}
    bids = [o.booking_id for o in orders]
    bookings = {b.id: b for b in db.scalars(select(Booking).where(Booking.id.in_(bids)))} if bids else {}
    rids = {b.room_id for b in bookings.values()}
    room_names = {r.id: r.name for r in db.scalars(select(Room).where(Room.id.in_(rids)))} if rids else {}
    tids = {o.tenant_id for o in orders if o.tenant_id}
    firms = {t.id: t.name for t in db.scalars(select(Tenant).where(Tenant.id.in_(tids)))} if tids else {}
    out = []
    for o in orders:
        b = bookings.get(o.booking_id)
        out.append({**catering.order_out(o, lines.get(o.id, []), kitchens.get(o.kitchen_id)),
                    "firm": firms.get(o.tenant_id, ""), "organizer": b.organizer if b else "",
                    "room": room_names.get(b.room_id, "") if b else "", "attendees": b.attendees if b else 0})
    return out


@admin.get("/catering-orders")
def list_orders(tenant_id: int | None = None, partner_id: int | None = None, month: str | None = None,
                format: str = "json", db: Session = Depends(get_db), p: Principal = Depends(current)):
    month = month or datetime.now(TZ).strftime("%Y-%m")
    rows = _order_rows(db, _orders_in_scope(db, p, tenant_id, partner_id, month))
    if format != "csv":
        live = [r for r in rows if r["status"] != "cancelled"]
        return {"month": month, "orders": rows, "count": len(live), "total": sum(r["total"] for r in live),
                "total_text": catering.kr(sum(r["total"] for r in live))}
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Dato", "Kl.", "Firma", "Bestilt af", "Omkostningssted", "Lokale", "Køkken", "Vare", "Antal", "Enhed",
                "Stykpris", "Beløb", "Status"])
    for r in rows:
        if r["status"] == "cancelled":
            continue
        d = datetime.fromisoformat(r["deliver_at"])
        for ln in r["lines"]:
            w.writerow([d.strftime("%d-%m-%Y"), d.strftime("%H:%M"), r["firm"], r["organizer"], r["cost_center"],
                        r["room"], r["kitchen"], ln["name"], ln["qty"], ln["unit"],
                        f"{ln['unit_price'] / 100:.2f}".replace(".", ","),
                        f"{ln['unit_price'] * ln['qty'] / 100:.2f}".replace(".", ","), r["status_text"]])
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="forplejning-{month}.csv"'})


# ---------- køkkenets side ----------

@pages.get("/kitchen/{token}")
def kitchen_page(token: str):
    return FileResponse(STATIC / "kitchen.html", headers={"Cache-Control": "no-cache"})


@public.get("/api/kitchen/{token}")
def kitchen_orders(token: str, date: str | None = None):
    """Spørges hvert minut af køkkenets skærm. Svaret kommer fra hukommelsen."""
    return catering.kitchen_day(token, date)


@public.post("/api/kitchen/{token}/orders/{oid}")
def kitchen_status(token: str, oid: int, body: OrderStatusIn, db: Session = Depends(get_db)):
    k = catering.kitchen_by_token(db, token)
    o = db.get(CateringOrder, oid)
    if o is None or o.kitchen_id != k.id:
        raise HTTPException(404, "Bestillingen findes ikke")
    if o.status == "cancelled":
        raise HTTPException(409, "Bestillingen er annulleret")
    o.status = body.status
    o.updated_at = utcnow()
    db.commit()
    _changed()
    return {"ok": True, "status": o.status, "status_text": catering.STATUS_DA[o.status],
            "when": to_local(o.updated_at).strftime("%H:%M")}
