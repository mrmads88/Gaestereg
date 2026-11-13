"""Admin API: set up customers, their look, people and message rules.

Alle endpoints kender den indloggede (Principal) og tjekker, at vedkommende må se kunden.
En kunde, man ikke må se, giver 404, så man ikke kan gætte sig til, hvilke kunder der findes.
"""
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .auth import Principal, current, require_platform
from .db import get_db
from .media import delete_media, media_url, save_image
from .models import Host, Notification, Partner, Tenant, User, Visit, new_token, utcnow
from .notify import build_messages, deliver
from .schemas import (HostIn, HostUpdate, Reorder, SubscriptionIn, TenantCreate, TenantUpdate, host_admin,
                      tenant_admin, tenant_languages)
from .timeutil import days_ago_utc, local_iso

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(current)])


# ---------- tenants ----------

def get_tenant_for(db: Session, tid: int, p: Principal) -> Tenant:
    t = db.get(Tenant, tid)
    if t is None or not p.can_see(t):
        raise HTTPException(404, "Kunden findes ikke")
    return t


def _out(t: Tenant, p: Principal, with_hosts: bool = True) -> dict:
    return tenant_admin(t, with_hosts=with_hosts, platform=p.is_platform)


def default_sender(name: str) -> str:
    return "".join(c for c in name if c.isalnum() or c == " ")[:11].strip() or "Reception"


@router.get("/tenants")
def list_tenants(db: Session = Depends(get_db), p: Principal = Depends(current)):
    q = select(Tenant).order_by(func.lower(Tenant.name))
    if p.role == "partner":
        q = q.where(Tenant.partner_id == p.partner_id)
    elif p.role == "tenant":
        q = q.where(Tenant.id == p.tenant_id)
    return [_out(t, p, with_hosts=False) for t in db.scalars(q)]


@router.post("/tenants")
def create_tenant(body: TenantCreate, db: Session = Depends(get_db), p: Principal = Depends(current)):
    if p.is_platform:
        partner_id = body.partner_id
        if partner_id is not None and db.get(Partner, partner_id) is None:
            raise HTTPException(404, "Partneren findes ikke")
    elif p.role == "partner":
        partner_id = p.partner_id
    else:
        raise HTTPException(403, "Du kan ikke oprette nye firmaer")
    t = Tenant(name=body.name.strip(), sms_sender=default_sender(body.name), partner_id=partner_id)
    db.add(t)
    db.commit()
    return _out(t, p)


@router.get("/tenants/{tid}")
def get_tenant(tid: int, db: Session = Depends(get_db), p: Principal = Depends(current)):
    return _out(get_tenant_for(db, tid, p), p)


@router.patch("/tenants/{tid}")
def update_tenant(tid: int, body: TenantUpdate, db: Session = Depends(get_db), p: Principal = Depends(current)):
    t = get_tenant_for(db, tid, p)
    data = body.model_dump(exclude_unset=True)
    if "active" in data and p.role == "tenant":
        raise HTTPException(403, "Kontakt din leverandør for at slå skærmen fra eller til")
    if "languages" in data:
        data["languages"] = ",".join(data["languages"])
    for k, v in data.items():
        setattr(t, k, v.strip() if isinstance(v, str) and k not in ("sms_template", "email_template") else v)
    # Standardsproget skal være et af de valgte sprog.
    langs = tenant_languages(t)
    if t.lang_default not in langs:
        if "lang_default" in data:
            raise HTTPException(422, "Standardsproget skal være et af de sprog, der vises på skærmen")
        t.lang_default = langs[0]
    db.commit()
    return _out(t, p)


@router.patch("/tenants/{tid}/subscription")
def update_subscription(tid: int, body: SubscriptionIn, db: Session = Depends(get_db),
                        p: Principal = Depends(require_platform)):
    t = get_tenant_for(db, tid, p)
    data = body.model_dump(exclude_unset=True)
    if data.get("partner_id") is not None and db.get(Partner, data["partner_id"]) is None:
        raise HTTPException(404, "Partneren findes ikke")
    for k, v in data.items():
        setattr(t, k, v.strip() if isinstance(v, str) else v)
    db.commit()
    return _out(t, p)


@router.delete("/tenants/{tid}")
def delete_tenant(tid: int, db: Session = Depends(get_db), p: Principal = Depends(require_platform)):
    t = get_tenant_for(db, tid, p)
    files = [t.logo_path, t.background_path] + [h.photo_path for h in t.hosts]
    db.query(Notification).filter(Notification.tenant_id == tid).delete()
    db.query(Visit).filter(Visit.tenant_id == tid).delete()
    db.query(User).filter(User.tenant_id == tid).delete()
    db.delete(t)
    db.commit()
    for f in files:
        delete_media(f)
    return {"ok": True}


@router.post("/tenants/{tid}/new-link")
def rotate_token(tid: int, db: Session = Depends(get_db), p: Principal = Depends(current)):
    t = get_tenant_for(db, tid, p)
    t.kiosk_token = new_token()
    db.commit()
    return _out(t, p)


@router.post("/tenants/{tid}/image/{kind}")
async def upload_tenant_image(tid: int, kind: Literal["logo", "background"], file: UploadFile = File(...),
                              db: Session = Depends(get_db), p: Principal = Depends(current)):
    t = get_tenant_for(db, tid, p)
    name = await save_image(file, kind)
    attr = "logo_path" if kind == "logo" else "background_path"
    delete_media(getattr(t, attr))
    setattr(t, attr, name)
    db.commit()
    return _out(t, p)


@router.delete("/tenants/{tid}/image/{kind}")
def delete_tenant_image(tid: int, kind: Literal["logo", "background"], db: Session = Depends(get_db),
                        p: Principal = Depends(current)):
    t = get_tenant_for(db, tid, p)
    attr = "logo_path" if kind == "logo" else "background_path"
    delete_media(getattr(t, attr))
    setattr(t, attr, "")
    db.commit()
    return _out(t, p)


# ---------- hosts ----------

def _host(db: Session, hid: int, p: Principal) -> Host:
    h = db.get(Host, hid)
    if h is None or not p.can_see(h.tenant):
        raise HTTPException(404, "Personen findes ikke")
    return h


@router.post("/tenants/{tid}/hosts")
def create_host(tid: int, body: HostIn, db: Session = Depends(get_db), p: Principal = Depends(current)):
    t = get_tenant_for(db, tid, p)
    last = max((h.sort_order for h in t.hosts), default=-1)
    h = Host(tenant_id=t.id, sort_order=last + 1, **{k: (v.strip() if isinstance(v, str) else v)
                                                     for k, v in body.model_dump().items()})
    db.add(h)
    db.commit()
    return host_admin(h)


@router.patch("/hosts/{hid}")
def update_host(hid: int, body: HostUpdate, db: Session = Depends(get_db), p: Principal = Depends(current)):
    h = _host(db, hid, p)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(h, k, v.strip() if isinstance(v, str) else v)
    db.commit()
    return host_admin(h)


@router.delete("/hosts/{hid}")
def delete_host(hid: int, db: Session = Depends(get_db), p: Principal = Depends(current)):
    h = _host(db, hid, p)
    photo = h.photo_path
    # Besøg beholder værtens navn (host_name), men mister koblingen til personen.
    db.execute(update(Visit).where(Visit.host_id == h.id).values(host_id=None))
    db.delete(h)
    db.commit()
    delete_media(photo)
    return {"ok": True}


@router.post("/tenants/{tid}/hosts/order")
def reorder_hosts(tid: int, body: Reorder, db: Session = Depends(get_db), p: Principal = Depends(current)):
    t = get_tenant_for(db, tid, p)
    pos = {hid: i for i, hid in enumerate(body.ids)}
    for h in t.hosts:
        h.sort_order = pos.get(h.id, len(pos) + h.sort_order)
    db.commit()
    db.refresh(t)
    return [host_admin(h) for h in t.hosts]


@router.post("/hosts/{hid}/photo")
async def upload_photo(hid: int, file: UploadFile = File(...), db: Session = Depends(get_db),
                       p: Principal = Depends(current)):
    h = _host(db, hid, p)
    name = await save_image(file, "photo")
    delete_media(h.photo_path)
    h.photo_path = name
    db.commit()
    return host_admin(h)


@router.delete("/hosts/{hid}/photo")
def delete_photo(hid: int, db: Session = Depends(get_db), p: Principal = Depends(current)):
    h = _host(db, hid, p)
    delete_media(h.photo_path)
    h.photo_path = ""
    db.commit()
    return host_admin(h)


@router.post("/hosts/{hid}/test")
def test_notify(hid: int, db: Session = Depends(get_db), p: Principal = Depends(current)):
    """Send the real messages for a made-up guest, so the customer can see exactly what arrives."""
    h = _host(db, hid, p)
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
def visits(tid: int, days: int = 14, db: Session = Depends(get_db), p: Principal = Depends(current)):
    get_tenant_for(db, tid, p)
    rows = db.scalars(select(Visit).where(Visit.tenant_id == tid, Visit.checked_in_at >= days_ago_utc(days))
                      .order_by(Visit.checked_in_at.desc()).limit(500))
    return [{"id": v.id, "guest_name": v.guest_name, "guest_phone": v.guest_phone,
             "guest_company": v.guest_company, "host_name": v.host_name,
             "checked_in_at": local_iso(v.checked_in_at), "checked_out_at": local_iso(v.checked_out_at)}
            for v in rows]


@router.get("/tenants/{tid}/notifications")
def notifications(tid: int, db: Session = Depends(get_db), p: Principal = Depends(current)):
    get_tenant_for(db, tid, p)
    rows = db.scalars(select(Notification).where(Notification.tenant_id == tid)
                      .order_by(Notification.created_at.desc()).limit(200))
    return [{"id": n.id, "channel": n.channel, "recipient": n.recipient, "subject": n.subject, "body": n.body,
             "status": n.status, "error": n.error, "created_at": local_iso(n.created_at)} for n in rows]


__all__ = ["router", "media_url"]
