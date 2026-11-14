"""Abonnement og fakturering: pakker, tilkøb, rabatter og fakturagrundlag.

Principper:
- Kunden (BillingAccount) er et firma eller et hus. Kunden tilmeldes produkter (AccountProduct) med startdato.
- Løbende produkter faktureres forud til periodens slutning. Tilmelding midt i en periode kommer automatisk med på
  næste faktura, udregnet forholdsmæssigt pr. dag. Opsiges et produkt, der allerede er betalt, krediteres resten.
- Forbrug (SMS ud over pakken) afregnes bagud for perioden indtil fakturaens start.
- Rabat: fast på kunden (procent af alt løbende og forbrug), pr. produkt (procent) og engangsrabatter (Adjustment).
- Årsbetaling giver 2 måneder gratis (1/6 af det løbende for perioden).
- Priser er i øre ekskl. moms. Moms 25 % lægges på til sidst.
- En kladde (draft) kan laves om. Når fakturaen godkendes (final), flyttes billed_through, og engangsposter låses.
"""
import calendar
import json
from datetime import date, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import (AccountProduct, Adjustment, BillingAccount, Invoice, InvoiceLine, Notification, Partner, Product,
                     Tenant, utcnow)

VAT_PCT = 25
YEAR_FREE_MONTHS = 2
INTERVAL_MONTHS = {"month": 1, "quarter": 3, "year": 12}
INTERVAL_DA = {"month": "Månedlig", "quarter": "Kvartalsvis", "year": "Årlig (2 måneder gratis)"}
FIRST_NUMBER = 1001


def kr(oere: int) -> str:
    neg = oere < 0
    whole, frac = divmod(abs(int(oere)), 100)
    return ("-" if neg else "") + f"{whole:,}".replace(",", ".") + f",{frac:02d} kr."


def d_da(d: date) -> str:
    return f"{d.day}.{d.month}.{d.year}"


# ---------- perioder ----------

def add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def period_of(day: date, interval: str) -> tuple[date, date]:
    """Kalenderperioden, der indeholder dagen: måned, kvartal eller år. Slut er eksklusiv."""
    if interval == "year":
        start = date(day.year, 1, 1)
    elif interval == "quarter":
        start = date(day.year, 3 * ((day.month - 1) // 3) + 1, 1)
    else:
        start = date(day.year, day.month, 1)
    return start, add_months(start, INTERVAL_MONTHS[interval])


def next_period(day: date, interval: str) -> tuple[date, date]:
    _, end = period_of(day, interval)
    return period_of(end, interval)


def month_fraction(a: date, b: date) -> float:
    """Antal måneder i [a, b), hvor en brudt måned tæller med sine dage."""
    total, cur = 0.0, a
    while cur < b:
        days = calendar.monthrange(cur.year, cur.month)[1]
        month_end = date(cur.year, cur.month, days) + timedelta(days=1)
        stop = min(b, month_end)
        total += 1.0 if (cur.day == 1 and stop == month_end) else (stop - cur).days / days
        cur = stop
    return total


def span_text(a: date, b: date) -> str:
    """'1.12.2026–31.12.2026' (b er eksklusiv)."""
    return f"{d_da(a)}–{d_da(b - timedelta(days=1))}"


# ---------- kunder og produkter ----------

def account_for(db: Session, tenant: Tenant | None = None, partner: Partner | None = None,
                create: bool = True) -> BillingAccount | None:
    q = select(BillingAccount).where(BillingAccount.tenant_id == tenant.id) if tenant is not None else \
        select(BillingAccount).where(BillingAccount.partner_id == partner.id)
    acc = db.scalar(q)
    if acc is None and create:
        acc = BillingAccount(tenant_id=tenant.id if tenant else None, partner_id=partner.id if partner else None)
        db.add(acc)
        db.flush()
    return acc


def active_on(ap: AccountProduct, day: date) -> bool:
    return ap.start_date <= day and (ap.end_date is None or ap.end_date > day)


def subscriptions(db: Session, account_id: int) -> list[AccountProduct]:
    return list(db.scalars(select(AccountProduct).where(AccountProduct.account_id == account_id)
                           .order_by(AccountProduct.start_date, AccountProduct.id)))


def products_by_id(db: Session) -> dict[int, Product]:
    return {p.id: p for p in db.scalars(select(Product))}


def product_by_code(db: Session, code: str) -> Product:
    p = db.scalar(select(Product).where(Product.code == code))
    if p is None:
        raise HTTPException(404, "Produktet findes ikke")
    return p


def modules_of_account(db: Session, account_id: int, day: date) -> set[str]:
    prods = products_by_id(db)
    out: set[str] = set()
    for ap in subscriptions(db, account_id):
        if active_on(ap, day):
            out |= set(json.loads(prods[ap.product_id].modules or "[]"))
    return out


def subscribe(db: Session, acc: BillingAccount, product: Product, start: date, qty: int = 1,
              price_override: int | None = None, discount_pct: int = 0, note: str = "") -> AccountProduct:
    """Tilmeld et produkt. En ny pakke afløser den gamle fra samme dag (den gamle krediteres/afregnes forholdsmæssigt)."""
    if product.kind not in ("package", "addon"):
        raise HTTPException(422, "Engangsposter og forbrug tilmeldes ikke. Brug en engangspost i stedet")
    if not product.active:
        raise HTTPException(422, "Produktet er ikke længere på prislisten")
    kind_ok = product.audience == "all" or (product.audience == "house") == (acc.partner_id is not None)
    if not kind_ok:
        raise HTTPException(422, f"{product.name} er til {'huse' if product.audience == 'house' else 'firmaer'}")
    prods = products_by_id(db)
    for ap in subscriptions(db, acc.id):
        if ap.end_date is not None and ap.end_date <= start:
            continue
        other = prods[ap.product_id]
        if product.kind == "package" and other.kind == "package":
            end(db, ap, start)  # pakkeskift
        elif other.id == product.id:
            raise HTTPException(409, f"Kunden har allerede {product.name}. Ret antal i stedet")
    ap = AccountProduct(account_id=acc.id, product_id=product.id, qty=qty, start_date=start,
                        price_override=price_override, discount_pct=discount_pct, note=note.strip())
    db.add(ap)
    db.flush()
    return ap


def end(db: Session, ap: AccountProduct, day: date) -> None:
    """Opsig fra og med dagen. Er produktet ikke startet endnu, fjernes det helt."""
    if day <= ap.start_date and ap.billed_through is None:
        db.delete(ap)
    else:
        ap.end_date = max(day, ap.start_date)
    db.flush()


# ---------- udregning ----------

def _line(kind: str, text: str, qty: int, unit: int, amount: int, ref: int | None = None,
          ref_end: date | None = None) -> dict:
    return {"kind": kind, "description": text, "qty": qty, "unit_price": unit, "amount": amount, "ref_id": ref,
            "ref_end": ref_end}


def sms_count(db: Session, acc: BillingAccount, a: date, b: date) -> int:
    """SMS sendt i [a, b) for kundens firmaer (et hus dækker alle sine firmaer)."""
    tids = select(Tenant.id).where(Tenant.partner_id == acc.partner_id) if acc.partner_id else \
        select(Tenant.id).where(Tenant.id == acc.tenant_id)
    q = select(func.count()).select_from(Notification).where(
        Notification.tenant_id.in_(tids), Notification.channel == "sms", Notification.status == "sendt",
        Notification.created_at >= datetime(a.year, a.month, a.day), Notification.created_at < datetime(b.year, b.month, b.day))
    return int(db.scalar(q) or 0)


def compute(db: Session, acc: BillingAccount, ps: date, pe: date) -> dict:
    """Udregn fakturagrundlaget for perioden [ps, pe). Ændrer intet i databasen."""
    prods = products_by_id(db)
    lines: list[dict] = []
    recurring = 0
    for ap in subscriptions(db, acc.id):
        p = prods[ap.product_id]
        unit = p.price if ap.price_override is None else ap.price_override
        name = p.name + (f" × {ap.qty}" if ap.qty != 1 else "")
        disc = f" (rabat {ap.discount_pct} %)" if ap.discount_pct else ""
        frm = ap.billed_through or ap.start_date
        to = pe if ap.end_date is None else min(ap.end_date, pe)
        if frm < to:
            months = month_fraction(frm, to)
            amount = round(unit * ap.qty * months * (100 - ap.discount_pct) / 100)
            whole = abs(months - round(months)) < 1e-9
            mtxt = f"{int(round(months))} md." if whole else f"{months:.2f} md.".replace(".", ",", 1)
            lines.append(_line("product", f"{name} {span_text(frm, to)} ({mtxt}){disc}", ap.qty, unit, amount,
                               ap.id, to))
            recurring += amount
        elif ap.end_date is not None and ap.billed_through is not None and ap.end_date < ap.billed_through:
            months = month_fraction(ap.end_date, ap.billed_through)
            amount = -round(unit * ap.qty * months * (100 - ap.discount_pct) / 100)
            lines.append(_line("credit", f"Kreditering: {name} opsagt {span_text(ap.end_date, ap.billed_through)}",
                               ap.qty, unit, amount, ap.id, ap.end_date))
            recurring += amount

    # Forbrug bagud: SMS ud over pakkens SMS i perioden indtil fakturaens start.
    usage = 0
    u_from = acc.usage_billed_through or acc.created_at.date()
    sms = db.scalar(select(Product).where(Product.code == "sms"))
    if sms is not None and sms.active and u_from < ps:
        sent = sms_count(db, acc, u_from, ps)
        months = month_fraction(u_from, ps)
        included = 0
        for ap in subscriptions(db, acc.id):
            p = prods[ap.product_id]
            if p.included_sms:
                a, b = max(ap.start_date, u_from), min(ap.end_date or ps, ps)
                if a < b:
                    included += round(p.included_sms * ap.qty * month_fraction(a, b))
        extra = max(0, sent - included)
        if extra:
            usage = extra * sms.price
            lines.append(_line("usage", f"SMS ud over pakken {span_text(u_from, ps)} ({sent} sendt, {included} inkluderet)",
                               extra, sms.price, usage))

    if acc.interval == "year" and recurring > 0:
        free = -round(recurring * YEAR_FREE_MONTHS / 12)
        lines.append(_line("discount", f"Årsbetaling: {YEAR_FREE_MONTHS} måneder gratis", 1, free, free))
        recurring += free
    if acc.discount_pct and (recurring + usage) > 0:
        d = -round((recurring + usage) * acc.discount_pct / 100)
        lines.append(_line("discount", f"Fast rabat {acc.discount_pct} %", 1, d, d))

    for adj in db.scalars(select(Adjustment).where(Adjustment.account_id == acc.id, Adjustment.invoice_id.is_(None))
                          .order_by(Adjustment.id)):
        lines.append(_line("once", adj.description, adj.qty, adj.amount, adj.amount * adj.qty, adj.id))

    subtotal = sum(ln["amount"] for ln in lines)
    vat = round(subtotal * VAT_PCT / 100)
    return {"period_start": ps, "period_end": pe, "usage_until": ps, "lines": lines, "subtotal": subtotal,
            "vat": vat, "total": subtotal + vat}


def preview(db: Session, acc: BillingAccount, today: date) -> dict:
    """Næste faktura: den kommende periode inkl. alt, der ikke er faktureret endnu."""
    ps, pe = next_period(today, acc.interval)
    return compute(db, acc, ps, pe)


def make_draft(db: Session, acc: BillingAccount, ps: date, pe: date) -> Invoice | None:
    """Lav (eller lav om) kladden for perioden. Ingen kladde, hvis der ikke er noget at fakturere."""
    for old in db.scalars(select(Invoice).where(Invoice.account_id == acc.id, Invoice.status == "draft")).all():
        db.delete(old)
    db.flush()
    c = compute(db, acc, ps, pe)
    if not c["lines"]:
        return None
    inv = Invoice(account_id=acc.id, period_start=ps, period_end=pe, usage_until=c["usage_until"],
                  subtotal=c["subtotal"], vat=c["vat"], total=c["total"])
    db.add(inv)
    db.flush()
    for i, ln in enumerate(c["lines"]):
        db.add(InvoiceLine(invoice_id=inv.id, sort_order=i, **ln))
    db.flush()
    return inv


def finalize(db: Session, inv: Invoice) -> None:
    """Godkend: giv nummer, flyt billed_through og lås engangsposter. Kan ikke fortrydes."""
    if inv.status != "draft":
        raise HTTPException(409, "Fakturaen er allerede godkendt")
    last = db.scalar(select(func.max(Invoice.number)))
    inv.number = max(FIRST_NUMBER - 1, last or 0) + 1
    inv.status = "final"
    inv.finalized_at = utcnow()
    acc = db.get(BillingAccount, inv.account_id)
    for ln in db.scalars(select(InvoiceLine).where(InvoiceLine.invoice_id == inv.id)).all():
        if ln.kind in ("product", "credit") and ln.ref_id:
            ap = db.get(AccountProduct, ln.ref_id)
            if ap is not None:
                ap.billed_through = ln.ref_end
        elif ln.kind == "once" and ln.ref_id:
            adj = db.get(Adjustment, ln.ref_id)
            if adj is not None:
                adj.invoice_id = inv.id
    if inv.usage_until and (acc.usage_billed_through is None or inv.usage_until > acc.usage_billed_through):
        acc.usage_billed_through = inv.usage_until
    db.flush()


def due_accounts(db: Session, ps: date) -> list[BillingAccount]:
    """Kunder, hvis periode starter på denne dag (måned hver måned, kvartal i jan/apr/jul/okt, år i januar)."""
    out = []
    for acc in db.scalars(select(BillingAccount)).all():
        if period_of(ps, acc.interval)[0] == ps:
            out.append(acc)
    return out


# ---------- serializers ----------

def product_out(p: Product) -> dict:
    return {"id": p.id, "code": p.code, "name": p.name, "kind": p.kind, "audience": p.audience, "price": p.price,
            "price_text": kr(p.price), "unit": p.unit, "modules": json.loads(p.modules or "[]"),
            "included_sms": p.included_sms, "description": p.description,
            "features": json.loads(p.features or "[]"), "active": p.active, "sort_order": p.sort_order}


def lines_out(lines) -> list[dict]:
    out = []
    for ln in lines:
        d = ln if isinstance(ln, dict) else {"kind": ln.kind, "description": ln.description, "qty": ln.qty,
                                             "unit_price": ln.unit_price, "amount": ln.amount}
        out.append({"kind": d["kind"], "description": d["description"], "qty": d["qty"], "unit_price": d["unit_price"],
                    "amount": d["amount"], "amount_text": kr(d["amount"])})
    return out


def totals_out(subtotal: int, vat: int, total: int) -> dict:
    return {"subtotal": subtotal, "vat": vat, "total": total, "subtotal_text": kr(subtotal), "vat_text": kr(vat),
            "total_text": kr(total)}


def invoice_out(db: Session, inv: Invoice, customer: str = "") -> dict:
    lines = db.scalars(select(InvoiceLine).where(InvoiceLine.invoice_id == inv.id).order_by(InvoiceLine.sort_order))
    return {"id": inv.id, "number": inv.number, "account_id": inv.account_id, "customer": customer,
            "period_start": inv.period_start.isoformat(), "period_end": inv.period_end.isoformat(),
            "period_text": span_text(inv.period_start, inv.period_end), "status": inv.status,
            "status_text": {"draft": "Kladde", "final": "Godkendt", "paid": "Betalt"}[inv.status],
            "lines": lines_out(lines.all()), **totals_out(inv.subtotal, inv.vat, inv.total)}
