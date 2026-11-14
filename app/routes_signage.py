"""Infoskærme (fase 8): admin (byg skærmen) og selve skærmen (/s/<token>)."""
import json
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from . import modules, presence, signage
from .auth import Principal, current
from .db import SessionLocal, get_db
from .media import delete_media, media_url, save_image
from .models import Partner, SignageScreen, Tenant, new_token
from .routes_admin import get_tenant_for

STATIC = Path(__file__).parent / "static"
admin = APIRouter(prefix="/api/admin/signage", tags=["infoskærme"], dependencies=[Depends(current)])
public = APIRouter(tags=["infoskærme"])
pages = APIRouter(include_in_schema=False)


class ScreenIn(BaseModel):
    tenant_id: int | None = None
    partner_id: int | None = None
    name: str = Field(min_length=1, max_length=120)


class ScreenUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    layout: str | None = Field(None, pattern="^(sidebar|full)$")
    theme: str | None = Field(None, pattern="^(brand|light|dark)$")
    active: bool | None = None
    content: signage.Content | None = None


def _base(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _owner(db: Session, p: Principal, tenant_id: int | None, partner_id: int | None):
    if tenant_id is not None:
        return get_tenant_for(db, tenant_id, p), None
    if partner_id is not None:
        pa = db.get(Partner, partner_id)
        if pa is None or not p.can_manage_partner(partner_id):
            raise HTTPException(404, "Partneren findes ikke")
        return None, pa
    raise HTTPException(422, "Vælg firma eller hus")


def _manage(db: Session, sid: int, p: Principal) -> SignageScreen:
    s = db.get(SignageScreen, sid)
    if s is None:
        raise HTTPException(404, "Infoskærmen findes ikke")
    if s.tenant_id is not None:
        get_tenant_for(db, s.tenant_id, p)
    elif not p.can_manage_partner(s.partner_id):
        raise HTTPException(404, "Infoskærmen findes ikke")
    return s


def _out(s: SignageScreen, request: Request) -> dict:
    d = signage.screen_out(s, _base(request))
    st = presence.status("signage:" + s.token)
    d["online"] = st["online"]
    d["images"] = {x: media_url(x) for x in signage.images_of(d["content"])}
    return d


@admin.get("")
def list_screens(request: Request, tenant_id: int | None = None, partner_id: int | None = None,
                 db: Session = Depends(get_db), p: Principal = Depends(current)):
    t, pa = _owner(db, p, tenant_id, partner_id)
    if t is not None:
        q = select(SignageScreen).where(SignageScreen.tenant_id == t.id)
        mods = modules.of_tenant(t)
    else:
        firms = select(Tenant.id).where(Tenant.partner_id == pa.id)
        q = select(SignageScreen).where(or_(SignageScreen.partner_id == pa.id, SignageScreen.tenant_id.in_(firms)))
        mods = modules.of_partner(pa)
    screens = db.scalars(q.order_by(SignageScreen.name)).all()
    return {"screens": [_out(s, request) for s in screens],
            "modules": {m: v["on"] for m, v in mods.items()}}


@admin.post("")
def create_screen(body: ScreenIn, request: Request, db: Session = Depends(get_db), p: Principal = Depends(current)):
    if (body.tenant_id is None) == (body.partner_id is None):
        raise HTTPException(422, "Skærmen skal høre til enten et firma eller huset")
    t, pa = _owner(db, p, body.tenant_id, body.partner_id)
    if t is not None:
        modules.require_tenant(t, "signage")
    else:
        modules.require_partner(pa, "signage")
    s = SignageScreen(tenant_id=body.tenant_id, partner_id=body.partner_id, name=body.name.strip(),
                      content=json.dumps(signage.default_content((t or pa).name), ensure_ascii=False))
    db.add(s)
    db.commit()
    signage.clear_cache()
    return _out(s, request)


@admin.patch("/{sid}")
def update_screen(sid: int, body: ScreenUpdate, request: Request, db: Session = Depends(get_db),
                  p: Principal = Depends(current)):
    s = _manage(db, sid, p)
    data = body.model_dump(exclude_unset=True)
    removed: set[str] = set()
    if "content" in data and data["content"] is not None:
        new = signage.Content.model_validate(data.pop("content")).model_dump()
        rooms_used = any(x["type"] == "rooms" for x in new["slides"] + new["side"])
        if rooms_used and not signage.owner_has(db, s, "rooms"):
            raise HTTPException(403, "Mødelokaler er ikke med i pakken. Fjern lokale-blokken eller kontakt leverandøren")
        removed = signage.images_of(signage.load_content(s)) - signage.images_of(new)
        s.content = json.dumps(new, ensure_ascii=False)
    for k, v in data.items():
        if v is not None:
            setattr(s, k, v.strip() if isinstance(v, str) else v)
    db.commit()
    for f in removed:
        delete_media(f)
    signage.clear_cache()
    return _out(s, request)


@admin.delete("/{sid}")
def delete_screen(sid: int, db: Session = Depends(get_db), p: Principal = Depends(current)):
    s = _manage(db, sid, p)
    files = signage.images_of(signage.load_content(s))
    db.delete(s)
    db.commit()
    for f in files:
        delete_media(f)
    signage.clear_cache()
    return {"ok": True}


@admin.post("/{sid}/image")
async def upload_image(sid: int, file: UploadFile = File(...), db: Session = Depends(get_db),
                       p: Principal = Depends(current)):
    """Billede til en slide. Det bliver en del af skærmen, når indholdet gemmes."""
    _manage(db, sid, p)
    name = await save_image(file, "background")
    return {"image": name, "url": media_url(name)}


@admin.post("/{sid}/link")
def new_link(sid: int, request: Request, db: Session = Depends(get_db), p: Principal = Depends(current)):
    s = _manage(db, sid, p)
    s.token = new_token()
    db.commit()
    signage.clear_cache()
    return _out(s, request)


# ---------- selve skærmen ----------

@pages.get("/s/{token}")
def screen_page(token: str):
    return FileResponse(STATIC / "signage.html", headers={"Cache-Control": "no-cache"})


@public.get("/api/signage/{token}/state")
def screen_state(token: str, preview: int = 0):
    """Spørges hvert minut af skærmen. Svaret kommer fra hukommelsen, så databasen kan sove."""
    if not preview:
        presence.mark("signage:" + token)
    return signage.state(SessionLocal, token)
