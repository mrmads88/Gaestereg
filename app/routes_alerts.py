"""Nødbesked på alle skærme: admin starter og afslutter, skærmene spørger, og brandvagten kan starte fra
evakueringslisten (/e/<token>) uden login."""
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import alerts, house, ratelimit
from .auth import Principal, current
from .db import SessionLocal, get_db
from .models import EmergencyAlert, Partner, Tenant
from .routes_admin import get_tenant_for

admin = APIRouter(prefix="/api/admin/alerts", tags=["nødbesked"], dependencies=[Depends(current)])
public = APIRouter(tags=["nødbesked"])


class AlertIn(BaseModel):
    tenant_id: int | None = None
    partner_id: int | None = None
    kind: Literal["evacuation", "warning", "info"] = "evacuation"
    title: str = Field("", max_length=120)
    message: str = Field("", max_length=600)
    minutes: int | None = Field(None, ge=1, le=24 * 60)  # tom = indtil den afsluttes
    notify: bool = False  # send også SMS/mail/Teams til personerne (kræver, at det er slået til)


class NotifySettingIn(BaseModel):
    alert_notify: bool


class EvacAlertIn(BaseModel):
    action: Literal["start", "end"]


def _who(p: Principal) -> str:
    return (p.user.name or p.user.email) if p.user else "Leverandør"


def _scope(db: Session, p: Principal, tenant_id: int | None, partner_id: int | None) -> tuple[int | None, int | None]:
    if tenant_id is not None:
        return get_tenant_for(db, tenant_id, p).id, None
    if partner_id is not None:
        if db.get(Partner, partner_id) is None or not p.can_manage_partner(partner_id):
            raise HTTPException(404, "Partneren findes ikke")
        return None, partner_id
    raise HTTPException(422, "Vælg firma eller hus")


@admin.get("")
def list_alerts(tenant_id: int | None = None, partner_id: int | None = None, kind: str = "evacuation",
                db: Session = Depends(get_db), p: Principal = Depends(current)):
    tid, pid = _scope(db, p, tenant_id, partner_id)
    hist = alerts.history(db, tid, pid)
    own = db.get(Tenant, tid) if tid is not None else db.get(Partner, pid)
    return {"active": [h for h in hist if h["active"]], "history": hist, "screens": alerts.screen_count(db, tid, pid),
            "templates": {k: {"title": v[0], "message": v[1]} for k, v in alerts.KINDS.items()},
            "notify": {**alerts.preview(db, tid, pid, kind), "own_setting": bool(own.alert_notify),
                       "can_change": p.role != "tenant"}}


@admin.patch("/settings")
def notify_setting(body: NotifySettingIn, tenant_id: int | None = None, partner_id: int | None = None,
                   db: Session = Depends(get_db), p: Principal = Depends(current)):
    """Slå SMS/mail/Teams ved nødbesked til eller fra. Koster SMS, så kun huset og leverandøren må."""
    tid, pid = _scope(db, p, tenant_id, partner_id)
    if p.role == "tenant":
        raise HTTPException(403, "Kontakt huset eller jeres leverandør for at slå SMS ved nødbesked til")
    own = db.get(Tenant, tid) if tid is not None else db.get(Partner, pid)
    own.alert_notify = body.alert_notify
    db.commit()
    return alerts.preview(db, tid, pid)


@admin.post("")
def start_alert(body: AlertIn, bg: BackgroundTasks, db: Session = Depends(get_db), p: Principal = Depends(current)):
    if (body.tenant_id is None) == (body.partner_id is None):
        raise HTTPException(422, "Vælg firma eller hus")
    tid, pid = _scope(db, p, body.tenant_id, body.partner_id)
    a = alerts.start(db, body.kind, body.title, body.message, body.minutes, _who(p), tenant_id=tid, partner_id=pid,
                     notify=body.notify)
    if a.notify:
        bg.add_task(alerts.notify_people, a.id, "start")
    return {**{k: v for k, v in alerts.out(a).items() if k != "_ends"}, "screens": alerts.screen_count(db, tid, pid)}


@admin.post("/{aid}/end")
def end_alert(aid: int, bg: BackgroundTasks, db: Session = Depends(get_db), p: Principal = Depends(current)):
    a = db.get(EmergencyAlert, aid)
    if a is None:
        raise HTTPException(404, "Beskeden findes ikke")
    _scope(db, p, a.tenant_id, a.partner_id)
    if alerts.end(db, a, _who(p)):
        bg.add_task(alerts.notify_people, a.id, "clear")
    return {"ok": True}


@public.get("/api/alert/{kind}/{token}")
def screen_alert(kind: Literal["k", "room", "s"], token: str):
    """Spørges hvert 15. sekund af alle skærme. Svaret kommer fra hukommelsen."""
    return {"alert": alerts.for_screen(SessionLocal, kind, token)}


@public.post("/api/evac/{token}/alert")
def evac_alert(token: str, body: EvacAlertIn, bg: BackgroundTasks, db: Session = Depends(get_db)):
    """Brandvagten starter eller afslutter evakuering på alle skærme fra evakueringslisten."""
    ratelimit.check("evac-alert:" + token[-16:], 20, 3600)
    ratelimit.hit("evac-alert:" + token[-16:])
    kind, oid, name = house.evac_owner(db, token)
    tid, pid = (oid, None) if kind == "t" else (None, oid)
    if body.action == "start":
        # Brandvagten følger husets/firmaets indstilling for SMS og mail.
        a = alerts.start(db, "evacuation", "", "", None, "Evakueringslisten", tenant_id=tid, partner_id=pid,
                         notify=alerts.notify_allowed(db, tid, pid))
        if a.notify:
            bg.add_task(alerts.notify_people, a.id, "start")
    else:
        for aid in alerts.end_scope(db, "Evakueringslisten", tenant_id=tid, partner_id=pid):
            bg.add_task(alerts.notify_people, aid, "clear")
    return {"active": body.action == "start", "screens": alerts.screen_count(db, tid, pid)}


@public.get("/api/evac/{token}/alert")
def evac_alert_state(token: str, db: Session = Depends(get_db)):
    kind, oid, name = house.evac_owner(db, token)
    tid, pid = (oid, None) if kind == "t" else (None, oid)
    alerts.ensure_loaded(SessionLocal)
    a = alerts.matching(tid, pid)
    return {"active": bool(a and a["kind"] == "evacuation")}
