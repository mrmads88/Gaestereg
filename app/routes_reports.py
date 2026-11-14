"""Overblik og månedsrapport: rapportsiden (/admin/rapport), tallene, CSV og prøveudsendelse."""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import modules, reports
from .auth import Principal, current
from .db import get_db
from .models import Partner
from .routes_admin import get_tenant_for

STATIC = Path(__file__).parent / "static"
admin = APIRouter(prefix="/api/admin/report", tags=["overblik"], dependencies=[Depends(current)])
pages = APIRouter(include_in_schema=False)


class SendTestIn(BaseModel):
    to: str = Field("", max_length=500)  # tom = de adresser, der er sat op


def _scope(db: Session, p: Principal, tenant_id: int | None, partner_id: int | None):
    """(tenant, partner, kind, id). Kræver modulet "reports", undtagen for leverandøren, der kan vise det til kunder."""
    if tenant_id is not None:
        t = get_tenant_for(db, tenant_id, p)
        if not p.is_platform:
            modules.require_tenant(t, "reports")
        return t, None, "tenant", t.id
    if partner_id is not None:
        pa = db.get(Partner, partner_id)
        if pa is None or not p.can_manage_partner(partner_id):
            raise HTTPException(404, "Partneren findes ikke")
        if not p.is_platform:
            modules.require_partner(pa, "reports")
        return None, pa, "partner", pa.id
    raise HTTPException(422, "Vælg firma eller hus")


@pages.get("/admin/rapport")
def report_page():
    return FileResponse(STATIC / "report.html", headers={"Cache-Control": "no-cache"})


@admin.get("")
def report(tenant_id: int | None = None, partner_id: int | None = None, period: str | None = None,
           format: str = "json", db: Session = Depends(get_db), p: Principal = Depends(current)):
    t, pa, kind, oid = _scope(db, p, tenant_id, partner_id)
    r = reports.build(db, tenant=t, partner=pa, period=period)
    if format == "csv":
        return Response(reports.to_csv(r), media_type="text/csv; charset=utf-8", headers={
            "Content-Disposition": f'attachment; filename="overblik-{r["period"]["key"]}.csv"'})
    r["has_reports_module"] = modules.tenant_has(t, "reports") if t is not None else modules.partner_has(pa, "reports")
    return r


@admin.get("/mail-preview", response_class=HTMLResponse)
def mail_preview(tenant_id: int | None = None, partner_id: int | None = None, period: str | None = None,
                 db: Session = Depends(get_db), p: Principal = Depends(current)):
    """Sådan ser månedsmailen ud (til at vise kunden, før den sendes)."""
    t, pa, kind, oid = _scope(db, p, tenant_id, partner_id)
    r = reports.build(db, tenant=t, partner=pa, period=period)
    subject, _, body = reports.mail_for(r, reports.report_link(kind, oid, r["period"]["key"]))
    return HTMLResponse(f"<!doctype html><meta charset=utf-8><title>{subject}</title>{body}",
                        headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src *"})


@admin.get("/settings")
def report_settings(tenant_id: int | None = None, partner_id: int | None = None, db: Session = Depends(get_db),
                    p: Principal = Depends(current)):
    t, pa, kind, oid = _scope(db, p, tenant_id, partner_id)
    obj = t or pa
    return {"report_email": obj.report_email, "runs": reports.runs_for(db, kind, oid),
            "module": modules.tenant_has(t, "reports") if t is not None else modules.partner_has(pa, "reports")}


@admin.post("/send-test")
def send_test(body: SendTestIn, tenant_id: int | None = None, partner_id: int | None = None,
              db: Session = Depends(get_db), p: Principal = Depends(current)):
    """Send sidste måneds rapport nu. Gemmes ikke som månedens udsendelse."""
    t, pa, kind, oid = _scope(db, p, tenant_id, partner_id)
    to = reports.recipients(body.to or (t or pa).report_email)
    if not to:
        raise HTTPException(422, "Skriv mindst én e-mailadresse")
    r = reports.build(db, tenant=t, partner=pa)
    status, error = reports.deliver_report(r, to, reports.report_link(kind, oid, r["period"]["key"]))
    msg = {"sendt": "Rapporten er sendt til " + ", ".join(to),
           "test": "Testtilstand: rapporten er ikke sendt. Se mailen med Vis mailen.",
           "fejl": "Rapporten kunne ikke sendes: " + error}[status]
    return {"status": status, "message": msg, "recipients": to, "period": r["period"]["label"]}
