"""Integrationer: signerede webhooks til andre systemer (ServiceNow, Salesforce, Zapier, Make, Power Automate ...).

En hændelse (fx "visit.checked_in") sendes til de webhooks, der har bedt om den, og som hører til firmaet, firmaets hus
eller (for leverandørens egne hændelser som "invoice.finalized") platformen. Hver afsendelse gemmes i
integration_deliveries og forsøges straks i en tråd. Fejler den, prøves igen efter 1, 5, 30 minutter, 2 og 12 timer
(tråd-timere, så intet poller databasen). Ved opstart genoptages de, der ventede.

Beskederne er JSON med headerne X-Nodd-Event, X-Nodd-Delivery, X-Nodd-Timestamp og
X-Nodd-Signature: sha256=HMAC_SHA256(hemmelighed, "<timestamp>.<body>"). Hemmeligheden gemmes krypteret (Fernet med en
nøgle afledt af SECRET_KEY), så den kan bruges til at signere. Skifter SECRET_KEY, skal hemmelighederne laves om.

Adresser skal være https og pege på en offentlig adresse (ingen interne IP'er), så en kunde ikke kan få serveren til at
kalde interne tjenester.
"""
import base64
import hashlib
import hmac
import ipaddress
import json
import logging
import secrets
import socket
import threading
import time
from datetime import datetime, timedelta
from urllib.parse import urlparse

import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete, or_, select, true
from sqlalchemy.orm import Session

from .config import settings
from .models import Integration, IntegrationDelivery, Partner, Tenant, utcnow
from .timeutil import local_iso

log = logging.getLogger("gaestereg.integrations")

# Hændelserne, man kan abonnere på. scope: hvor de kan bruges.
EVENTS = {
    "visit.checked_in": ("Gæst tjekket ind", ("tenant", "partner")),
    "visit.checked_out": ("Gæst tjekket ud", ("tenant", "partner")),
    "delivery.received": ("Pakke modtaget", ("tenant", "partner")),
    "booking.created": ("Booking oprettet", ("tenant", "partner")),
    "booking.cancelled": ("Booking aflyst", ("tenant", "partner")),
    "time.week_approved": ("Uge godkendt (tidsregistrering)", ("tenant", "partner")),
    "alert.started": ("Nødbesked startet", ("tenant", "partner")),
    "alert.ended": ("Nødbesked afsluttet", ("tenant", "partner")),
    "invoice.finalized": ("Faktura godkendt", ("platform",)),
}
RETRY_SECONDS = [60, 300, 1800, 7200, 43200]
KEEP_DAYS = 30
TIMEOUT = 10

# Tests kører afsendelsen med det samme (ingen tråde) og med en falsk HTTP-klient.
run_inline = False
client_factory = lambda: httpx.Client(timeout=TIMEOUT, follow_redirects=False)  # noqa: E731
schedule_retry = lambda delay, fn: threading.Timer(delay, fn).start()  # noqa: E731


# ---------- hemmeligheder ----------

def _fernet() -> Fernet:
    key = hashlib.sha256(("nodd-integrations:" + settings.secret_key).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode() if value else ""


def decrypt(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode()).decode() if value else ""
    except InvalidToken:
        return ""


def new_secret() -> str:
    return "whsec_" + secrets.token_urlsafe(24)


def sign(secret: str, timestamp: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()


# ---------- adresser ----------

def resolve(host: str) -> list[str]:
    return [a[4][0] for a in socket.getaddrinfo(host, None)]


def check_url(url: str) -> str:
    """Gyldig, offentlig https-adresse, ellers ValueError med en dansk forklaring."""
    url = (url or "").strip()
    u = urlparse(url)
    local = settings.env == "local"
    if u.scheme not in (("https", "http") if local else ("https",)) or not u.hostname:
        raise ValueError("Adressen skal starte med https://")
    if len(url) > 500:
        raise ValueError("Adressen er for lang")
    if u.username or u.password:
        raise ValueError("Skriv ikke brugernavn og adgangskode i adressen")
    if not local:
        try:
            ips = resolve(u.hostname)
        except OSError:
            raise ValueError("Adressen findes ikke (navnet kan ikke slås op)")
        for ip in ips:
            if not ipaddress.ip_address(ip.split("%")[0]).is_global:
                raise ValueError("Adressen peger på et internt netværk og kan ikke bruges")
    return url


# ---------- hvem skal have hvad ----------

def _targets(db: Session, event: str, tenant: Tenant | None, partner: Partner | None, platform: bool) -> list[Integration]:
    conds = []
    if tenant is not None:
        conds.append((Integration.scope == "tenant") & (Integration.tenant_id == tenant.id))
        if tenant.partner_id:
            conds.append((Integration.scope == "partner") & (Integration.partner_id == tenant.partner_id))
    if partner is not None:
        conds.append((Integration.scope == "partner") & (Integration.partner_id == partner.id))
    if platform:
        conds.append(Integration.scope == "platform")
    if not conds:
        return []
    rows = db.scalars(select(Integration).where(Integration.enabled == true(), or_(*conds))).all()
    return [i for i in rows if event in json.loads(i.events or "[]")]


def account_of(tenant: Tenant | None, partner: Partner | None) -> dict:
    if tenant is not None:
        return {"type": "company", "id": tenant.id, "name": tenant.name,
                "building": {"id": tenant.partner_id, "name": tenant.partner.name} if tenant.partner_id and tenant.partner else None}
    if partner is not None:
        return {"type": "building", "id": partner.id, "name": partner.name}
    return {"type": "provider"}


def emit(db: Session, event: str, data: dict, tenant: Tenant | None = None, partner: Partner | None = None,
         platform: bool = False) -> int:
    """Send en hændelse til dem, der har bedt om den. Kaldes efter commit. Fejl her må aldrig stoppe det, der skete."""
    try:
        targets = _targets(db, event, tenant, partner, platform)
        if not targets:
            return 0
        payload = {"event": event, "created_at": local_iso(utcnow()), "account": account_of(tenant, partner), "data": data}
        rows = [IntegrationDelivery(integration_id=i.id, event=event, payload=json.dumps(payload, ensure_ascii=False))
                for i in targets]
        db.add_all(rows)
        db.commit()
        for r in rows:
            _start(r.id)
        return len(rows)
    except Exception:  # noqa: BLE001
        log.exception("Kunne ikke sende hændelsen %s", event)
        db.rollback()
        return 0


def _start(delivery_id: int) -> None:
    if run_inline:
        attempt(delivery_id)
    else:
        threading.Thread(target=attempt, args=(delivery_id,), daemon=True, name="webhook").start()


# ---------- afsendelse ----------

def _post(integ: Integration, d: IntegrationDelivery) -> tuple[int | None, str]:
    cfg = json.loads(integ.config or "{}")
    url = check_url(cfg.get("url", ""))
    body_obj = json.loads(d.payload)
    body_obj["id"] = d.id
    body = json.dumps(body_obj, ensure_ascii=False).encode()
    ts = str(int(time.time()))
    headers = {"Content-Type": "application/json; charset=utf-8", "User-Agent": "Nodd-Webhooks/1",
               "X-Nodd-Event": d.event, "X-Nodd-Delivery": str(d.id), "X-Nodd-Timestamp": ts,
               "X-Nodd-Signature": sign(decrypt(integ.secret), ts, body)}
    with client_factory() as c:
        r = c.post(url, content=body, headers=headers)
    return r.status_code, ("" if r.status_code < 300 else f"Svar {r.status_code}: {r.text[:200]}")


def attempt(delivery_id: int) -> str:
    """Forsøg én afsendelse. Returnerer den nye status."""
    from .db import SessionLocal
    with SessionLocal() as db:
        d = db.get(IntegrationDelivery, delivery_id)
        if d is None or d.status in ("ok", "dead"):
            return d.status if d else "gone"
        integ = db.get(Integration, d.integration_id)
        d.attempts += 1
        now = utcnow()
        if integ is None or not integ.enabled:
            d.status, d.error, d.done_at = "dead", "Integrationen er slået fra", now
            db.commit()
            return d.status
        try:
            code, err = _post(integ, d)
        except ValueError as e:
            code, err = None, str(e)
        except Exception as e:  # noqa: BLE001 - netværksfejl
            code, err = None, f"{type(e).__name__}: {e}"[:300]
        d.response_code = code
        if not err:
            d.status, d.error, d.done_at, d.next_at = "ok", "", now, None
            integ.last_ok_at = now
        else:
            integ.last_error, integ.last_error_at = err[:500], now
            d.error = err[:500]
            if d.attempts > len(RETRY_SECONDS):
                d.status, d.done_at, d.next_at = "dead", now, None
            else:
                delay = RETRY_SECONDS[d.attempts - 1]
                d.status, d.next_at = "failed", now + timedelta(seconds=delay)
                schedule_retry(delay, lambda: attempt(delivery_id))
        db.commit()
        return d.status


def resume(db: Session) -> int:
    """Ved opstart: start timere for afsendelser, der ventede på et nyt forsøg, og slet gamle."""
    db.execute(delete(IntegrationDelivery).where(IntegrationDelivery.created_at < utcnow() - timedelta(days=KEEP_DAYS)))
    db.commit()
    rows = db.scalars(select(IntegrationDelivery).where(IntegrationDelivery.status.in_(("pending", "failed")))).all()
    for d in rows:
        delay = max(5, (d.next_at - utcnow()).total_seconds()) if d.next_at else 5
        schedule_retry(delay, lambda i=d.id: attempt(i))
    return len(rows)


# ---------- ud ----------

def events_for(scope: str) -> list[dict]:
    return [{"key": k, "label": label} for k, (label, scopes) in EVENTS.items() if scope in scopes]


def delivery_out(d: IntegrationDelivery) -> dict:
    return {"id": d.id, "event": d.event, "status": d.status, "attempts": d.attempts, "response_code": d.response_code,
            "error": d.error, "created_at": local_iso(d.created_at), "next_at": local_iso(d.next_at),
            "done_at": local_iso(d.done_at)}


def integration_out(db: Session, i: Integration) -> dict:
    recent = db.scalars(select(IntegrationDelivery).where(IntegrationDelivery.integration_id == i.id)
                        .order_by(IntegrationDelivery.id.desc()).limit(20)).all()
    cfg = json.loads(i.config or "{}")
    return {"id": i.id, "kind": i.kind, "name": i.name, "url": cfg.get("url", ""), "events": json.loads(i.events or "[]"),
            "enabled": i.enabled, "last_ok_at": local_iso(i.last_ok_at), "last_error": i.last_error,
            "last_error_at": local_iso(i.last_error_at), "created_at": local_iso(i.created_at),
            "deliveries": [delivery_out(d) for d in recent]}


def remove_for(db: Session, tenant_id: int | None = None, partner_id: int | None = None) -> None:
    """Kaldes, når et firma eller hus slettes (ingen FK)."""
    from .models import ApiKey
    q = select(Integration.id).where(Integration.tenant_id == tenant_id) if tenant_id is not None else \
        select(Integration.id).where(Integration.partner_id == partner_id)
    db.execute(delete(IntegrationDelivery).where(IntegrationDelivery.integration_id.in_(q)))
    if tenant_id is not None:
        db.execute(delete(Integration).where(Integration.tenant_id == tenant_id))
        db.execute(delete(ApiKey).where(ApiKey.tenant_id == tenant_id))
    else:
        db.execute(delete(Integration).where(Integration.partner_id == partner_id))
        db.execute(delete(ApiKey).where(ApiKey.partner_id == partner_id))


# ---------- data i hændelserne ----------

def visit_data(v) -> dict:
    return {"visit": {"id": v.id, "kind": v.kind, "guest_name": v.guest_name, "guest_company": v.guest_company,
                      "host": {"id": v.host_id, "name": v.host_name}, "group": v.group_ref or None,
                      "checked_in_at": local_iso(v.checked_in_at), "checked_out_at": local_iso(v.checked_out_at)}}


def booking_data(b, room) -> dict:
    return {"booking": {"id": b.id, "title": b.title, "organizer": b.organizer, "attendees": b.attendees,
                        "start": local_iso(b.start_at), "end": local_iso(b.end_at), "status": b.status, "source": b.source,
                        "room": {"id": room.id, "name": room.name, "location": room.location}}}


def alert_data(a) -> dict:
    return {"alert": {"id": a.id, "kind": a.kind, "title": a.title, "message": a.message, "started_at": local_iso(a.started_at),
                      "ended_at": local_iso(a.ended_at), "by": a.ended_by if a.ended_at else a.created_by}}


def emit_alert(db: Session, event: str, a) -> None:
    t = db.get(Tenant, a.tenant_id) if a.tenant_id else None
    p = db.get(Partner, a.partner_id) if a.partner_id else None
    emit(db, event, alert_data(a), tenant=t, partner=p)
