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
from sqlalchemy import func, or_, select, true
from sqlalchemy.orm import Session

from .models import EmergencyAlert, Host, Notification, Partner, Product, Room, SignageScreen, Tenant, utcnow
from .notify import deliver, normalize_msisdn, valid_email
from .timeutil import local_iso, to_local

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
            "notify": bool(a.notify), "notified_count": max(0, a.notified_count or 0), "cleared_count": max(0, a.cleared_count or 0),
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
          tenant_id: int | None = None, partner_id: int | None = None, notify: bool = False) -> EmergencyAlert:
    """Start en nødbesked. notify: send også SMS/mail/Teams til personerne (kun evakuering og vigtig besked, og kun
    når det er slået til for firmaet eller huset). Selve afsendelsen sker i notify_people (baggrundsopgave)."""
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
                       created_by=by[:200], started_at=now, ends_at=now + timedelta(minutes=minutes) if minutes else None,
                       notify=bool(notify and kind != "info" and notify_allowed(db, tenant_id, partner_id)))
    db.add(a)
    db.commit()
    refresh(db)
    return a


def end(db: Session, a: EmergencyAlert, by: str) -> bool:
    """Afslut. Returnerer True, hvis personerne skal have besked om, at det er afblæst."""
    if a.ended_at is None:
        a.ended_at, a.ended_by = utcnow(), by[:200]
        db.commit()
    refresh(db)
    return bool(a.notify and a.notified_count and not a.cleared_count)


def end_scope(db: Session, by: str, tenant_id: int | None = None, partner_id: int | None = None) -> list[int]:
    """Afslut alle aktive i omfanget. Returnerer id'er på dem, hvor personerne skal have besked om afblæsning."""
    rows = db.scalars(select(EmergencyAlert).where(
        EmergencyAlert.ended_at.is_(None),
        EmergencyAlert.tenant_id == tenant_id if tenant_id is not None else EmergencyAlert.partner_id == partner_id)).all()
    now = utcnow()
    for a in rows:
        a.ended_at, a.ended_by = now, by[:200]
    db.commit()
    refresh(db)
    return [a.id for a in rows if a.notify and a.notified_count and not a.cleared_count]


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


# ---------- besked til personerne (slukket som standard) ----------

def notify_allowed(db: Session, tenant_id: int | None = None, partner_id: int | None = None) -> bool:
    """Er SMS/mail/Teams ved nødbesked slået til? Huset slår det til for alle sine firmaer."""
    if tenant_id is not None:
        t = db.get(Tenant, tenant_id)
        return bool(t and (t.alert_notify or (t.partner is not None and t.partner.alert_notify)))
    p = db.get(Partner, partner_id) if partner_id else None
    return bool(p and p.alert_notify)


def _firms(db: Session, tenant_id: int | None, partner_id: int | None) -> list[Tenant]:
    if tenant_id is not None:
        t = db.get(Tenant, tenant_id)
        return [t] if t else []
    return list(db.scalars(select(Tenant).where(Tenant.partner_id == partner_id, Tenant.active == true())))


def recipients(db: Session, tenant_id: int | None = None, partner_id: int | None = None) -> dict:
    """Hvem der får besked: SMS til alle aktive personer med mobil, mail til dem med mail og Teams til firmaer med en
    Teams-kanal. Hvert nummer og hver adresse kun én gang."""
    firms = _firms(db, tenant_id, partner_id)
    by_id = {t.id: t for t in firms}
    sms, mail, seen_p, seen_m = [], [], set(), set()
    firm_ids = select(Tenant.id).where(Tenant.id == tenant_id) if tenant_id is not None else \
        select(Tenant.id).where(Tenant.partner_id == partner_id, Tenant.active == true())
    for h in db.scalars(select(Host).where(Host.tenant_id.in_(firm_ids), Host.active == true()).order_by(Host.id)).all():
        t = by_id.get(h.tenant_id)
        if t is None:
            continue
        num = normalize_msisdn(h.phone) if h.phone else ""
        if len(num) >= 8 and num not in seen_p:
            seen_p.add(num)
            sms.append((t, h.phone))
        addr = (h.email or "").strip().lower()
        if addr and valid_email(addr) and addr not in seen_m:
            seen_m.add(addr)
            mail.append((t, h.email.strip()))
    teams = [t for t in firms if t.teams_webhook]
    return {"sms": sms, "email": mail, "teams": teams}


def _scope_name(db: Session, a: EmergencyAlert) -> str:
    if a.tenant_id is not None:
        t = db.get(Tenant, a.tenant_id)
        return t.name if t else ""
    p = db.get(Partner, a.partner_id) if a.partner_id else None
    return p.name if p else ""


def texts(a: EmergencyAlert, name: str, phase: str) -> tuple[str, str, str]:
    """(SMS, mailens emne, mailens tekst)."""
    when = to_local(a.started_at if phase == "start" else (a.ended_at or utcnow())).strftime("%H:%M")
    if phase == "start":
        sms = f"{a.title.upper()} ({name}): {a.message}".strip()
        return sms[:459], f"{a.title} · {name}", f"{a.message}\n\nSendt kl. {when} fra skærmene i {name}."
    sms = f"Afblæst ({name}): {a.title} er slut kl. {when}. Du kan vende tilbage."
    return sms, f"Afblæst: {a.title} · {name}", f"{a.title} er afblæst kl. {when}. Du kan vende tilbage."


def sms_segments(text: str) -> int:
    return 1 if len(text) <= 160 else -(-len(text) // 153)


def preview(db: Session, tenant_id: int | None = None, partner_id: int | None = None, kind: str = "evacuation") -> dict:
    """Til vinduet i admin: antal modtagere og anslået pris for SMS'erne."""
    r = recipients(db, tenant_id, partner_id)
    title, msg = KINDS.get(kind, KINDS["evacuation"])
    seg = sms_segments(f"{title.upper()} (x): {msg}")
    price = db.scalar(select(Product.price).where(Product.code == "sms")) or 39
    cost = len(r["sms"]) * seg * price
    return {"enabled": notify_allowed(db, tenant_id, partner_id), "sms": len(r["sms"]), "email": len(r["email"]),
            "teams": len(r["teams"]), "segments": seg, "cost": cost,
            "cost_text": f"{cost / 100:.2f}".replace(".", ",") + " kr."}


def notify_people(alert_id: int, phase: str = "start") -> int:
    """Baggrundsopgave: send nødbeskeden (phase="start") eller afblæsningen (phase="clear") som SMS, mail og Teams.
    Sendes højst én gang pr. fase. Alle forsøg gemmes i beskedloggen (Notification), så SMS'erne tæller med i forbruget."""
    from .db import SessionLocal
    with SessionLocal() as db:
        a = db.get(EmergencyAlert, alert_id)
        if a is None or not a.notify:
            return 0
        if phase == "start" and a.notified_count:
            return 0
        if phase == "clear" and (not a.notified_count or a.cleared_count):
            return 0
        name = _scope_name(db, a)
        sms, subject, body = texts(a, name, phase)
        r = recipients(db, a.tenant_id, a.partner_id)
        rows: list[tuple[Notification, Tenant]] = []
        for t, phone in r["sms"]:
            rows.append((Notification(tenant_id=t.id, channel="sms", recipient=phone, subject=subject, body=sms), t))
        for t, addr in r["email"]:
            rows.append((Notification(tenant_id=t.id, channel="email", recipient=addr, subject=subject, body=body), t))
        for t in r["teams"]:
            rows.append((Notification(tenant_id=t.id, channel="teams", recipient="Teams", subject=subject, body=body), t))
        # Tæl op først, så en genstart midt i afsendelsen ikke sender det hele igen.
        if phase == "start":
            a.notified_count = len(rows) or -1
        else:
            a.cleared_count = len(rows) or -1
        for n, _ in rows:
            db.add(n)
        db.commit()
        for n, t in rows:
            deliver(n, t)
            db.commit()
        return len(rows)
