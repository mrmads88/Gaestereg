"""Admin API: set up customers, their look, people and message rules."""
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import COOKIE, MAX_AGE, check_password, make_session, require_admin
from .config import settings
from .db import get_db
from .media import delete_media, media_url, save_image
from .models import Host, Notification, Tenant, Visit, new_token, utcnow
from .notify import build_messages, deliver
from .schemas import (HostIn, HostUpdate, LoginIn, Reorder, TenantCreate, TenantUpdate, host_admin,
                      tenant_admin)
from .timeutil import days_ago_utc, local_iso

public = APIRouter(prefix="/api/admin", tags=["admin"])
router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


# ---------- session ----------

@public.post("/login")
def login(body: LoginIn, response: Response):
    if not settings.admin_password_effective:
        raise HTTPException(503, "ADMIN_PASSWORD er ikke sat på serveren")
    if not check_password(body.password):
        raise HTTPException(401, "Forkert adgangskode")
    response.set_cookie(COOKIE, make_session(), max_age=MAX_AGE, httponly=True, samesite="lax",
                        secure=settings.env in ("dev", "prod"))
    return {"ok": True}


@public.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE)
    return {"ok": True}


@router.get("/status")
def status():
    return {
        "env": settings.env,
        "notify_mode": settings.notify_mode,
        "sms_configured": settings.sms_configured,
        "smtp_configured": settings.smtp_configured,
        "default_password": not settings.admin_password,
    }


# ---------- tenants ----------

def _tenant(db: Session, tid: int) -> Tenant:
    t = db.get(Tenant, tid)
    if t is None:
        raise HTTPException(404, "Kunden findes ikke")
    return t


@router.get("/tenants")
def list_tenants(db: Session = Depends(get_db)):
    ts = db.scalars(select(Tenant).order_by(func.lower(Tenant.name)))
    return [tenant_admin(t, with_hosts=False) for t in ts]


@router.post("/tenants")
def create_tenant(body: TenantCreate, db: Session = Depends(get_db)):
    sender = "".join(c for c in body.name if c.isalnum() or c == " ")[:11].strip() or "Reception"
    t = Tenant(name=body.name.strip(), sms_sender=sender)
    db.add(t)
    db.commit()
    return tenant_admin(t)


@router.get("/tenants/{tid}")
def get_tenant(tid: int, db: Session = Depends(get_db)):
    return tenant_admin(_tenant(db, tid))


@router.patch("/tenants/{tid}")
def update_tenant(tid: int, body: TenantUpdate, db: Session = Depends(get_db)):
    t = _tenant(db, tid)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(t, k, v.strip() if isinstance(v, str) and k not in ("sms_template", "email_template") else v)
    db.commit()
    return tenant_admin(t)


@router.delete("/tenants/{tid}")
def delete_tenant(tid: int, db: Session = Depends(get_db)):
    t = _tenant(db, tid)
    files = [t.logo_path, t.background_path] + [h.photo_path for h in t.hosts]
    db.query(Notification).filter(Notification.tenant_id == tid).delete()
    db.query(Visit).filter(Visit.tenant_id == tid).delete()
    db.delete(t)
    db.commit()
    for f in files:
        delete_media(f)
    return {"ok": True}


@router.post("/tenants/{tid}/new-link")
def rotate_token(tid: int, db: Session = Depends(get_db)):
    t = _tenant(db, tid)
    t.kiosk_token = new_token()
    db.commit()
    return tenant_admin(t)


@router.post("/tenants/{tid}/image/{kind}")
async def upload_tenant_image(tid: int, kind: Literal["logo", "background"], file: UploadFile = File(...),
                              db: Session = Depends(get_db)):
    t = _tenant(db, tid)
    name = await save_image(file, kind)
    attr = "logo_path" if kind == "logo" else "background_path"
    delete_media(getattr(t, attr))
    setattr(t, attr, name)
    db.commit()
    return tenant_admin(t)


@router.delete("/tenants/{tid}/image/{kind}")
def delete_tenant_image(tid: int, kind: Literal["logo", "background"], db: Session = Depends(get_db)):
    t = _tenant(db, tid)
    attr = "logo_path" if kind == "logo" else "background_path"
    delete_media(getattr(t, attr))
    setattr(t, attr, "")
    db.commit()
    return tenant_admin(t)


# ---------- hosts ----------

def _host(db: Session, hid: int) -> Host:
    h = db.get(Host, hid)
    if h is None:
        raise HTTPException(404, "Personen findes ikke")
    return h


@router.post("/tenants/{tid}/hosts")
def create_host(tid: int, body: HostIn, db: Session = Depends(get_db)):
    t = _tenant(db, tid)
    last = max((h.sort_order for h in t.hosts), default=-1)
    h = Host(tenant_id=t.id, sort_order=last + 1, **{k: (v.strip() if isinstance(v, str) else v)
                                                     for k, v in body.model_dump().items()})
    db.add(h)
    db.commit()
    return host_admin(h)


@router.patch("/hosts/{hid}")
def update_host(hid: int, body: HostUpdate, db: Session = Depends(get_db)):
    h = _host(db, hid)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(h, k, v.strip() if isinstance(v, str) else v)
    db.commit()
    return host_admin(h)


@router.delete("/hosts/{hid}")
def delete_host(hid: int, db: Session = Depends(get_db)):
    h = _host(db, hid)
    photo = h.photo_path
    db.delete(h)
    db.commit()
    delete_media(photo)
    return {"ok": True}


@router.post("/tenants/{tid}/hosts/order")
def reorder_hosts(tid: int, body: Reorder, db: Session = Depends(get_db)):
    t = _tenant(db, tid)
    pos = {hid: i for i, hid in enumerate(body.ids)}
    for h in t.hosts:
        h.sort_order = pos.get(h.id, len(pos) + h.sort_order)
    db.commit()
    db.refresh(t)
    return [host_admin(h) for h in t.hosts]


@router.post("/hosts/{hid}/photo")
async def upload_photo(hid: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    h = _host(db, hid)
    name = await save_image(file, "photo")
    delete_media(h.photo_path)
    h.photo_path = name
    db.commit()
    return host_admin(h)


@router.delete("/hosts/{hid}/photo")
def delete_photo(hid: int, db: Session = Depends(get_db)):
    h = _host(db, hid)
    delete_media(h.photo_path)
    h.photo_path = ""
    db.commit()
    return host_admin(h)


@router.post("/hosts/{hid}/test")
def test_notify(hid: int, db: Session = Depends(get_db)):
    """Send the real messages for a made-up guest, so the customer can see exactly what arrives."""
    h = _host(db, hid)
    t = h.tenant
    fake = Visit(tenant_id=t.id, host_id=h.id, host_name=h.name, guest_name="Test Testesen",
                 guest_phone="12 34 56 78", guest_company="Testfirma ApS", checked_in_at=utcnow())
    rows = build_messages(fake, t, h)
    if not rows:
        raise HTTPException(422, "Personen har ingen e-mail eller mobil med flueben")
    out = []
    for n in rows:
        n.subject = ("[TEST] " + n.subject) if n.channel == "email" else n.subject
        n.body = ("[TEST] " + n.body) if n.channel == "sms" else n.body
        db.add(n)
        db.commit()
        deliver(n, t)
        db.commit()
        out.append({"channel": n.channel, "recipient": n.recipient, "status": n.status, "error": n.error})
    return out


# ---------- log ----------

@router.get("/tenants/{tid}/visits")
def visits(tid: int, days: int = 14, db: Session = Depends(get_db)):
    _tenant(db, tid)
    rows = db.scalars(select(Visit).where(Visit.tenant_id == tid, Visit.checked_in_at >= days_ago_utc(days))
                      .order_by(Visit.checked_in_at.desc()).limit(500))
    return [{"id": v.id, "guest_name": v.guest_name, "guest_phone": v.guest_phone,
             "guest_company": v.guest_company, "host_name": v.host_name,
             "checked_in_at": local_iso(v.checked_in_at), "checked_out_at": local_iso(v.checked_out_at)}
            for v in rows]


@router.get("/tenants/{tid}/notifications")
def notifications(tid: int, db: Session = Depends(get_db)):
    _tenant(db, tid)
    rows = db.scalars(select(Notification).where(Notification.tenant_id == tid)
                      .order_by(Notification.created_at.desc()).limit(200))
    return [{"id": n.id, "channel": n.channel, "recipient": n.recipient, "subject": n.subject, "body": n.body,
             "status": n.status, "error": n.error, "created_at": local_iso(n.created_at)} for n in rows]


__all__ = ["public", "router", "media_url"]
