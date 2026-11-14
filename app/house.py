"""Kontorhotel (fase 4): husets skærm, hvem er i huset, evakueringslinks og besøgsstatistik."""
from datetime import timedelta

from fastapi import HTTPException
from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy import select, true
from sqlalchemy.orm import Session

from .config import settings
from .models import Partner, Tenant, Visit, VisitStat
from .timeutil import start_of_local_day_utc, to_local

_evac = URLSafeSerializer(settings.secret_key, salt="evacuation")


# ---------- husets skærm ----------

def firms_of(db: Session, house: Tenant) -> list[Tenant]:
    """Firmaerne på husets skærm: partnerens aktive firmaer. Husets eget firma kun, hvis det har personer."""
    if not house.house_screen or house.partner_id is None:
        return []
    # == true() og ikke .is_(True): SQL Server forstår ikke "IS 1".
    ts = db.scalars(select(Tenant).where(Tenant.partner_id == house.partner_id, Tenant.active == true()))
    out = [t for t in ts if t.id != house.id or any(h.active for h in t.hosts)]
    return sorted(out, key=lambda t: t.name.casefold())


def firm_for(db: Session, house: Tenant, firm_id: int | None) -> Tenant:
    """Det firma, gæsten valgte på husets skærm. Uden husets skærm er det skærmens eget firma."""
    if firm_id is None or not house.house_screen:
        return house
    firm = db.get(Tenant, firm_id)
    if firm is None or not firm.active or firm.partner_id != house.partner_id or house.partner_id is None:
        raise HTTPException(404, "Firmaet findes ikke længere. Vælg igen")
    return firm


def tenant_ids_on_screen(db: Session, t: Tenant) -> list[int]:
    """De firmaer, en skærm dækker: husets skærm dækker alle partnerens firmaer og sig selv."""
    if not t.house_screen:
        return [t.id]
    return sorted({x.id for x in firms_of(db, t)} | {t.id})


# ---------- hvem er i huset ----------

def inside(db: Session, tenant_ids: list[int]) -> list[Visit]:
    """Gæster tjekket ind i dag og ikke tjekket ud. Pakker tæller ikke."""
    if not tenant_ids:
        return []
    return list(db.scalars(select(Visit).where(
        Visit.tenant_id.in_(tenant_ids), Visit.kind == "guest", Visit.checked_out_at.is_(None),
        Visit.checked_in_at >= start_of_local_day_utc()).order_by(Visit.checked_in_at)))


def evac_token(kind: str, obj) -> str:
    return _evac.dumps([kind, obj.id, obj.evac_version])


def evac_scope(db: Session, token: str) -> tuple[str, list[int]]:
    """Navn og firma-id'er for et evakueringslink. 404 hvis linket er lavet om eller ugyldigt."""
    try:
        kind, oid, version = _evac.loads(token)
    except (BadSignature, ValueError, TypeError):
        raise HTTPException(404, "Linket virker ikke længere")
    if kind == "p":
        p = db.get(Partner, oid)
        if p is None or p.evac_version != version:
            raise HTTPException(404, "Linket virker ikke længere")
        return p.name, [t.id for t in db.scalars(select(Tenant).where(Tenant.partner_id == p.id))]
    t = db.get(Tenant, oid)
    if t is None or t.evac_version != version:
        raise HTTPException(404, "Linket virker ikke længere")
    return t.name, [t.id]


def evac_owner(db: Session, token: str) -> tuple[str, int, str]:
    """("t" | "p", id, navn) for et gyldigt evakueringslink. 404 ellers."""
    name, _ = evac_scope(db, token)
    kind, oid, _ = _evac.loads(token)
    return kind, oid, name


def inside_out(db: Session, rows: list[Visit]) -> list[dict]:
    names = {t.id: t.name for t in db.scalars(select(Tenant).where(Tenant.id.in_({v.tenant_id for v in rows})))} if rows else {}
    return [{"id": v.id, "name": v.guest_name or "Gæst", "phone": v.guest_phone, "company": v.guest_company,
             "host": v.host_name, "firm": names.get(v.tenant_id, ""),
             "time": to_local(v.checked_in_at).strftime("%H:%M")} for v in rows]


# ---------- statistik ----------

def month_of(dt) -> str:
    return to_local(dt).strftime("%Y-%m")


def bump(db: Session, tenant_id: int, kind: str, when, n: int = 1) -> None:
    """Tæl besøg op. Kaldes ved check-ind og pakker. Committes sammen med besøget."""
    m = month_of(when)
    row = db.scalar(select(VisitStat).where(VisitStat.tenant_id == tenant_id, VisitStat.month == m,
                                            VisitStat.kind == kind))
    if row is None:
        db.add(VisitStat(tenant_id=tenant_id, month=m, kind=kind, count=n))
    else:
        row.count += n


def last_months(n: int, now) -> list[str]:
    d = to_local(now).replace(day=1)
    out = []
    for _ in range(n):
        out.append(d.strftime("%Y-%m"))
        d = (d - timedelta(days=1)).replace(day=1)
    return list(reversed(out))


def stats(db: Session, tenants: list[Tenant], months: list[str]) -> dict:
    ids = [t.id for t in tenants]
    rows = db.scalars(select(VisitStat).where(VisitStat.tenant_id.in_(ids), VisitStat.month.in_(months))) if ids else []
    data = {(r.tenant_id, r.month, r.kind): r.count for r in rows}
    return {"months": months, "firms": [
        {"id": t.id, "name": t.name,
         "guests": [data.get((t.id, m, "guest"), 0) for m in months],
         "deliveries": [data.get((t.id, m, "delivery"), 0) for m in months]} for t in tenants]}
