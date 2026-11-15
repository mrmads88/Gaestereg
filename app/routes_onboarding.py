"""Opsætning af nye kunder: "Kom i gang"-tjeklisten på kunden og demoen til salgsmøder (demo.py)."""
from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select, true
from sqlalchemy.orm import Session

from . import billing, demo, legal, modules, presence
from .auth import Principal, current, require_platform
from .db import get_db
from .models import Host, User, Visit, VisitStat
from .routes_admin import get_tenant_for

router = APIRouter(prefix="/api/admin", tags=["opsætning"], dependencies=[Depends(current)])


class HideIn(BaseModel):
    hidden: bool = True


def _any(db: Session, q) -> bool:
    """Findes der mindst én række? (SQL Server forstår ikke SELECT EXISTS, så vi henter højst én.)"""
    return db.scalar(q.limit(1)) is not None


def checklist(db: Session, t, p: Principal) -> dict:
    """Det, en ny kunde mangler for at være i gang. Krydses af af sig selv, efterhånden som det sker."""
    items = [
        ("look", "Logo og farve", bool(t.logo_path), "look", "Gør skærmen til jeres egen under Udseende."),
        ("people", "Personer på skærmen", _any(db, select(Host.id).where(Host.tenant_id == t.id, Host.active == true())),
         "people", "Tilføj dem, gæsterne kan vælge, eller importér fra Excel."),
        ("screen", "Skærmen er tændt", bool(presence.status(t.kiosk_token)["seen_at"]) or
         _any(db, select(Visit.id).where(Visit.tenant_id == t.id)), "look",
         "Åbn skærmlinket på tabletten i receptionen."),
        ("guest", "Første gæst tjekket ind", bool(db.scalar(select(func.coalesce(func.sum(VisitStat.count), 0))
                                                           .where(VisitStat.tenant_id == t.id))), "log",
         "Prøv selv at tjekke ind på skærmen."),
        ("dpa", "Databehandleraftale accepteret", t.dpa_version == legal.version() or
         (t.partner is not None and t.partner.dpa_version == legal.version()), "sub",
         "Kundens admin accepterer den ved første login."),
    ]
    if modules.tenant_has(t, "self_service") and t.partner_id is None:
        items.insert(4, ("admin", "Administrator inviteret", _any(db, select(User.id).where(User.tenant_id == t.id)),
                         "access", "Invitér kundens egen administrator under Adgang."))
    if p.is_platform:
        acc = billing.account_for(db, tenant=t, create=False) if t.partner_id is None else \
            billing.account_for(db, partner=t.partner, create=False)
        prods = billing.products_by_id(db)
        has_pkg = acc is not None and any(billing.active_on(ap, date.today()) and prods[ap.product_id].kind == "package"
                                          for ap in billing.subscriptions(db, acc.id))
        items.append(("package", "Pakke valgt", has_pkg, "sub", "Vælg kundens pakke under Abonnement."))
    out = [{"key": k, "label": label, "done": bool(done), "tab": tab, "hint": hint} for k, label, done, tab, hint in items]
    n = sum(1 for x in out if x["done"])
    return {"items": out, "done": n, "total": len(out), "complete": n == len(out), "hidden": t.checklist_hidden}


@router.get("/tenants/{tid}/checklist")
def get_checklist(tid: int, db: Session = Depends(get_db), p: Principal = Depends(current)):
    return checklist(db, get_tenant_for(db, tid, p), p)


@router.post("/tenants/{tid}/checklist/hide")
def hide_checklist(tid: int, body: HideIn, db: Session = Depends(get_db), p: Principal = Depends(current)):
    t = get_tenant_for(db, tid, p)
    t.checklist_hidden = body.hidden
    db.commit()
    return checklist(db, t, p)


# ---------- demo ----------

@router.get("/demo")
def demo_status(db: Session = Depends(get_db), p: Principal = Depends(require_platform)):
    return demo.status(db)


@router.post("/demo")
def demo_build(db: Session = Depends(get_db), p: Principal = Depends(require_platform)):
    """Lav demoen (forfra). Alt i den tidligere demo slettes."""
    return demo.build(db)


@router.delete("/demo")
def demo_remove(db: Session = Depends(get_db), p: Principal = Depends(require_platform)):
    return {"removed": demo.remove(db)}
