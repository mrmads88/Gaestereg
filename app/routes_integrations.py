"""Admin for integrationer: webhooks (firma, hus eller leverandør) og API-nøgler (firma eller hus). Se integrations.py."""
import hashlib
import json
import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import integrations, modules
from .auth import Principal, current
from .db import get_db
from .models import ApiKey, Integration, IntegrationDelivery, utcnow
from .routes_access import _partner_for
from .routes_admin import get_tenant_for
from .timeutil import local_iso

router = APIRouter(prefix="/api/admin", tags=["integrationer"], dependencies=[Depends(current)])

SCOPES = {"read": "Læse besøg, personer, bookinger og arbejdstid", "people:write": "Opdatere personlisten (fx fra HR)"}


class Owner(BaseModel):
    tenant_id: int | None = None
    partner_id: int | None = None
    platform: bool = False


class WebhookIn(Owner):
    name: str = Field("", max_length=120)
    url: str = Field(max_length=500)
    events: list[str] = Field(min_length=1, max_length=20)


class WebhookPatch(BaseModel):
    name: str | None = Field(None, max_length=120)
    url: str | None = Field(None, max_length=500)
    events: list[str] | None = Field(None, min_length=1, max_length=20)
    enabled: bool | None = None


class KeyIn(Owner):
    name: str = Field(min_length=1, max_length=120)
    scopes: list[str] = Field(default_factory=lambda: ["read"], min_length=1, max_length=5)


def _owner(db: Session, p: Principal, tenant_id: int | None, partner_id: int | None, platform: bool) -> tuple[str, object]:
    """Ejeren af integrationen og adgangstjek. Kunder og huse skal have modulet; leverandøren må altid."""
    if platform:
        if not p.is_platform:
            raise HTTPException(403, "Det kan kun din leverandør gøre")
        return "platform", None
    if (tenant_id is None) == (partner_id is None):
        raise HTTPException(422, "Vælg firma eller hus")
    if tenant_id is not None:
        t = get_tenant_for(db, tenant_id, p)
        if not p.is_platform:
            modules.require_tenant(t, "integrations")
        return "tenant", t
    pa = _partner_for(db, partner_id, p)
    if not p.is_platform:
        modules.require_partner(pa, "integrations")
    return "partner", pa


def _integration(db: Session, iid: int, p: Principal) -> Integration:
    i = db.get(Integration, iid)
    if i is None:
        raise HTTPException(404, "Integrationen findes ikke")
    try:
        _owner(db, p, i.tenant_id, i.partner_id, i.scope == "platform")
    except HTTPException as e:
        raise HTTPException(404, "Integrationen findes ikke") if e.status_code == 403 and i.scope == "platform" else e
    return i


def _events(scope: str, events: list[str]) -> list[str]:
    allowed = {e["key"] for e in integrations.events_for(scope)}
    bad = [e for e in events if e not in allowed]
    if bad:
        raise HTTPException(422, "Ukendt hændelse: " + ", ".join(bad))
    return sorted(set(events))


def _url(url: str) -> str:
    try:
        return integrations.check_url(url)
    except ValueError as e:
        raise HTTPException(422, str(e))


def _key_out(k: ApiKey) -> dict:
    return {"id": k.id, "name": k.name, "prefix": k.prefix, "scopes": json.loads(k.scopes or "[]"),
            "created_by": k.created_by, "created_at": local_iso(k.created_at), "last_used_at": local_iso(k.last_used_at),
            "revoked": k.revoked_at is not None}


@router.get("/integrations")
def list_integrations(tenant_id: int | None = None, partner_id: int | None = None, platform: bool = False,
                      db: Session = Depends(get_db), p: Principal = Depends(current)):
    scope, obj = _owner(db, p, tenant_id, partner_id, platform)
    q = select(Integration).where(Integration.scope == scope)
    if scope == "tenant":
        q = q.where(Integration.tenant_id == obj.id)
    elif scope == "partner":
        q = q.where(Integration.partner_id == obj.id)
    out = {"scope": scope, "events": integrations.events_for(scope),
           "webhooks": [integrations.integration_out(db, i) for i in db.scalars(q.order_by(Integration.id)).all()]}
    if scope != "platform":
        kq = select(ApiKey).where(ApiKey.tenant_id == obj.id) if scope == "tenant" else select(ApiKey).where(ApiKey.partner_id == obj.id)
        out["api_keys"] = [_key_out(k) for k in db.scalars(kq.order_by(ApiKey.id)).all()]
        out["scopes"] = [{"key": k, "label": v} for k, v in SCOPES.items()]
    return out


@router.post("/integrations")
def create_webhook(body: WebhookIn, db: Session = Depends(get_db), p: Principal = Depends(current)):
    scope, obj = _owner(db, p, body.tenant_id, body.partner_id, body.platform)
    secret = integrations.new_secret()
    i = Integration(scope=scope, tenant_id=obj.id if scope == "tenant" else None,
                    partner_id=obj.id if scope == "partner" else None, kind="webhook",
                    name=body.name.strip() or "Webhook", config=json.dumps({"url": _url(body.url)}),
                    secret=integrations.encrypt(secret), events=json.dumps(_events(scope, body.events)))
    db.add(i)
    db.commit()
    return {**integrations.integration_out(db, i), "secret": secret}


@router.patch("/integrations/{iid}")
def update_webhook(iid: int, body: WebhookPatch, db: Session = Depends(get_db), p: Principal = Depends(current)):
    i = _integration(db, iid, p)
    data = body.model_dump(exclude_unset=True)
    if data.get("name") is not None:
        i.name = data["name"].strip() or i.name
    if data.get("url") is not None:
        i.config = json.dumps({**json.loads(i.config or "{}"), "url": _url(data["url"])})
    if data.get("events") is not None:
        i.events = json.dumps(_events(i.scope, data["events"]))
    if data.get("enabled") is not None:
        i.enabled = data["enabled"]
    db.commit()
    return integrations.integration_out(db, i)


@router.post("/integrations/{iid}/secret")
def rotate_secret(iid: int, db: Session = Depends(get_db), p: Principal = Depends(current)):
    i = _integration(db, iid, p)
    secret = integrations.new_secret()
    i.secret = integrations.encrypt(secret)
    db.commit()
    return {"secret": secret}


@router.post("/integrations/{iid}/test")
def test_webhook(iid: int, db: Session = Depends(get_db), p: Principal = Depends(current)):
    """Send en testbesked med det samme og vis svaret."""
    i = _integration(db, iid, p)
    payload = {"event": "ping", "created_at": local_iso(utcnow()), "test": True, "account": {"type": i.scope},
               "data": {"message": "Testbesked fra Nodd. Alt virker."}}
    d = IntegrationDelivery(integration_id=i.id, event="ping", payload=json.dumps(payload, ensure_ascii=False))
    db.add(d)
    db.commit()
    integrations.attempt(d.id)
    db.refresh(d)
    return integrations.delivery_out(d)


@router.post("/deliveries/{did}/retry")
def retry_delivery(did: int, db: Session = Depends(get_db), p: Principal = Depends(current)):
    d = db.get(IntegrationDelivery, did)
    if d is None:
        raise HTTPException(404, "Afsendelsen findes ikke")
    _integration(db, d.integration_id, p)
    if d.status == "ok":
        return integrations.delivery_out(d)
    d.status, d.attempts = "pending", 0
    db.commit()
    integrations.attempt(d.id)
    db.refresh(d)
    return integrations.delivery_out(d)


@router.delete("/integrations/{iid}")
def delete_webhook(iid: int, db: Session = Depends(get_db), p: Principal = Depends(current)):
    db.delete(_integration(db, iid, p))  # afsendelserne følger med (ON DELETE CASCADE)
    db.commit()
    return {"ok": True}


# ---------- API-nøgler ----------

def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


@router.post("/api-keys")
def create_key(body: KeyIn, db: Session = Depends(get_db), p: Principal = Depends(current)):
    scope, obj = _owner(db, p, body.tenant_id, body.partner_id, False)
    bad = [s for s in body.scopes if s not in SCOPES]
    if bad:
        raise HTTPException(422, "Ukendt rettighed: " + ", ".join(bad))
    key = "nodd_" + secrets.token_urlsafe(32)
    k = ApiKey(tenant_id=obj.id if scope == "tenant" else None, partner_id=obj.id if scope == "partner" else None,
               name=body.name.strip(), prefix=key[:12], key_hash=hash_key(key), scopes=json.dumps(sorted(set(body.scopes))),
               created_by=((p.user.name or p.user.email) if p.user else "Leverandøren")[:200])
    db.add(k)
    db.commit()
    return {**_key_out(k), "key": key}


@router.delete("/api-keys/{kid}")
def revoke_key(kid: int, db: Session = Depends(get_db), p: Principal = Depends(current)):
    k = db.get(ApiKey, kid)
    if k is None:
        raise HTTPException(404, "Nøglen findes ikke")
    _owner(db, p, k.tenant_id, k.partner_id, False)
    k.revoked_at = k.revoked_at or utcnow()
    db.commit()
    return _key_out(k)
