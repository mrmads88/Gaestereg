"""CRM-endpoints. Kun leverandøren (platform). Se crm.py."""
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, true
from sqlalchemy.orm import Session

from . import crm
from .auth import Principal, require_platform
from .db import get_db
from .models import CrmActivity, CrmCompany, CrmContact, CrmDeal, Partner, Tenant, utcnow

router = APIRouter(prefix="/api/admin/crm", tags=["crm"], dependencies=[Depends(require_platform)])

Status = Literal["emne", "kunde", "tidligere"]
Segment = Literal["firma", "kontorhotel", "andet"]
Stage = Literal["ny", "kontakt", "demo", "tilbud", "vundet", "tabt"]
Kind = Literal["note", "opkald", "moede", "mail", "opgave"]


def _strip(v):
    return v.strip() if isinstance(v, str) else v


class CompanyIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    status: Status = "emne"
    segment: Segment = "firma"
    cvr: str = Field("", max_length=20)
    website: str = Field("", max_length=200)
    phone: str = Field("", max_length=40)
    email: str = Field("", max_length=200)
    address: str = Field("", max_length=300)
    source: str = Field("", max_length=80)
    notes: str = Field("", max_length=20000)
    _s = field_validator("*", mode="before")(_strip)


class CompanyPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=160)
    status: Status | None = None
    segment: Segment | None = None
    cvr: str | None = Field(None, max_length=20)
    website: str | None = Field(None, max_length=200)
    phone: str | None = Field(None, max_length=40)
    email: str | None = Field(None, max_length=200)
    address: str | None = Field(None, max_length=300)
    source: str | None = Field(None, max_length=80)
    notes: str | None = Field(None, max_length=20000)
    # Kobling til Nodd: "tenant:12", "partner:3" eller "" for ingen.
    link: str | None = Field(None, max_length=30)
    _s = field_validator("*", mode="before")(_strip)


class ContactIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    title: str = Field("", max_length=120)
    email: str = Field("", max_length=200)
    phone: str = Field("", max_length=40)
    is_primary: bool = False
    notes: str = Field("", max_length=500)
    _s = field_validator("*", mode="before")(_strip)


class ContactPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    title: str | None = Field(None, max_length=120)
    email: str | None = Field(None, max_length=200)
    phone: str | None = Field(None, max_length=40)
    is_primary: bool | None = None
    notes: str | None = Field(None, max_length=500)
    _s = field_validator("*", mode="before")(_strip)


class DealIn(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    stage: Stage = "ny"
    monthly: int = Field(0, ge=0, le=100_000_000)  # øre
    once: int = Field(0, ge=0, le=100_000_000)
    expected_close: date | None = None
    _s = field_validator("title", mode="before")(_strip)


class DealPatch(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=160)
    stage: Stage | None = None
    monthly: int | None = Field(None, ge=0, le=100_000_000)
    once: int | None = Field(None, ge=0, le=100_000_000)
    expected_close: date | None = None
    clear_close: bool = False
    lost_reason: str | None = Field(None, max_length=300)


class ActivityIn(BaseModel):
    kind: Kind = "note"
    text: str = Field(min_length=1, max_length=5000)
    due_date: date | None = None
    deal_id: int | None = None
    contact_id: int | None = None
    _s = field_validator("text", mode="before")(_strip)


class ActivityPatch(BaseModel):
    text: str | None = Field(None, min_length=1, max_length=5000)
    due_date: date | None = None
    done: bool | None = None


def _company(db: Session, cid: int) -> CrmCompany:
    c = db.get(CrmCompany, cid)
    if c is None:
        raise HTTPException(404, "Firmaet findes ikke i CRM")
    return c


def _touch(c: CrmCompany) -> None:
    c.updated_at = utcnow()


@router.get("/overview")
def overview(db: Session = Depends(get_db)):
    return crm.overview(db)


@router.get("/companies")
def companies(q: str = "", status: str = "", db: Session = Depends(get_db)):
    return crm.list_companies(db, q[:100], status if status in crm.STATUS_DA else "")


@router.get("/companies.csv")
def companies_csv(q: str = "", status: str = "", db: Session = Depends(get_db)):
    rows = crm.list_companies(db, q[:100], status if status in crm.STATUS_DA else "")
    return Response(crm.companies_csv(rows), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="crm-firmaer-{crm.today()}.csv"'})


@router.post("/companies")
def create_company(body: CompanyIn, db: Session = Depends(get_db), p: Principal = Depends(require_platform)):
    c = CrmCompany(**body.model_dump())
    db.add(c)
    db.flush()
    crm.log_system(db, c, "Oprettet i CRM")
    db.commit()
    return crm.company_out(db, c)


@router.get("/companies/{cid}")
def company(cid: int, db: Session = Depends(get_db)):
    return crm.company_out(db, _company(db, cid))


@router.patch("/companies/{cid}")
def update_company(cid: int, body: CompanyPatch, db: Session = Depends(get_db)):
    c = _company(db, cid)
    data = body.model_dump(exclude_unset=True)
    link = data.pop("link", None)
    if "status" in data and data["status"] != c.status:
        crm.log_system(db, c, f"Status: {crm.STATUS_DA[c.status]} → {crm.STATUS_DA[data['status']]}")
    for k, v in data.items():
        if v is not None:
            setattr(c, k, v)
    if link is not None:
        kind, _, oid = link.partition(":")
        if not link:
            c.tenant_id = c.partner_id = None
        elif kind in ("tenant", "partner") and oid.isdigit():
            org = db.get(Tenant if kind == "tenant" else Partner, int(oid))
            if org is None:
                raise HTTPException(404, "Findes ikke i Nodd")
            taken = db.scalar(select(CrmCompany.id).where(
                (CrmCompany.tenant_id if kind == "tenant" else CrmCompany.partner_id) == org.id, CrmCompany.id != c.id))
            if taken:
                raise HTTPException(409, f"{org.name} er allerede koblet til et andet firma i CRM")
            c.tenant_id, c.partner_id = (org.id, None) if kind == "tenant" else (None, org.id)
            crm.log_system(db, c, f"Koblet til {org.name} i Nodd")
        else:
            raise HTTPException(422, "Ugyldig kobling")
    _touch(c)
    db.commit()
    return crm.company_out(db, c)


@router.delete("/companies/{cid}")
def delete_company(cid: int, db: Session = Depends(get_db)):
    db.delete(_company(db, cid))  # kontakter, salgsmuligheder og aktiviteter følger med (ON DELETE CASCADE)
    db.commit()
    return {"ok": True}


@router.post("/sync")
def sync(db: Session = Depends(get_db)):
    n = crm.sync_from_nodd(db)
    db.commit()
    return {"created": n, "message": f"{n} {'firma' if n == 1 else 'firmaer og huse'} hentet fra Nodd." if n else
            "Alle firmaer og huse i Nodd er allerede i CRM."}


@router.get("/nodd-options")
def nodd_options(db: Session = Depends(get_db)):
    """Firmaer og huse i Nodd, som et CRM-firma kan kobles til."""
    return [{"value": f"partner:{p.id}", "label": f"{p.name} (hus)"} for p in db.scalars(select(Partner).order_by(Partner.name))] + \
        [{"value": f"tenant:{t.id}", "label": t.name} for t in db.scalars(select(Tenant).order_by(Tenant.name))]


# ---------- kontakter ----------

def _primary_only(db: Session, x: CrmContact) -> None:
    if x.is_primary:
        for o in db.scalars(select(CrmContact).where(CrmContact.company_id == x.company_id, CrmContact.id != x.id,
                                                     CrmContact.is_primary == true())).all():
            o.is_primary = False


@router.post("/companies/{cid}/contacts")
def add_contact(cid: int, body: ContactIn, db: Session = Depends(get_db)):
    c = _company(db, cid)
    first = db.scalar(select(CrmContact.id).where(CrmContact.company_id == c.id)) is None
    x = CrmContact(company_id=c.id, **body.model_dump())
    x.is_primary = x.is_primary or first
    db.add(x)
    db.flush()
    _primary_only(db, x)
    _touch(c)
    db.commit()
    return crm.contact_out(x)


@router.patch("/contacts/{xid}")
def update_contact(xid: int, body: ContactPatch, db: Session = Depends(get_db)):
    x = db.get(CrmContact, xid)
    if x is None:
        raise HTTPException(404, "Kontakten findes ikke")
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(x, k, v)
    _primary_only(db, x)
    _touch(db.get(CrmCompany, x.company_id))
    db.commit()
    return crm.contact_out(x)


@router.delete("/contacts/{xid}")
def delete_contact(xid: int, db: Session = Depends(get_db)):
    x = db.get(CrmContact, xid)
    if x is None:
        raise HTTPException(404, "Kontakten findes ikke")
    crm.delete_contact(db, x)
    db.commit()
    return {"ok": True}


# ---------- salgsmuligheder ----------

@router.get("/deals")
def deals(db: Session = Depends(get_db)):
    return {"stages": [{"key": k, "label": v, "chance": crm.CHANCE[k]} for k, v in crm.STAGES], "deals": crm.pipeline(db)}


@router.post("/companies/{cid}/deals")
def add_deal(cid: int, body: DealIn, db: Session = Depends(get_db)):
    c = _company(db, cid)
    d = CrmDeal(company_id=c.id, title=body.title, stage="ny", monthly=body.monthly, once=body.once,
                expected_close=body.expected_close)
    db.add(d)
    db.flush()
    crm.log_system(db, c, f"Ny salgsmulighed: {d.title}", d.id)
    crm.set_stage(db, c, d, body.stage)
    _touch(c)
    db.commit()
    return crm.deal_out(d, c.name)


@router.patch("/deals/{did}")
def update_deal(did: int, body: DealPatch, db: Session = Depends(get_db)):
    d = db.get(CrmDeal, did)
    if d is None:
        raise HTTPException(404, "Salgsmuligheden findes ikke")
    c = db.get(CrmCompany, d.company_id)
    data = body.model_dump(exclude_unset=True)
    if data.get("stage"):
        crm.set_stage(db, c, d, data.pop("stage"))
    if data.pop("clear_close", False):
        d.expected_close = None
    for k in ("title", "monthly", "once", "expected_close", "lost_reason"):
        if data.get(k) is not None:
            setattr(d, k, data[k])
    _touch(c)
    db.commit()
    return crm.deal_out(d, c.name)


@router.delete("/deals/{did}")
def delete_deal(did: int, db: Session = Depends(get_db)):
    d = db.get(CrmDeal, did)
    if d is None:
        raise HTTPException(404, "Salgsmuligheden findes ikke")
    crm.delete_deal(db, d)
    db.commit()
    return {"ok": True}


# ---------- noter, opkald, møder og opgaver ----------

@router.post("/companies/{cid}/activities")
def add_activity(cid: int, body: ActivityIn, db: Session = Depends(get_db)):
    c = _company(db, cid)
    for fid, model in ((body.deal_id, CrmDeal), (body.contact_id, CrmContact)):
        if fid is not None:
            o = db.get(model, fid)
            if o is None or o.company_id != c.id:
                raise HTTPException(404, "Findes ikke på firmaet")
    if body.kind == "opgave" and body.due_date is None:
        body.due_date = crm.today()
    a = CrmActivity(company_id=c.id, **body.model_dump())
    db.add(a)
    _touch(c)
    db.commit()
    return crm.activity_out(a, c.name)


@router.patch("/activities/{aid}")
def update_activity(aid: int, body: ActivityPatch, db: Session = Depends(get_db)):
    a = db.get(CrmActivity, aid)
    if a is None or a.kind == "system":
        raise HTTPException(404, "Findes ikke")
    data = body.model_dump(exclude_unset=True)
    if data.get("text"):
        a.text = data["text"]
    if "due_date" in data and a.kind == "opgave" and data["due_date"] is not None:
        a.due_date = data["due_date"]
    if data.get("done") is not None:
        a.done_at = utcnow() if data["done"] else None
    db.commit()
    return crm.activity_out(a)


@router.delete("/activities/{aid}")
def delete_activity(aid: int, db: Session = Depends(get_db)):
    a = db.get(CrmActivity, aid)
    if a is None or a.kind == "system":
        raise HTTPException(404, "Findes ikke")
    db.delete(a)
    db.commit()
    return {"ok": True}
