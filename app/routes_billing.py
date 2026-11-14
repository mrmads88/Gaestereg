"""Abonnement og fakturering (kun leverandøren/platform): prisliste, tilmelding, rabatter og fakturagrundlag."""
import csv
import io
import json
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import billing, modules
from .auth import Principal, require_platform
from .db import get_db
from .models import AccountProduct, Adjustment, BillingAccount, Invoice, InvoiceLine, Partner, Product, Tenant

router = APIRouter(prefix="/api/admin/billing", tags=["fakturering"], dependencies=[Depends(require_platform)])


# ---------- input ----------

class ProductUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    price: float | None = Field(None, ge=0, le=1_000_000)  # kr.
    description: str | None = Field(None, max_length=500)
    features: list[str] | None = Field(None, max_length=12)
    included_sms: int | None = Field(None, ge=0, le=100_000)
    active: bool | None = None


class AccountUpdate(BaseModel):
    interval: str | None = Field(None, pattern="^(month|quarter|year)$")
    discount_pct: int | None = Field(None, ge=0, le=100)
    cvr: str | None = Field(None, max_length=20)
    invoice_email: str | None = Field(None, max_length=200)
    reference: str | None = Field(None, max_length=120)
    note: str | None = Field(None, max_length=500)


class SubscribeIn(BaseModel):
    product: str  # produktets kode, fx "komplet" eller "rooms"
    start: date | None = None  # tom = i dag
    qty: int = Field(1, ge=1, le=1000)
    price: float | None = Field(None, ge=0, le=1_000_000)  # særpris i kr. pr. md., tom = prislisten
    discount_pct: int = Field(0, ge=0, le=100)
    note: str = Field("", max_length=200)


class ChangeIn(BaseModel):
    """Ændring af antal, pris eller rabat fra en dato. Den gamle linje opsiges, og en ny starter samme dag."""
    start: date | None = None
    qty: int | None = Field(None, ge=1, le=1000)
    price: float | None = Field(None, ge=0, le=1_000_000)
    clear_price: bool = False
    discount_pct: int | None = Field(None, ge=0, le=100)


class EndIn(BaseModel):
    end: date | None = None  # tom = i dag


class AdjustmentIn(BaseModel):
    product: str | None = None  # engangsprodukt, fx "setup" eller "tablet"
    description: str = Field("", max_length=200)
    qty: int = Field(1, ge=1, le=1000)
    amount: float | None = Field(None, ge=-1_000_000, le=1_000_000)  # kr. pr. stk., negativ = rabat


class RunIn(BaseModel):
    period_start: date


# ---------- hjælpere ----------

def _oere(kroner: float | None) -> int | None:
    return None if kroner is None else int(round(kroner * 100))


def _account(db: Session, p: Principal, tenant_id: int | None, partner_id: int | None,
             create: bool = True) -> tuple[BillingAccount | None, str]:
    if tenant_id is not None:
        t = db.get(Tenant, tenant_id)
        if t is None:
            raise HTTPException(404, "Kunden findes ikke")
        return billing.account_for(db, tenant=t, create=create), t.name
    if partner_id is not None:
        pa = db.get(Partner, partner_id)
        if pa is None:
            raise HTTPException(404, "Partneren findes ikke")
        return billing.account_for(db, partner=pa, create=create), pa.name
    raise HTTPException(422, "Vælg kunde eller partner")


def _customer_names(db: Session) -> dict[int, tuple[str, str]]:
    """account_id -> (navn, 'firma'/'hus')."""
    tn = {t.id: t.name for t in db.scalars(select(Tenant))}
    pn = {p.id: p.name for p in db.scalars(select(Partner))}
    return {a.id: (tn.get(a.tenant_id, "?"), "firma") if a.tenant_id else (pn.get(a.partner_id, "?"), "hus")
            for a in db.scalars(select(BillingAccount))}


def _sub_out(ap: AccountProduct, p: Product, today: date) -> dict:
    unit = p.price if ap.price_override is None else ap.price_override
    state = "future" if ap.start_date > today else "ended" if (ap.end_date and ap.end_date <= today) else \
        "ending" if ap.end_date else "active"
    monthly = round(unit * ap.qty * (100 - ap.discount_pct) / 100)
    return {"id": ap.id, "product": billing.product_out(p), "qty": ap.qty, "start": ap.start_date.isoformat(),
            "end": ap.end_date.isoformat() if ap.end_date else None,
            "billed_through": ap.billed_through.isoformat() if ap.billed_through else None,
            "price_override": ap.price_override, "unit_price": unit, "unit_text": billing.kr(unit),
            "discount_pct": ap.discount_pct, "monthly": monthly, "monthly_text": billing.kr(monthly),
            "note": ap.note, "state": state}


def _account_out(db: Session, acc: BillingAccount, name: str) -> dict:
    today = date.today()
    prods = billing.products_by_id(db)
    subs = [_sub_out(ap, prods[ap.product_id], today) for ap in billing.subscriptions(db, acc.id)]
    live = [s for s in subs if s["state"] in ("active", "ending")]
    monthly = sum(s["monthly"] for s in live)
    if acc.interval == "year":
        monthly = round(monthly * (12 - billing.YEAR_FREE_MONTHS) / 12)
    monthly = round(monthly * (100 - acc.discount_pct) / 100)
    nxt = billing.preview(db, acc, today)
    adjs = db.scalars(select(Adjustment).where(Adjustment.account_id == acc.id, Adjustment.invoice_id.is_(None))
                      .order_by(Adjustment.id)).all()
    invs = db.scalars(select(Invoice).where(Invoice.account_id == acc.id).order_by(Invoice.period_start.desc(),
                                                                                   Invoice.id.desc())).all()
    owner_mods = sorted(billing.modules_of_account(db, acc.id, today))
    return {
        "id": acc.id, "name": name, "tenant_id": acc.tenant_id, "partner_id": acc.partner_id,
        "interval": acc.interval, "interval_text": billing.INTERVAL_DA[acc.interval], "discount_pct": acc.discount_pct,
        "cvr": acc.cvr, "invoice_email": acc.invoice_email, "reference": acc.reference, "note": acc.note,
        "subscriptions": subs, "modules": owner_mods,
        "monthly": monthly, "monthly_text": billing.kr(monthly),
        "adjustments": [{"id": a.id, "description": a.description, "qty": a.qty, "amount": a.amount,
                         "amount_text": billing.kr(a.amount * a.qty)} for a in adjs],
        "next_invoice": {"period_text": billing.span_text(nxt["period_start"], nxt["period_end"]),
                         "lines": billing.lines_out(nxt["lines"]),
                         **billing.totals_out(nxt["subtotal"], nxt["vat"], nxt["total"])},
        "invoices": [{"id": i.id, "number": i.number, "period_text": billing.span_text(i.period_start, i.period_end),
                      "status": i.status, "total_text": billing.kr(i.total)} for i in invs],
    }


def _done(db: Session, acc: BillingAccount, name: str) -> dict:
    db.commit()
    modules.clear_cache()
    return _account_out(db, acc, name)


# ---------- prislisten ----------

@router.get("/products")
def list_products(db: Session = Depends(get_db)):
    return [billing.product_out(p) for p in db.scalars(select(Product).order_by(Product.sort_order, Product.id))]


@router.patch("/products/{pid}")
def update_product(pid: int, body: ProductUpdate, db: Session = Depends(get_db)):
    """Nye priser gælder fra næste faktura for alle, der ikke har en særpris. Allerede godkendte fakturaer ændres ikke."""
    p = db.get(Product, pid)
    if p is None:
        raise HTTPException(404, "Produktet findes ikke")
    for k, v in body.model_dump(exclude_unset=True).items():
        if k == "price":
            v = _oere(v)
        elif k == "features":
            v = json.dumps([x.strip() for x in v if x.strip()], ensure_ascii=False)
        elif isinstance(v, str):
            v = v.strip()
        setattr(p, k, v)
    db.commit()
    modules.clear_cache()
    return billing.product_out(p)


# ---------- kunden ----------

@router.get("/account")
def get_account(tenant_id: int | None = None, partner_id: int | None = None, db: Session = Depends(get_db),
                p: Principal = Depends(require_platform)):
    acc, name = _account(db, p, tenant_id, partner_id)
    db.commit()
    return _account_out(db, acc, name)


@router.patch("/account")
def update_account(body: AccountUpdate, tenant_id: int | None = None, partner_id: int | None = None,
                   db: Session = Depends(get_db), p: Principal = Depends(require_platform)):
    acc, name = _account(db, p, tenant_id, partner_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(acc, k, v.strip() if isinstance(v, str) else v)
    return _done(db, acc, name)


@router.post("/account/subscriptions")
def subscribe(body: SubscribeIn, tenant_id: int | None = None, partner_id: int | None = None,
              db: Session = Depends(get_db), p: Principal = Depends(require_platform)):
    acc, name = _account(db, p, tenant_id, partner_id)
    billing.subscribe(db, acc, billing.product_by_code(db, body.product), body.start or date.today(), body.qty,
                      _oere(body.price), body.discount_pct, body.note)
    return _done(db, acc, name)


def _sub(db: Session, sid: int) -> tuple[AccountProduct, BillingAccount, str]:
    ap = db.get(AccountProduct, sid)
    if ap is None:
        raise HTTPException(404, "Tilmeldingen findes ikke")
    acc = db.get(BillingAccount, ap.account_id)
    return ap, acc, _customer_names(db).get(acc.id, ("", ""))[0]


@router.post("/subscriptions/{sid}/change")
def change(sid: int, body: ChangeIn, db: Session = Depends(get_db)):
    ap, acc, name = _sub(db, sid)
    day = body.start or date.today()
    if ap.end_date is not None and ap.end_date <= day:
        raise HTTPException(409, "Tilmeldingen er opsagt")
    new = AccountProduct(account_id=acc.id, product_id=ap.product_id, start_date=max(day, ap.start_date),
                         qty=body.qty or ap.qty, discount_pct=ap.discount_pct if body.discount_pct is None else body.discount_pct,
                         price_override=None if body.clear_price else (_oere(body.price) if body.price is not None
                                                                         else ap.price_override),
                         end_date=ap.end_date, note=ap.note)
    if day <= ap.start_date and ap.billed_through is None:
        db.delete(ap)  # ikke startet og ikke faktureret: bare ret den
    else:
        ap.end_date = day
    db.add(new)
    return _done(db, acc, name)


@router.post("/subscriptions/{sid}/end")
def end_subscription(sid: int, body: EndIn, db: Session = Depends(get_db)):
    ap, acc, name = _sub(db, sid)
    billing.end(db, ap, body.end or date.today())
    return _done(db, acc, name)


@router.post("/account/adjustments")
def add_adjustment(body: AdjustmentIn, tenant_id: int | None = None, partner_id: int | None = None,
                   db: Session = Depends(get_db), p: Principal = Depends(require_platform)):
    """Engangspost på næste faktura: et engangsprodukt (opsætning, tablet) eller en engangsrabat (negativt beløb)."""
    acc, name = _account(db, p, tenant_id, partner_id)
    if body.product:
        prod = billing.product_by_code(db, body.product)
        if prod.kind != "once":
            raise HTTPException(422, "Kun engangsprodukter kan lægges på som engangspost")
        amount = _oere(body.amount) if body.amount is not None else prod.price
        db.add(Adjustment(account_id=acc.id, product_id=prod.id, description=body.description.strip() or prod.name,
                          qty=body.qty, amount=amount))
    else:
        if body.amount is None or not body.description.strip():
            raise HTTPException(422, "Skriv en tekst og et beløb")
        db.add(Adjustment(account_id=acc.id, description=body.description.strip(), qty=body.qty,
                          amount=_oere(body.amount)))
    return _done(db, acc, name)


@router.delete("/adjustments/{aid}")
def delete_adjustment(aid: int, db: Session = Depends(get_db)):
    a = db.get(Adjustment, aid)
    if a is None or a.invoice_id is not None:
        raise HTTPException(404, "Posten findes ikke eller er allerede faktureret")
    acc = db.get(BillingAccount, a.account_id)
    db.delete(a)
    return _done(db, acc, _customer_names(db).get(acc.id, ("", ""))[0])


@router.post("/account/invoice-now")
def invoice_now(tenant_id: int | None = None, partner_id: int | None = None, db: Session = Depends(get_db),
                p: Principal = Depends(require_platform)):
    """Lav en kladde nu for den igangværende periode (fx når en ny kunde starter midt i måneden)."""
    acc, name = _account(db, p, tenant_id, partner_id)
    ps, pe = billing.period_of(date.today(), acc.interval)
    inv = billing.make_draft(db, acc, ps, pe)
    db.commit()
    if inv is None:
        raise HTTPException(409, "Der er ikke noget at fakturere")
    return billing.invoice_out(db, inv, name)


# ---------- fakturakørsel ----------

@router.post("/run")
def run(body: RunIn, db: Session = Depends(get_db)):
    """Lav kladder for alle kunder, hvis periode starter på datoen (normalt den 1. i måneden)."""
    if body.period_start.day != 1:
        raise HTTPException(422, "Perioden starter den 1. i en måned")
    names = _customer_names(db)
    made = []
    for acc in billing.due_accounts(db, body.period_start):
        if db.scalar(select(Invoice).where(Invoice.account_id == acc.id, Invoice.status != "draft",
                                           Invoice.period_start == body.period_start)):
            continue  # allerede godkendt for perioden
        _, pe = billing.period_of(body.period_start, acc.interval)
        inv = billing.make_draft(db, acc, body.period_start, pe)
        if inv is not None:
            made.append(billing.invoice_out(db, inv, names[acc.id][0]))
    db.commit()
    return {"count": len(made), "invoices": made}


@router.get("/invoices")
def list_invoices(status: str | None = None, db: Session = Depends(get_db)):
    names = _customer_names(db)
    q = select(Invoice).order_by(Invoice.period_start.desc(), Invoice.id.desc())
    if status:
        q = q.where(Invoice.status == status)
    invs = db.scalars(q.limit(500)).all()
    return [{"id": i.id, "number": i.number, "customer": names.get(i.account_id, ("?", ""))[0],
             "customer_kind": names.get(i.account_id, ("?", ""))[1], "period_text": billing.span_text(i.period_start, i.period_end),
             "status": i.status, "total": i.total, "total_text": billing.kr(i.total),
             "subtotal_text": billing.kr(i.subtotal)} for i in invs]


def _inv(db: Session, iid: int) -> Invoice:
    inv = db.get(Invoice, iid)
    if inv is None:
        raise HTTPException(404, "Fakturaen findes ikke")
    return inv


@router.get("/invoices/{iid}")
def get_invoice(iid: int, db: Session = Depends(get_db)):
    inv = _inv(db, iid)
    return billing.invoice_out(db, inv, _customer_names(db).get(inv.account_id, ("", ""))[0])


@router.post("/invoices/{iid}/finalize")
def finalize(iid: int, db: Session = Depends(get_db)):
    inv = _inv(db, iid)
    billing.finalize(db, inv)
    db.commit()
    return billing.invoice_out(db, inv, _customer_names(db).get(inv.account_id, ("", ""))[0])


@router.post("/invoices/{iid}/paid")
def mark_paid(iid: int, db: Session = Depends(get_db)):
    inv = _inv(db, iid)
    if inv.status != "final":
        raise HTTPException(409, "Godkend fakturaen først")
    inv.status = "paid"
    db.commit()
    return billing.invoice_out(db, inv, _customer_names(db).get(inv.account_id, ("", ""))[0])


@router.delete("/invoices/{iid}")
def delete_draft(iid: int, db: Session = Depends(get_db)):
    inv = _inv(db, iid)
    if inv.status != "draft":
        raise HTTPException(409, "Kun kladder kan slettes")
    db.delete(inv)
    db.commit()
    return {"ok": True}


@router.get("/invoices.csv")
def invoices_csv(status: str = "final", db: Session = Depends(get_db)):
    """Fakturalinjer til bogføringen (fx import i e-conomic eller Dinero). Beløb ekskl. moms."""
    names = _customer_names(db)
    accs = {a.id: a for a in db.scalars(select(BillingAccount))}
    invs = db.scalars(select(Invoice).where(Invoice.status == status).order_by(Invoice.number, Invoice.id)).all()
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Fakturanr", "Kunde", "CVR", "Faktura-mail", "Reference", "Periode", "Tekst", "Antal", "Stykpris",
                "Beløb", "Moms", "I alt inkl. moms"])
    fmt = lambda o: f"{o / 100:.2f}".replace(".", ",")  # noqa: E731
    for inv in invs:
        a = accs.get(inv.account_id)
        for ln in db.scalars(select(InvoiceLine).where(InvoiceLine.invoice_id == inv.id).order_by(InvoiceLine.sort_order)).all():
            w.writerow([inv.number or "", names.get(inv.account_id, ("", ""))[0], a.cvr if a else "",
                        a.invoice_email if a else "", a.reference if a else "",
                        billing.span_text(inv.period_start, inv.period_end), ln.description, ln.qty,
                        fmt(ln.unit_price), fmt(ln.amount), "", ""])
        w.writerow([inv.number or "", names.get(inv.account_id, ("", ""))[0], "", "", "", "", "I alt", "", "",
                    fmt(inv.subtotal), fmt(inv.vat), fmt(inv.total)])
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="fakturaer-{status}.csv"'})
