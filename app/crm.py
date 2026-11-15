"""Leverandørens CRM: firmaer, kontakter, salgsmuligheder (pipeline) og en tidslinje med noter og opgaver.

Kun leverandøren (platform) ser CRM'et. Et CRM-firma kan kobles til et firma eller hus i Nodd. Så viser kortet
nøgletal derfra (månedlig omsætning, besøg, seneste login) og tidslinjen får Nodd-hændelser (oprettet, fakturaer,
databehandleraftale) uden at de gemmes to gange.

Morgenmail med dagens opfølgninger: kl. 07.30 til CRM_EMAIL (eller OPS_EMAIL), kun når CRM_DIGEST er slået til
(standard i prod, så den gratis dev-database ikke vækkes hver dag). Én gang pr. dag takket være report_runs.
"""
import csv
import io
import logging
import threading
import time
from datetime import date, datetime, timedelta

from sqlalchemy import false, func, or_, select, true
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import billing
from .config import settings
from .models import (BillingAccount, CrmActivity, CrmCompany, CrmContact, CrmDeal, Invoice, Partner,
                     ReportRun, Tenant, User, VisitStat, utcnow)
from .timeutil import TZ, local_iso

log = logging.getLogger("gaestereg.crm")

STAGES = [("ny", "Ny"), ("kontakt", "I dialog"), ("demo", "Demo"), ("tilbud", "Tilbud sendt"), ("vundet", "Vundet"),
          ("tabt", "Tabt")]
STAGE_DA = dict(STAGES)
OPEN = ("ny", "kontakt", "demo", "tilbud")
CHANCE = {"ny": 10, "kontakt": 25, "demo": 50, "tilbud": 75, "vundet": 100, "tabt": 0}  # vægtet pipeline (%)
STATUS_DA = {"emne": "Emne", "kunde": "Kunde", "tidligere": "Tidligere kunde"}
SEGMENT_DA = {"firma": "Firma", "kontorhotel": "Kontorhotel", "andet": "Andet"}
KIND_DA = {"note": "Note", "opkald": "Opkald", "moede": "Møde", "mail": "Mail", "opgave": "Opgave", "system": "Ændring"}


def today() -> date:
    return datetime.now(TZ).date()


# ---------- tal fra Nodd ----------

def mrr(db: Session, acc: BillingAccount, day: date) -> int:
    """Løbende omsætning pr. måned (øre ekskl. moms) for kontoens aktive pakker og tilkøb."""
    prods = billing.products_by_id(db)
    total = 0
    for ap in billing.subscriptions(db, acc.id):
        if billing.active_on(ap, day):
            p = prods[ap.product_id]
            unit = p.price if ap.price_override is None else ap.price_override
            total += unit * ap.qty * (100 - ap.discount_pct) / 100
    if acc.interval == "year":
        total *= (12 - billing.YEAR_FREE_MONTHS) / 12
    total *= (100 - acc.discount_pct) / 100
    return round(total)


def _account(db: Session, c: CrmCompany) -> BillingAccount | None:
    if c.tenant_id:
        return db.scalar(select(BillingAccount).where(BillingAccount.tenant_id == c.tenant_id))
    if c.partner_id:
        return db.scalar(select(BillingAccount).where(BillingAccount.partner_id == c.partner_id))
    return None


def _tenant_ids(db: Session, c: CrmCompany) -> list[int]:
    if c.tenant_id:
        return [c.tenant_id]
    if c.partner_id:
        return list(db.scalars(select(Tenant.id).where(Tenant.partner_id == c.partner_id)).all())
    return []


def linked(db: Session, c: CrmCompany) -> dict | None:
    """Koblingen til Nodd og nøgletal derfra."""
    org = db.get(Tenant, c.tenant_id) if c.tenant_id else db.get(Partner, c.partner_id) if c.partner_id else None
    if org is None:
        return None
    kind = "tenant" if isinstance(org, Tenant) else "partner"
    month = today().strftime("%Y-%m")
    prev = (today().replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    if kind == "tenant":
        tids = select(Tenant.id).where(Tenant.id == org.id)
        users = User.tenant_id == org.id
    else:
        tids = select(Tenant.id).where(Tenant.partner_id == org.id)
        users = or_(User.partner_id == org.id, User.tenant_id.in_(tids))
    visits = dict(db.execute(select(VisitStat.month, func.sum(VisitStat.count))
                             .where(VisitStat.tenant_id.in_(tids), VisitStat.month.in_((month, prev)),
                                    VisitStat.kind == "guest")
                             .group_by(VisitStat.month)).all())
    acc = _account(db, c)
    return {"kind": kind, "id": org.id, "name": org.name,
            "firms": db.scalar(select(func.count()).select_from(Tenant).where(Tenant.partner_id == org.id))
            if kind == "partner" else None,
            "mrr": mrr(db, acc, today()) if acc else 0,
            "visits_month": int(visits.get(month) or 0), "visits_prev": int(visits.get(prev) or 0),
            "last_login": local_iso(db.scalar(select(func.max(User.last_login_at)).where(users))),
            "dpa": bool(org.dpa_accepted_at), "created_at": local_iso(org.created_at)}


def nodd_events(db: Session, c: CrmCompany) -> list[dict]:
    """Hændelser fra Nodd til tidslinjen (gemmes ikke i CRM'et)."""
    org = db.get(Tenant, c.tenant_id) if c.tenant_id else db.get(Partner, c.partner_id) if c.partner_id else None
    if org is None:
        return []
    out = [{"kind": "nodd", "text": f"Oprettet i Nodd som {'firma' if isinstance(org, Tenant) else 'hus'}",
            "at": local_iso(org.created_at)}]
    if org.dpa_accepted_at:
        out.append({"kind": "nodd", "text": f"Databehandleraftale accepteret af {org.dpa_accepted_by}",
                    "at": local_iso(org.dpa_accepted_at)})
    acc = _account(db, c)
    if acc:
        for inv in db.scalars(select(Invoice).where(Invoice.account_id == acc.id, Invoice.status != "draft")
                              .order_by(Invoice.finalized_at.desc()).limit(24)).all():
            out.append({"kind": "nodd", "text": f"Faktura {inv.number} på {billing.kr(inv.total)} inkl. moms "
                        f"({billing.span_text(inv.period_start, inv.period_end)})"
                        + (" er betalt" if inv.status == "paid" else ""),
                        "at": local_iso(inv.finalized_at or inv.created_at)})
    return out


# ---------- ud ----------

def contact_out(x: CrmContact) -> dict:
    return {"id": x.id, "name": x.name, "title": x.title, "email": x.email, "phone": x.phone,
            "is_primary": x.is_primary, "notes": x.notes}


def deal_out(d: CrmDeal, company: str | None = None) -> dict:
    return {"id": d.id, "company_id": d.company_id, "company": company,
            "title": d.title, "stage": d.stage, "stage_text": STAGE_DA.get(d.stage, d.stage),
            "monthly": d.monthly, "once": d.once, "chance": CHANCE.get(d.stage, 0),
            "expected_close": d.expected_close.isoformat() if d.expected_close else None,
            "lost_reason": d.lost_reason, "created_at": local_iso(d.created_at), "closed_at": local_iso(d.closed_at),
            "open": d.stage in OPEN}


def activity_out(a: CrmActivity, company: str | None = None) -> dict:
    return {"id": a.id, "company_id": a.company_id, "company": company,
            "deal_id": a.deal_id, "contact_id": a.contact_id, "kind": a.kind, "kind_text": KIND_DA.get(a.kind, a.kind),
            "text": a.text, "due_date": a.due_date.isoformat() if a.due_date else None,
            "done": a.done_at is not None, "done_at": local_iso(a.done_at), "at": local_iso(a.created_at),
            "overdue": a.kind == "opgave" and a.done_at is None and a.due_date is not None and a.due_date < today()}


def company_row(c: CrmCompany, primary: CrmContact | None, open_deals: int, pipeline: int, next_task: CrmActivity | None,
                mrr_value: int) -> dict:
    return {"id": c.id, "name": c.name, "status": c.status, "status_text": STATUS_DA.get(c.status, c.status),
            "segment": c.segment, "segment_text": SEGMENT_DA.get(c.segment, c.segment), "cvr": c.cvr,
            "contact": contact_out(primary) if primary else None, "open_deals": open_deals, "pipeline": pipeline,
            "next_task": activity_out(next_task) if next_task else None, "mrr": mrr_value,
            "linked": bool(c.tenant_id or c.partner_id), "updated_at": local_iso(c.updated_at)}


def company_out(db: Session, c: CrmCompany) -> dict:
    contacts = db.scalars(select(CrmContact).where(CrmContact.company_id == c.id)
                          .order_by(CrmContact.is_primary.desc(), CrmContact.name)).all()
    deals = db.scalars(select(CrmDeal).where(CrmDeal.company_id == c.id).order_by(CrmDeal.created_at.desc())).all()
    acts = db.scalars(select(CrmActivity).where(CrmActivity.company_id == c.id)
                      .order_by(CrmActivity.created_at.desc()).limit(200)).all()
    timeline = [activity_out(a) for a in acts if a.kind != "opgave"] + nodd_events(db, c)
    timeline.sort(key=lambda x: x["at"] or "", reverse=True)
    tasks = sorted((activity_out(a) for a in acts if a.kind == "opgave"),
                   key=lambda x: (x["done"], x["due_date"] or "9999", x["at"] or ""))
    return {"id": c.id, "name": c.name, "status": c.status, "status_text": STATUS_DA.get(c.status, c.status),
            "segment": c.segment, "cvr": c.cvr, "website": c.website, "phone": c.phone, "email": c.email,
            "address": c.address, "source": c.source, "notes": c.notes, "tenant_id": c.tenant_id,
            "partner_id": c.partner_id, "created_at": local_iso(c.created_at),
            "contacts": [contact_out(x) for x in contacts], "deals": [deal_out(d) for d in deals],
            "tasks": tasks, "timeline": timeline, "linked": linked(db, c)}


def list_companies(db: Session, q: str = "", status: str = "") -> list[dict]:
    stmt = select(CrmCompany)
    if status:
        stmt = stmt.where(CrmCompany.status == status)
    if q:
        like = f"%{q.strip().lower()}%"
        sub = select(CrmContact.company_id).where(or_(func.lower(CrmContact.name).like(like),
                                                      func.lower(CrmContact.email).like(like)))
        stmt = stmt.where(or_(func.lower(CrmCompany.name).like(like), CrmCompany.cvr.like(like), CrmCompany.id.in_(sub)))
    companies = db.scalars(stmt.order_by(func.lower(CrmCompany.name))).all()
    if not companies:
        return []
    ids = select(CrmCompany.id).where(stmt.whereclause) if stmt.whereclause is not None else select(CrmCompany.id)
    primary: dict[int, CrmContact] = {}
    for x in db.scalars(select(CrmContact).where(CrmContact.company_id.in_(ids))
                        .order_by(CrmContact.is_primary.desc(), CrmContact.id)).all():
        primary.setdefault(x.company_id, x)
    deals: dict[int, tuple[int, int]] = {}
    for cid, n, s in db.execute(select(CrmDeal.company_id, func.count(), func.sum(CrmDeal.monthly))
                                .where(CrmDeal.company_id.in_(ids), CrmDeal.stage.in_(OPEN))
                                .group_by(CrmDeal.company_id)).all():
        deals[cid] = (n, int(s or 0))
    tasks: dict[int, CrmActivity] = {}
    for a in db.scalars(select(CrmActivity).where(CrmActivity.company_id.in_(ids), CrmActivity.kind == "opgave",
                                                  CrmActivity.done_at.is_(None))
                        .order_by(CrmActivity.due_date, CrmActivity.id)).all():
        tasks.setdefault(a.company_id, a)
    # Månedlig omsætning for de koblede (alle konti på én gang, så listen ikke laver ét kald pr. firma).
    mrr_by: dict[int, int] = {}
    accs = db.scalars(select(BillingAccount)).all()
    by_t = {a.tenant_id: a for a in accs if a.tenant_id}
    by_p = {a.partner_id: a for a in accs if a.partner_id}
    for c in companies:
        acc = by_t.get(c.tenant_id) if c.tenant_id else by_p.get(c.partner_id) if c.partner_id else None
        mrr_by[c.id] = mrr(db, acc, today()) if acc else 0
    return [company_row(c, primary.get(c.id), *deals.get(c.id, (0, 0)), tasks.get(c.id), mrr_by[c.id])
            for c in companies]


def overview(db: Session) -> dict:
    t = today()
    open_tasks = db.scalars(select(CrmActivity).where(CrmActivity.kind == "opgave", CrmActivity.done_at.is_(None))
                            .order_by(CrmActivity.due_date, CrmActivity.id)).all()
    names = dict(db.execute(select(CrmCompany.id, CrmCompany.name)).all())
    due = [activity_out(a, names.get(a.company_id)) for a in open_tasks if a.due_date is not None and a.due_date <= t]
    later = [activity_out(a, names.get(a.company_id)) for a in open_tasks if a.due_date is None or a.due_date > t][:10]
    stages = {k: {"label": v, "count": 0, "monthly": 0, "once": 0} for k, v in STAGES}
    weighted = 0
    for stage, n, m, o in db.execute(select(CrmDeal.stage, func.count(), func.sum(CrmDeal.monthly), func.sum(CrmDeal.once))
                                     .group_by(CrmDeal.stage)).all():
        if stage in stages:
            stages[stage].update(count=n, monthly=int(m or 0), once=int(o or 0))
            if stage in OPEN:
                weighted += round(int(m or 0) * CHANCE[stage] / 100)
    month_start = datetime(t.year, t.month, 1)
    won = db.execute(select(func.count(), func.sum(CrmDeal.monthly)).where(CrmDeal.stage == "vundet",
                                                                          CrmDeal.closed_at >= month_start)).one()
    counts = dict(db.execute(select(CrmCompany.status, func.count()).group_by(CrmCompany.status)).all())
    demo_t = set(db.scalars(select(Tenant.id).where(Tenant.is_demo == true())).all())
    demo_p = set(db.scalars(select(Partner.id).where(Partner.is_demo == true())).all())
    total_mrr = sum(mrr(db, acc, t) for acc in db.scalars(select(BillingAccount)).all()
                    if acc.tenant_id not in demo_t and acc.partner_id not in demo_p)  # demo tæller ikke
    recent = db.scalars(select(CrmActivity).where(CrmActivity.kind != "opgave")
                        .order_by(CrmActivity.created_at.desc()).limit(8)).all()
    unlinked = db.scalar(select(func.count()).select_from(Tenant).where(
        Tenant.partner_id.is_(None), Tenant.is_demo == false(), ~Tenant.id.in_(select(CrmCompany.tenant_id).where(CrmCompany.tenant_id.isnot(None))))) + \
        db.scalar(select(func.count()).select_from(Partner).where(
            Partner.is_demo == false(), ~Partner.id.in_(select(CrmCompany.partner_id).where(CrmCompany.partner_id.isnot(None)))))
    return {"today": t.isoformat(), "due": due, "later": later, "stages": stages, "weighted": weighted,
            "open_monthly": sum(stages[k]["monthly"] for k in OPEN),
            "won_month": {"count": won[0] or 0, "monthly": int(won[1] or 0)},
            "counts": {k: int(counts.get(k, 0)) for k in STATUS_DA}, "mrr": total_mrr,
            "recent": [activity_out(a, names.get(a.company_id)) for a in recent], "unlinked": int(unlinked or 0)}


def pipeline(db: Session) -> list[dict]:
    """Åbne salgsmuligheder og dem, der er lukket de sidste 60 dage."""
    since = utcnow() - timedelta(days=60)
    deals = db.scalars(select(CrmDeal).where(or_(CrmDeal.stage.in_(OPEN), CrmDeal.closed_at >= since))
                       .order_by(CrmDeal.expected_close, CrmDeal.created_at)).all()
    names = dict(db.execute(select(CrmCompany.id, CrmCompany.name)).all())
    return [deal_out(d, names.get(d.company_id)) for d in deals]


# ---------- ændringer ----------

def log_system(db: Session, c: CrmCompany, text: str, deal_id: int | None = None) -> None:
    db.add(CrmActivity(company_id=c.id, deal_id=deal_id, kind="system", text=text))


def set_stage(db: Session, c: CrmCompany, d: CrmDeal, stage: str) -> None:
    if stage == d.stage:
        return
    log_system(db, c, f"{d.title}: {STAGE_DA.get(d.stage, d.stage)} → {STAGE_DA.get(stage, stage)}", d.id)
    d.stage = stage
    d.closed_at = utcnow() if stage in ("vundet", "tabt") else None
    if stage == "vundet" and c.status != "kunde":
        log_system(db, c, f"Status: {STATUS_DA.get(c.status, c.status)} → Kunde")
        c.status = "kunde"


def sync_from_nodd(db: Session) -> int:
    """Opret CRM-firmaer for de firmaer og huse i Nodd, der ikke er i CRM'et endnu. Firmaer under et hus hører med
    til huset og oprettes ikke for sig."""
    have_t = set(db.scalars(select(CrmCompany.tenant_id).where(CrmCompany.tenant_id.isnot(None))).all())
    have_p = set(db.scalars(select(CrmCompany.partner_id).where(CrmCompany.partner_id.isnot(None))).all())
    accs = {a.tenant_id or -a.partner_id: a for a in db.scalars(select(BillingAccount)).all()}
    n = 0
    for p in db.scalars(select(Partner).where(Partner.is_demo == false()).order_by(Partner.name)).all():
        if p.id not in have_p:
            acc = accs.get(-p.id)
            c = CrmCompany(name=p.name, status="kunde" if p.active else "tidligere", segment="kontorhotel",
                           partner_id=p.id, cvr=acc.cvr if acc else "", email=acc.invoice_email if acc else "",
                           source="Nodd")
            db.add(c)
            n += 1
    for t in db.scalars(select(Tenant).where(Tenant.partner_id.is_(None), Tenant.is_demo == false()).order_by(Tenant.name)).all():
        if t.id not in have_t:
            acc = accs.get(t.id)
            db.add(CrmCompany(name=t.name, status="kunde" if t.active else "tidligere", segment="firma",
                              tenant_id=t.id, cvr=acc.cvr if acc else "", email=acc.invoice_email if acc else "",
                              source="Nodd"))
            n += 1
    db.flush()
    return n


def unlink_tenant(db: Session, tid: int) -> None:
    """Kaldes, når et firma slettes i Nodd. CRM-firmaet bliver (som tidligere kunde)."""
    for c in db.scalars(select(CrmCompany).where(CrmCompany.tenant_id == tid)).all():
        c.tenant_id = None
        if c.status == "kunde":
            c.status = "tidligere"
        log_system(db, c, "Firmaet er slettet i Nodd")


def unlink_partner(db: Session, pid: int) -> None:
    for c in db.scalars(select(CrmCompany).where(CrmCompany.partner_id == pid)).all():
        c.partner_id = None
        if c.status == "kunde":
            c.status = "tidligere"
        log_system(db, c, "Huset er slettet i Nodd")


def delete_deal(db: Session, d: CrmDeal) -> None:
    db.query(CrmActivity).filter(CrmActivity.deal_id == d.id).update({CrmActivity.deal_id: None})
    db.delete(d)


def delete_contact(db: Session, x: CrmContact) -> None:
    db.query(CrmActivity).filter(CrmActivity.contact_id == x.id).update({CrmActivity.contact_id: None})
    db.delete(x)


# ---------- CSV ----------

def companies_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Firma", "Status", "Type", "CVR", "Kontakt", "Titel", "E-mail", "Telefon", "Åbne salgsmuligheder",
                "Pipeline pr. md. (kr.)", "Omsætning pr. md. (kr.)", "Næste opgave", "Dato"])
    for r in rows:
        ct, t = r["contact"] or {}, r["next_task"] or {}
        w.writerow([r["name"], r["status_text"], r["segment_text"], r["cvr"], ct.get("name", ""), ct.get("title", ""),
                    ct.get("email", ""), ct.get("phone", ""), r["open_deals"], f"{r['pipeline'] / 100:.2f}".replace(".", ","),
                    f"{r['mrr'] / 100:.2f}".replace(".", ","), t.get("text", ""), t.get("due_date") or ""])
    return "﻿" + buf.getvalue()  # BOM, så Excel læser æøå rigtigt


# ---------- morgenmail ----------

def digest_text(db: Session) -> tuple[str, str] | None:
    """(emne, tekst) med dagens og forfaldne opgaver, eller None, hvis der ikke er nogen."""
    ov = overview(db)
    if not ov["due"]:
        return None
    lines = [f"God morgen. Du har {len(ov['due'])} opfølgning{'er' if len(ov['due']) != 1 else ''} i dag:", ""]
    for a in ov["due"]:
        when = "i dag" if a["due_date"] == ov["today"] else f"forfalden ({date.fromisoformat(a['due_date']):%d.%m})"
        lines.append(f"- {a['company']}: {a['text']} ({when})")
    lines += ["", f"Åben pipeline: {billing.kr(ov['open_monthly'])} pr. md. (vægtet {billing.kr(ov['weighted'])}).",
              f"Omsætning nu: {billing.kr(ov['mrr'])} pr. md.", "",
              f"Åbn CRM: {settings.public_url.rstrip('/')}/admin#crm"]
    return f"Nodd CRM: {len(ov['due'])} opfølgning{'er' if len(ov['due']) != 1 else ''} i dag", "\n".join(lines)


def send_digest(db_factory, day: date | None = None) -> str:
    """Send morgenmailen én gang pr. dag. Returnerer status (sendt | test | tom | fejl | allerede)."""
    day = day or today()
    to = [x.strip() for x in (settings.crm_email or settings.ops_email).split(",") if x.strip()]
    if not to:
        return "ingen modtager"
    with db_factory() as db:
        run = ReportRun(scope="crm", scope_id=int(day.strftime("%Y%m%d")), month=day.strftime("%Y-%m"),
                        recipients=", ".join(to))
        db.add(run)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return "allerede"
        msg = digest_text(db)
        if msg is None:
            run.status = "tom"
        elif settings.notify_mode != "live":
            run.status = "test"
        else:
            from .notify import send_email
            try:
                for addr in to:
                    send_email(addr, msg[0], msg[1], "Nodd CRM")
                run.status = "sendt"
            except Exception as e:  # noqa: BLE001
                run.status, run.error = "fejl", str(e)[:500]
        db.commit()
        return run.status


def start_digest(db_factory) -> None:
    if not settings.crm_digest:
        return

    def loop():
        time.sleep(90)
        while True:
            now = datetime.now(TZ)
            try:
                if now.hour * 60 + now.minute >= 7 * 60 + 30:
                    send_digest(db_factory)
            except Exception:  # noqa: BLE001 - planlæggeren må aldrig dø
                log.exception("CRM-morgenmail fejlede")
            nxt = datetime(now.year, now.month, now.day, 7, 30, tzinfo=TZ)
            if now >= nxt:
                nxt += timedelta(days=1)
            time.sleep(max(60, min((nxt - datetime.now(TZ)).total_seconds(), 6 * 3600)))

    threading.Thread(target=loop, name="crm-morgenmail", daemon=True).start()

