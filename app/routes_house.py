"""Kontorhotel (fase 4): hvem er i huset, evakueringsliste og besøgsstatistik."""
import csv
import io
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import house
from .auth import Principal, current
from .db import get_db
from .models import Partner, Tenant, utcnow
from .routes_admin import get_tenant_for

STATIC = Path(__file__).parent / "static"
admin = APIRouter(prefix="/api/admin", tags=["kontorhotel"], dependencies=[Depends(current)])
public = APIRouter(tags=["kontorhotel"])
pages = APIRouter(include_in_schema=False)


def _partner(db: Session, pid: int, p: Principal) -> Partner:
    partner = db.get(Partner, pid)
    if partner is None or not p.can_manage_partner(pid):
        raise HTTPException(404, "Partneren findes ikke")
    return partner


def _partner_tenants(db: Session, pid: int) -> list[Tenant]:
    return list(db.scalars(select(Tenant).where(Tenant.partner_id == pid).order_by(func.lower(Tenant.name))))


def _evac_url(request: Request, token: str) -> str:
    return f"{str(request.base_url).rstrip('/')}/e/{token}"


# ---------- hvem er i huset ----------

@admin.get("/tenants/{tid}/inside")
def tenant_inside(tid: int, db: Session = Depends(get_db), p: Principal = Depends(current)):
    t = get_tenant_for(db, tid, p)
    return house.inside_out(db, house.inside(db, [t.id]))


@admin.get("/partners/{pid}/inside")
def partner_inside(pid: int, db: Session = Depends(get_db), p: Principal = Depends(current)):
    _partner(db, pid, p)
    return house.inside_out(db, house.inside(db, [t.id for t in _partner_tenants(db, pid)]))


@admin.get("/tenants/{tid}/evac-link")
def tenant_evac_link(tid: int, request: Request, db: Session = Depends(get_db), p: Principal = Depends(current)):
    return {"url": _evac_url(request, house.evac_token("t", get_tenant_for(db, tid, p)))}


@admin.post("/tenants/{tid}/evac-link")
def tenant_new_evac_link(tid: int, request: Request, db: Session = Depends(get_db), p: Principal = Depends(current)):
    t = get_tenant_for(db, tid, p)
    t.evac_version += 1
    db.commit()
    return {"url": _evac_url(request, house.evac_token("t", t))}


@admin.get("/partners/{pid}/evac-link")
def partner_evac_link(pid: int, request: Request, db: Session = Depends(get_db), p: Principal = Depends(current)):
    return {"url": _evac_url(request, house.evac_token("p", _partner(db, pid, p)))}


@admin.post("/partners/{pid}/evac-link")
def partner_new_evac_link(pid: int, request: Request, db: Session = Depends(get_db), p: Principal = Depends(current)):
    partner = _partner(db, pid, p)
    partner.evac_version += 1
    db.commit()
    return {"url": _evac_url(request, house.evac_token("p", partner))}


@pages.get("/e/{token}")
def evac_page(token: str):
    return FileResponse(STATIC / "evac.html", headers={"Cache-Control": "no-cache"})


@public.get("/api/evac/{token}")
def evac_list(token: str, db: Session = Depends(get_db)):
    """Evakueringslisten: alle gæster i huset lige nu. Linket er hemmeligt og kan laves om i admin."""
    name, ids = house.evac_scope(db, token)
    return {"name": name, "guests": house.inside_out(db, house.inside(db, ids))}


# ---------- statistik ----------

def _stats_response(data: dict, fmt: str, filename: str):
    if fmt != "csv":
        return data
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")  # semikolon: dansk Excel
    w.writerow(["Firma", "Type"] + data["months"])
    for f in data["firms"]:
        w.writerow([f["name"], "Gæster"] + f["guests"])
        w.writerow([f["name"], "Pakker"] + f["deliveries"])
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@admin.get("/tenants/{tid}/stats")
def tenant_stats(tid: int, months: int = 12, format: str = "json", db: Session = Depends(get_db),
                 p: Principal = Depends(current)):
    t = get_tenant_for(db, tid, p)
    data = house.stats(db, [t], house.last_months(max(1, min(months, 36)), utcnow()))
    return _stats_response(data, format, "besog.csv")


@admin.get("/partners/{pid}/stats")
def partner_stats(pid: int, months: int = 12, format: str = "json", db: Session = Depends(get_db),
                  p: Principal = Depends(current)):
    _partner(db, pid, p)
    data = house.stats(db, _partner_tenants(db, pid), house.last_months(max(1, min(months, 36)), utcnow()))
    return _stats_response(data, format, "besog-pr-firma.csv")
