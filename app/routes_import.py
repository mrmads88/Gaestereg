"""Import af firmaer og personer fra Excel, CSV eller ZIP (se importer.py)."""
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from .auth import Principal, current
from .db import get_db
from .importer import Scope, apply_import, read_upload, template_xlsx
from .models import Partner
from .routes_admin import default_sender, get_tenant_for

router = APIRouter(prefix="/api/admin/import", tags=["import"], dependencies=[Depends(current)])


@router.get("/template")
def template(firma: bool = True, p: Principal = Depends(current)):
    with_firm = firma and p.role != "tenant"
    name = "skabelon-firmaer-og-personer.xlsx" if with_firm else "skabelon-personer.xlsx"
    return Response(template_xlsx(with_firm),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("")
async def run_import(file: UploadFile = File(...), dry_run: bool = Form(True), tenant_id: int | None = Form(None),
                     partner_id: int | None = Form(None), db: Session = Depends(get_db),
                     p: Principal = Depends(current)):
    """Med dry_run=true (standard) vises kun, hvad der vil ske. Intet gemmes."""
    if tenant_id is not None:
        scope = Scope("tenant", tenant=get_tenant_for(db, tenant_id, p))
    elif p.role == "tenant":
        scope = Scope("tenant", tenant=get_tenant_for(db, p.tenant_id, p))
    elif p.role == "partner":
        scope = Scope("partner", partner_id=p.partner_id)
    elif partner_id is not None:
        if db.get(Partner, partner_id) is None:
            raise HTTPException(404, "Partneren findes ikke")
        scope = Scope("partner", partner_id=partner_id)
    else:
        scope = Scope("none")
    sheet = read_upload(file.filename or "", await file.read())
    return apply_import(db, scope, sheet, dry_run, default_sender)
