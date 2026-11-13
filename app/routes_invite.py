"""Fase 3: forventede gæster.

- Admin: liste, opret, send igen, annullér, værtens invitationslink og QR-plakat til døren.
- Værtens side /i/<token>: værten (uden login) inviterer selv sine gæster.
- Gæstens side /g/<token>: kode og QR-kode til skærmen.
"""
from datetime import timedelta
from html import escape
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import invitations as inv_mod
from . import ratelimit
from .auth import Principal, current
from .db import get_db
from .media import media_url
from .models import Host, Invitation, Tenant, utcnow
from .routes_admin import _host, get_tenant_for
from .schemas import InvitationIn
from .timeutil import from_local, local_day_label, local_hhmm

STATIC = Path(__file__).parent / "static"
admin = APIRouter(prefix="/api/admin", tags=["invitationer"], dependencies=[Depends(current)])
public = APIRouter(tags=["invitationer"])
pages = APIRouter(include_in_schema=False)


def _base(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _expected(value: str):
    try:
        at = from_local(value)
    except ValueError:
        raise HTTPException(422, "Ugyldig dato eller tid")
    now = utcnow()
    if at < now - timedelta(hours=12):
        raise HTTPException(422, "Tidspunktet er allerede passeret")
    if at > now + timedelta(days=366):
        raise HTTPException(422, "Højst et år frem")
    return at


def _create(db: Session, t: Tenant, host: Host | None, body: InvitationIn, by: str, request: Request,
            bg: BackgroundTasks) -> dict:
    if not (body.guest_phone.strip() or body.guest_email.strip()) and body.send:
        raise HTTPException(422, "Skriv gæstens mobil eller e-mail, så de kan få koden")
    data = body.model_dump()
    data["expected_at"] = _expected(body.expected_at)
    inv = inv_mod.create(db, t, host, data, by)
    if body.send:
        bg.add_task(inv_mod.send_to_guest, inv.id, _base(request))
    return inv_mod.out(inv, _base(request))


# ---------- admin ----------

@admin.get("/tenants/{tid}/invitations")
def list_invitations(tid: int, request: Request, all: bool = False, db: Session = Depends(get_db),
                     p: Principal = Depends(current)):
    get_tenant_for(db, tid, p)
    q = select(Invitation).where(Invitation.tenant_id == tid)
    if all:
        q = q.where(Invitation.expected_at >= utcnow() - timedelta(days=30))
    else:
        q = q.where(Invitation.status == "pending", Invitation.expected_at >= utcnow() - timedelta(hours=12))
    return [inv_mod.out(x, _base(request)) for x in db.scalars(q.order_by(Invitation.expected_at).limit(500))]


@admin.post("/tenants/{tid}/invitations")
def create_invitation(tid: int, body: InvitationIn, request: Request, bg: BackgroundTasks,
                      db: Session = Depends(get_db), p: Principal = Depends(current)):
    t = get_tenant_for(db, tid, p)
    host = None
    if body.host_id is not None:
        host = _host(db, body.host_id, p)
        if host.tenant_id != t.id:
            raise HTTPException(404, "Personen findes ikke")
    by = p.user.email if p.user else "Leverandør"
    return _create(db, t, host, body, by, request, bg)


def _inv(db: Session, iid: int, p: Principal) -> Invitation:
    inv = db.get(Invitation, iid)
    if inv is None:
        raise HTTPException(404, "Invitationen findes ikke")
    get_tenant_for(db, inv.tenant_id, p)
    return inv


@admin.post("/invitations/{iid}/send")
def resend(iid: int, request: Request, bg: BackgroundTasks, db: Session = Depends(get_db),
           p: Principal = Depends(current)):
    inv = _inv(db, iid, p)
    if inv.status != "pending":
        raise HTTPException(409, "Invitationen er allerede brugt eller annulleret")
    bg.add_task(inv_mod.send_to_guest, inv.id, _base(request))
    return inv_mod.out(inv, _base(request))


@admin.delete("/invitations/{iid}")
def cancel(iid: int, request: Request, db: Session = Depends(get_db), p: Principal = Depends(current)):
    inv = _inv(db, iid, p)
    if inv.status == "pending":
        inv.status = "cancelled"
        db.commit()
    return inv_mod.out(inv, _base(request))


@admin.get("/hosts/{hid}/invite-link")
def host_link(hid: int, request: Request, db: Session = Depends(get_db), p: Principal = Depends(current)):
    h = _host(db, hid, p)
    return {"url": f"{_base(request)}/i/{inv_mod.host_token(h)}"}


@admin.post("/hosts/{hid}/invite-link")
def new_host_link(hid: int, request: Request, db: Session = Depends(get_db), p: Principal = Depends(current)):
    h = _host(db, hid, p)
    h.link_version += 1
    db.commit()
    return {"url": f"{_base(request)}/i/{inv_mod.host_token(h)}"}


@admin.get("/tenants/{tid}/poster", response_class=HTMLResponse)
def poster(tid: int, request: Request, db: Session = Depends(get_db), p: Principal = Depends(current)):
    """A4-plakat med QR-kode til døren: gæsten scanner og tjekker ind på sin egen telefon."""
    t = get_tenant_for(db, tid, p)
    url = f"{_base(request)}/k/{t.kiosk_token}?m=1"
    logo = media_url(t.logo_path)
    page = (STATIC / "poster.html").read_text(encoding="utf-8")
    return page.replace("{{name}}", escape(t.name)).replace("{{color}}", escape(t.color)).replace(
        "{{logo}}", f'<img src="{escape(logo)}" alt="{escape(t.name)}">' if logo else f"<b>{escape(t.name)}</b>").replace(
        "{{qr}}", inv_mod.qr_svg(url, scale=10)).replace("{{url}}", escape(url))


# ---------- værtens egen side ----------

def _host_or_404(db: Session, token: str) -> Host:
    h = inv_mod.host_from_token(db, token)
    if h is None:
        raise HTTPException(404, "Linket virker ikke længere. Bed din administrator om et nyt.")
    return h


@pages.get("/i/{token}")
def host_page(token: str):
    return FileResponse(STATIC / "invite.html", headers={"Cache-Control": "no-cache"})


@public.get("/api/host/{token}")
def host_info(token: str, request: Request, db: Session = Depends(get_db)):
    h = _host_or_404(db, token)
    t = db.get(Tenant, h.tenant_id)
    upcoming = db.scalars(select(Invitation).where(
        Invitation.host_id == h.id, Invitation.status == "pending",
        Invitation.expected_at >= utcnow() - timedelta(hours=12)).order_by(Invitation.expected_at).limit(50))
    return {"host": h.name, "tenant": t.name, "color": t.color, "logo_url": media_url(t.logo_path),
            "upcoming": [{**inv_mod.out(x, _base(request)), "when": f"{local_day_label(x.expected_at)} kl. "
                          f"{local_hhmm(x.expected_at)}"} for x in upcoming]}


@public.post("/api/host/{token}/invitations")
def host_invite(token: str, body: InvitationIn, request: Request, bg: BackgroundTasks, db: Session = Depends(get_db)):
    h = _host_or_404(db, token)
    ratelimit.check("host-invite:" + str(h.id), 40, 3600)
    ratelimit.hit("host-invite:" + str(h.id))
    t = db.get(Tenant, h.tenant_id)
    body.host_id = h.id
    return _create(db, t, h, body, h.name, request, bg)


@public.delete("/api/host/{token}/invitations/{iid}")
def host_cancel(token: str, iid: int, request: Request, db: Session = Depends(get_db)):
    h = _host_or_404(db, token)
    inv = db.get(Invitation, iid)
    if inv is None or inv.host_id != h.id:
        raise HTTPException(404, "Invitationen findes ikke")
    if inv.status == "pending":
        inv.status = "cancelled"
        db.commit()
    return inv_mod.out(inv, _base(request))


# ---------- gæstens side ----------

@pages.get("/g/{token}")
def guest_page(token: str):
    return FileResponse(STATIC / "guest.html", headers={"Cache-Control": "no-cache"})


@public.get("/api/guest/{token}")
def guest_info(token: str, db: Session = Depends(get_db)):
    inv = inv_mod.invitation_from_guest_token(db, token)
    if inv is None:
        raise HTTPException(404, "Linket virker ikke længere")
    t = db.get(Tenant, inv.tenant_id)
    return {"tenant": t.name, "color": t.color, "logo_url": media_url(t.logo_path),
            "guest": inv.guest_name.split(" ")[0], "host": inv.host_name, "code": inv.code, "status": inv.status,
            "when": f"{local_day_label(inv.expected_at)} kl. {local_hhmm(inv.expected_at)}",
            "qr": inv_mod.qr_svg(inv.code, scale=10)}
