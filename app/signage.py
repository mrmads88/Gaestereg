"""Infoskærme (fase 8).

En infoskærm har en playliste af slides i hovedfeltet, faste felter i en sidebar og et nyhedsbånd nederst.
Kunden bygger den selv i admin. Blokkene følger pakken: hele skærmen kræver modulet "signage", og
mødelokale-blokken kræver "rooms".

Skærmens data (state) caches i hukommelsen og tømmes ved alle admin-ændringer, nye bookinger og invitationer,
så skærmens polling ikke vækker databasen. Vejret hentes af skærmen selv fra Open-Meteo (gratis, uden nøgle).
"""
import json
import re
import time
from datetime import datetime, timedelta
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import false, select, true
from sqlalchemy.orm import Session

from . import modules, rooms
from .invitations import qr_svg
from .media import media_url
from .models import Invitation, Partner, Room, SignageScreen, Tenant
from .timeutil import TZ, local_iso

MEDIA_NAME = re.compile(r"^([0-9a-f]{32}\.(png|jpg|svg))?$")
HHMM = r"^(\d{2}:\d{2})?$"
SLIDES = ("welcome", "text", "image", "rooms", "guests", "menu", "qr")
WIDGETS = ("clock", "weather", "rooms", "guests", "wifi", "menu", "qr")
NEEDS = {"rooms": "rooms"}  # blok -> modul ud over "signage"


# ---------- indhold ----------

class Slide(BaseModel):
    type: Literal[SLIDES]  # type: ignore[valid-type]
    duration: int = Field(12, ge=5, le=300)
    title: str = Field("", max_length=120)
    text: str = Field("", max_length=800)
    image: str = Field("", max_length=60)
    url: str = Field("", max_length=300)
    week: list[str] = Field(default_factory=list, max_length=7)  # menu: mandag..søndag
    guest_mode: Literal["company", "first"] = "company"
    days: list[int] = Field(default_factory=list, max_length=7)  # 0 = mandag. Tom = alle dage
    from_time: str = Field("", pattern=HHMM)
    to_time: str = Field("", pattern=HHMM)

    @field_validator("image")
    @classmethod
    def _img(cls, v):
        if not MEDIA_NAME.match(v):
            raise ValueError("Ugyldigt billede")
        return v

    @field_validator("week")
    @classmethod
    def _week(cls, v):
        return [x[:300] for x in v]

    @field_validator("days")
    @classmethod
    def _days(cls, v):
        return sorted({d for d in v if 0 <= d <= 6})

    @field_validator("url")
    @classmethod
    def _url(cls, v):
        if v and not re.match(r"^https?://", v):
            raise ValueError("Linket skal starte med https://")
        return v


class Widget(BaseModel):
    type: Literal[WIDGETS]  # type: ignore[valid-type]
    title: str = Field("", max_length=80)
    place: str = Field("", max_length=80)  # vejr: bynavn
    lat: float | None = Field(None, ge=-90, le=90)
    lon: float | None = Field(None, ge=-180, le=180)
    url: str = Field("", max_length=300)
    guest_mode: Literal["company", "first"] = "company"
    week: list[str] = Field(default_factory=list, max_length=7)

    @field_validator("url")
    @classmethod
    def _url(cls, v):
        if v and not re.match(r"^https?://", v):
            raise ValueError("Linket skal starte med https://")
        return v


class Content(BaseModel):
    slides: list[Slide] = Field(default_factory=list, max_length=40)
    side: list[Widget] = Field(default_factory=list, max_length=8)
    ticker: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("ticker")
    @classmethod
    def _ticker(cls, v):
        return [" ".join(x.split())[:200] for x in v if x.strip()]


def default_content(name: str) -> dict:
    """Et forslag, så en ny skærm ser færdig ud med det samme."""
    return {"slides": [{"type": "welcome", "duration": 15, "title": "Velkommen", "text": f"Godt at se dig hos {name}"},
                       {"type": "guests", "duration": 12, "title": "Vi glæder os til at se"}],
            "side": [{"type": "clock"}, {"type": "weather", "place": "København", "lat": 55.68, "lon": 12.57}],
            "ticker": []}


def load_content(s: SignageScreen) -> dict:
    try:
        return Content.model_validate(json.loads(s.content or "{}")).model_dump()
    except Exception:  # noqa: BLE001 - gammelt eller ødelagt indhold: vis en tom skærm frem for en fejl
        return Content().model_dump()


def images_of(content: dict) -> set[str]:
    return {x["image"] for x in content.get("slides", []) if x.get("image")}


# ---------- adgang og moduler ----------

def owner_has(db: Session, s: SignageScreen, m: str = "signage") -> bool:
    return modules.owner_has(db, s.tenant_id, s.partner_id, m)


def tenant_ids(s: SignageScreen):
    """Firmaerne på skærmen som subquery: firmaet selv eller husets aktive firmaer."""
    if s.tenant_id is not None:
        return select(Tenant.id).where(Tenant.id == s.tenant_id)
    return select(Tenant.id).where(Tenant.partner_id == s.partner_id, Tenant.active == true())


def screen_rooms(db: Session, s: SignageScreen) -> list[Room]:
    """Lokalerne på skærmen: firmaets egne og husets, eller husets for en husskærm. Kun med modulet."""
    if s.tenant_id is not None:
        t = db.get(Tenant, s.tenant_id)
        return rooms.rooms_for_tenant(db, t) if t is not None else []
    p = db.get(Partner, s.partner_id)
    if not modules.partner_has(p, "rooms"):
        return []
    return list(db.scalars(select(Room).where(Room.partner_id == s.partner_id, Room.active == true())
                           .order_by(Room.sort_order, Room.name)))


# ---------- skærmens data ----------

_cache: dict[str, tuple[float, dict]] = {}
CACHE_SECONDS = 6 * 3600


def clear_cache() -> None:
    _cache.clear()


def _guest_label(inv: Invitation, mode: str) -> dict:
    if mode == "first":
        parts = (inv.guest_name or "").split()
        name = (parts[0] + (" " + parts[-1][0] + "." if len(parts) > 1 else "")) if parts else ""
    else:
        name = ""
    return {"time": local_iso(inv.expected_at), "name": name, "company": inv.guest_company}


def state(db_factory, token: str) -> dict:
    """Alt, skærmen viser, fra hukommelsen når muligt. Ingen mail, mobil eller mødetitler (diskretion gælder)."""
    today = datetime.now(TZ).date().isoformat()
    hit = _cache.get(token)
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS and hit[1]["day"] == today:
        return hit[1]
    with db_factory() as db:
        s = db.scalar(select(SignageScreen).where(SignageScreen.token == token))
        if s is None or not s.active or not owner_has(db, s):
            raise HTTPException(404, "Infoskærmen er ikke sat op")
        content = load_content(s)
        owner = db.get(Tenant, s.tenant_id) if s.tenant_id else None
        partner = db.get(Partner, s.partner_id) if s.partner_id else None
        brand_t = owner or (db.scalar(select(Tenant).where(Tenant.partner_id == s.partner_id, Tenant.house_screen == true()))
                            if partner else None)
        uses = {x["type"] for x in content["slides"]} | {x["type"] for x in content["side"]}
        data = {
            "day": today,
            "screen": {"name": s.name, "layout": s.layout, "theme": s.theme},
            "brand": {"name": owner.name if owner else partner.name if partner else "",
                      "color": brand_t.color if brand_t else "#12352e",
                      "logo_url": media_url(brand_t.logo_path) if brand_t else "",
                      "background_url": media_url(brand_t.background_path) if brand_t else ""},
            "content": content,
            "images": {x: media_url(x) for x in images_of(content)},
            "rooms": None, "guests": None, "wifi": None, "qr": {},
        }
        # Mødelokaler kræver modulet. Uden det fjernes blokken fra skærmen.
        if "rooms" in uses:
            rs = screen_rooms(db, s)
            if rs and (s.partner_id is not None or modules.tenant_has(owner, "rooms")):
                start, _ = rooms.day_bounds(today)
                bks = rooms.bookings_between(db, [r.id for r in rs], start, start + timedelta(days=1))
                data["rooms"] = [{"name": r.name, "location": r.location, "capacity": r.capacity,
                                  "bookings": [{"start": local_iso(b.start_at), "end": local_iso(b.end_at),
                                                "title": rooms.public_label(db, r, b)["title"]}
                                               for b in bks if b.room_id == r.id]} for r in rs]
        if "guests" in uses:
            start, end = rooms.day_bounds(today)
            invs = db.scalars(select(Invitation).where(
                Invitation.tenant_id.in_(tenant_ids(s)), Invitation.status != "cancelled",
                Invitation.recurring == false(), Invitation.expected_at >= start, Invitation.expected_at < end)
                .order_by(Invitation.expected_at)).all()
            modes = {x.get("guest_mode", "company") for x in content["slides"] + content["side"] if x["type"] == "guests"}
            mode = "first" if "first" in modes else "company"
            data["guests"] = [_guest_label(i, mode) for i in invs if i.guest_company or mode == "first"][:40]
        if "wifi" in uses and brand_t is not None and brand_t.wifi_name:
            data["wifi"] = {"name": brand_t.wifi_name, "password": brand_t.wifi_password}
        for x in content["slides"] + content["side"]:
            if x["type"] == "qr" and x.get("url"):
                data["qr"][x["url"]] = qr_svg(x["url"], scale=6)
    _cache[token] = (time.monotonic(), data)
    return data


def screen_out(s: SignageScreen, base_url: str = "") -> dict:
    return {"id": s.id, "name": s.name, "token": s.token, "layout": s.layout, "theme": s.theme, "active": s.active,
            "tenant_id": s.tenant_id, "partner_id": s.partner_id, "content": load_content(s),
            "url": f"{base_url.rstrip('/')}/s/{s.token}" if base_url else f"/s/{s.token}",
            "created_at": local_iso(s.created_at)}
