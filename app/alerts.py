"""Nødbesked på alle skærme.

En nødbesked gælder et firma (alle firmaets skærme) eller et hus (alle skærme i huset: husets egne og alle firmaernes).
Evakuering og advarsel dækker hele skærmen. Information vises som et bånd øverst.

Skærmene spørger hvert 15. sekund (GET /api/alert/<type>/<token>). Svaret kommer fra hukommelsen:
de aktive beskeder holdes i en liste, der genindlæses ved hver ændring, og skærmens token slås op én gang og caches.
Det forudsætter én worker ligesom presence.py.
"""
import threading
import time
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .models import EmergencyAlert, Room, SignageScreen, Tenant, utcnow
from .timeutil import local_iso

KINDS = {
    "evacuation": ("Evakuering", "Forlad bygningen ad nærmeste nødudgang. Brug ikke elevatoren. Gå til mødestedet, "
                                 "og bliv der, til du får besked."),
    "warning": ("Vigtig besked", ""),
    "info": ("Information", ""),
}
SEVERITY = {"evacuation": 3, "warning": 2, "info": 1}
TOKEN_SECONDS = 3600

_lock = threading.Lock()
_active: list[dict] | None = None  # None = ikke indlæst endnu
_tokens: dict[tuple[str, str], tuple[float, tuple[int | None, int | None] | None]] = {}


def clear_token_cache() -> None:
    _tokens.clear()


def reset() -> None:
    """Til tests: glem alt i hukommelsen."""
    global _active
    with _lock:
        _active = None
        _tokens.clear()


def out(a: EmergencyAlert) -> dict:
    return {"id": a.id, "kind": a.kind, "title": a.title, "message": a.message, "tenant_id": a.tenant_id,
            "partner_id": a.partner_id, "created_by": a.created_by, "started_at": local_iso(a.started_at),
            "ends_at": local_iso(a.ends_at), "ended_at": local_iso(a.ended_at), "ended_by": a.ended_by,
            "_ends": a.ends_at}


def _is_live(a: dict, now: datetime) -> bool:
    return a["ended_at"] is None and (a["_ends"] is None or a["_ends"] > now)


def refresh(db: Session) -> None:
    global _active
    rows = db.scalars(select(EmergencyAlert).where(EmergencyAlert.ended_at.is_(None))).all()
    with _lock:
        _active = [out(a) for a in rows]


def ensure_loaded(db_factory) -> None:
    if _active is None:
        with db_factory() as db:
            refresh(db)


def _scope_of(db: Session, kind: str, token: str) -> tuple[int | None, int | None] | None:
    """(firma-id, hus-id) for en skærm. None, hvis skærmen ikke findes."""
    if kind == "k":
        t = db.scalar(select(Tenant).where(Tenant.kiosk_token == token))
        return (t.id, t.partner_id) if t else None
    if kind == "room":
        r = db.scalar(select(Room).where(Room.screen_token == token))
    elif kind == "s":
        r = db.scalar(select(SignageScreen).where(SignageScreen.token == token))
    else:
        return None
    if r is None:
        return None
    if r.tenant_id is not None:
        t = db.get(Tenant, r.tenant_id)
        return (r.tenant_id, t.partner_id if t else None)
    return (None, r.partner_id)


def matching(tid: int | None, pid: int | None, now: datetime | None = None) -> dict | None:
    """Den vigtigste aktive besked for et firma og dets hus."""
    now = now or utcnow()
    hits = [a for a in (_active or []) if _is_live(a, now) and
            ((tid is not None and a["tenant_id"] == tid) or (pid is not None and a["partner_id"] == pid))]
    if not hits:
        return None
    a = max(hits, key=lambda x: (SEVERITY.get(x["kind"], 0), x["started_at"] or ""))
    return {k: v for k, v in a.items() if k in ("id", "kind", "title", "message", "started_at", "ends_at")}


def for_screen(db_factory, kind: str, token: str) -> dict | None:
    ensure_loaded(db_factory)
    hit = _tokens.get((kind, token))
    if hit is None or time.monotonic() - hit[0] > TOKEN_SECONDS:
        with db_factory() as db:
            scope = _scope_of(db, kind, token)
        _tokens[(kind, token)] = (time.monotonic(), scope)
        hit = _tokens[(kind, token)]
    if hit[1] is None:
        return None
    return matching(*hit[1])


# ---------- start og stop ----------

def start(db: Session, kind: str, title: str, message: str, minutes: int | None, by: str,
          tenant_id: int | None = None, partner_id: int | None = None) -> EmergencyAlert:
    if kind not in KINDS:
        raise HTTPException(422, "Ukendt type")
    now = utcnow()
    # En ny besked afløser den aktive i samme omfang.
    for old in db.scalars(select(EmergencyAlert).where(
            EmergencyAlert.ended_at.is_(None),
            EmergencyAlert.tenant_id == tenant_id if tenant_id is not None else EmergencyAlert.partner_id == partner_id)).all():
        old.ended_at, old.ended_by = now, by
    a = EmergencyAlert(tenant_id=tenant_id, partner_id=partner_id, kind=kind,
                       title=(title or KINDS[kind][0]).strip()[:120], message=(message or KINDS[kind][1]).strip()[:600],
                       created_by=by[:200], started_at=now, ends_at=now + timedelta(minutes=minutes) if minutes else None)
    db.add(a)
    db.commit()
    refresh(db)
    return a


def end(db: Session, a: EmergencyAlert, by: str) -> None:
    if a.ended_at is None:
        a.ended_at, a.ended_by = utcnow(), by[:200]
        db.commit()
    refresh(db)


def end_scope(db: Session, by: str, tenant_id: int | None = None, partner_id: int | None = None) -> int:
    rows = db.scalars(select(EmergencyAlert).where(
        EmergencyAlert.ended_at.is_(None),
        EmergencyAlert.tenant_id == tenant_id if tenant_id is not None else EmergencyAlert.partner_id == partner_id)).all()
    now = utcnow()
    for a in rows:
        a.ended_at, a.ended_by = now, by[:200]
    db.commit()
    refresh(db)
    return len(rows)


def history(db: Session, tenant_id: int | None = None, partner_id: int | None = None) -> list[dict]:
    q = select(EmergencyAlert).where(EmergencyAlert.tenant_id == tenant_id if tenant_id is not None
                                     else EmergencyAlert.partner_id == partner_id)
    now = utcnow()
    rows = []
    for a in db.scalars(q.order_by(EmergencyAlert.started_at.desc()).limit(10)).all():
        d = out(a)
        d["active"] = _is_live(d, now)
        d.pop("_ends")
        rows.append(d)
    return rows


def screen_count(db: Session, tenant_id: int | None = None, partner_id: int | None = None) -> int:
    """Hvor mange skærme beskeden når: gæsteskærme, lokaleskærme og infoskærme."""
    firms = select(Tenant.id).where(Tenant.id == tenant_id) if tenant_id is not None else \
        select(Tenant.id).where(Tenant.partner_id == partner_id)
    kiosks = db.scalar(select(func.count()).select_from(Tenant).where(Tenant.id.in_(firms)))
    room_cond = Room.tenant_id.in_(firms) if tenant_id is not None else or_(Room.tenant_id.in_(firms), Room.partner_id == partner_id)
    sig_cond = SignageScreen.tenant_id.in_(firms) if tenant_id is not None else \
        or_(SignageScreen.tenant_id.in_(firms), SignageScreen.partner_id == partner_id)
    rooms_n = db.scalar(select(func.count()).select_from(Room).where(room_cond))
    sig_n = db.scalar(select(func.count()).select_from(SignageScreen).where(sig_cond))
    return int(kiosks or 0) + int(rooms_n or 0) + int(sig_n or 0)
