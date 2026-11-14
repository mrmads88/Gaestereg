"""Overblik og månedsrapport (fase 7).

build(): tallene for et firma eller et hus i en periode (måned, kvartal eller år) med udvikling mod forrige periode
og 13 måneders tendens. Ingen navne på gæster og ingen mødetitler, så rapporten kan vises på et direktionsmøde.

Månedsrapporten sendes den 1. i måneden kl. 07 til report_email på firmaer og huse med modulet "reports".
Planlæggeren er en tråd, der sover til næste udsendelse og kun rører databasen ved opstart og den 1. i måneden,
så den gratis database kan sove. report_runs sikrer, at hver rapport kun sendes én gang, også efter genstart.
"""
import csv
import html
import io
import logging
import threading
import time
from collections import defaultdict
from datetime import date, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import modules
from .billing import add_months, kr
from .config import settings
from .media import media_url
from .models import Booking, CateringLine, CateringOrder, Kitchen, Partner, ReportRun, Room, Tenant, VisitStat
from .notify import send_email, valid_email
from .rooms import day_bounds
from .timeutil import TZ, to_local

log = logging.getLogger("gaestereg.reports")
MONTHS_DA = ["januar", "februar", "marts", "april", "maj", "juni", "juli", "august", "september", "oktober",
             "november", "december"]
MONTHS_SHORT = ["jan", "feb", "mar", "apr", "maj", "jun", "jul", "aug", "sep", "okt", "nov", "dec"]
WEEKDAYS = ["Man", "Tir", "Ons", "Tor", "Fre", "Lør", "Søn"]
WORK_HOURS = 9  # 08–17 tæller som åbningstid for belægning


# ---------- perioder ----------

def parse_period(key: str | None, today: date | None = None) -> tuple[str, date, date, str]:
    """'2026-11' | '2026-Q4' | '2026' -> (type, start, slut eksklusiv, nøgle). Tom = sidste hele måned."""
    today = today or datetime.now(TZ).date()
    if not key:
        last = add_months(date(today.year, today.month, 1), -1)
        key = f"{last.year}-{last.month:02d}"
    try:
        if len(key) == 7 and key[4:6] == "-Q":
            q = int(key[6])
            if not 1 <= q <= 4:
                raise ValueError
            s = date(int(key[:4]), 3 * (q - 1) + 1, 1)
            return "quarter", s, add_months(s, 3), key
        if len(key) == 7 and key[4] == "-":
            s = date(int(key[:4]), int(key[5:]), 1)
            return "month", s, add_months(s, 1), key
        if len(key) == 4:
            s = date(int(key), 1, 1)
            return "year", s, add_months(s, 12), key
    except ValueError:
        pass
    raise HTTPException(422, "Ugyldig periode. Brug fx 2026-11, 2026-Q4 eller 2026")


def period_key(kind: str, start: date) -> str:
    if kind == "year":
        return str(start.year)
    if kind == "quarter":
        return f"{start.year}-Q{(start.month - 1) // 3 + 1}"
    return f"{start.year}-{start.month:02d}"


def period_label(kind: str, start: date) -> str:
    if kind == "year":
        return str(start.year)
    if kind == "quarter":
        return f"{(start.month - 1) // 3 + 1}. kvartal {start.year}"
    return f"{MONTHS_DA[start.month - 1]} {start.year}"


def months_between(a: date, b: date) -> list[str]:
    out, cur = [], date(a.year, a.month, 1)
    while cur < b:
        out.append(f"{cur.year}-{cur.month:02d}")
        cur = add_months(cur, 1)
    return out


def utc_bounds(a: date, b: date) -> tuple[datetime, datetime]:
    return day_bounds(a.isoformat())[0], day_bounds(b.isoformat())[0]


def workdays(a: date, b: date) -> int:
    return sum(1 for i in range((b - a).days) if (a + timedelta(days=i)).weekday() < 5)


def delta(cur: float, prev: float) -> float | None:
    """Ændring i procent mod forrige periode. None, når der intet var at sammenligne med."""
    if not prev:
        return None
    return round(100 * (cur - prev) / prev, 1)


# ---------- omfang ----------

class Scope:
    """Hvem rapporten handler om: ét firma eller et hus med alle dets firmaer."""

    def __init__(self, db: Session, tenant: Tenant | None = None, partner: Partner | None = None):
        self.db, self.tenant, self.partner = db, tenant, partner
        self.kind = "tenant" if tenant is not None else "partner"
        self.name = tenant.name if tenant is not None else partner.name
        if tenant is not None:
            self.tenant_ids = select(Tenant.id).where(Tenant.id == tenant.id)
            self.firms = [tenant]
            self.rooms_owned = select(Room.id).where(Room.tenant_id == tenant.id)
            self.kitchens = select(Kitchen.id).where(Kitchen.tenant_id == tenant.id)
            brand = tenant
        else:
            self.tenant_ids = select(Tenant.id).where(Tenant.partner_id == partner.id)
            self.firms = list(db.scalars(select(Tenant).where(Tenant.partner_id == partner.id).order_by(Tenant.name)))
            self.rooms_owned = select(Room.id).where(or_(Room.partner_id == partner.id, Room.tenant_id.in_(self.tenant_ids)))
            self.kitchens = select(Kitchen.id).where(or_(Kitchen.partner_id == partner.id,
                                                         Kitchen.tenant_id.in_(self.tenant_ids)))
            brand = next((t for t in self.firms if t.house_screen), None)
        self.brand = {"name": self.name, "color": brand.color if brand else "#12352e",
                      "logo_url": media_url(brand.logo_path) if brand else ""}

    def has(self, m: str) -> bool:
        return modules.tenant_has(self.tenant, m) if self.tenant is not None else modules.partner_has(self.partner, m)


# ---------- tallene ----------

def _visits(sc: Scope, months: list[str]) -> dict[tuple[int, str, str], int]:
    rows = sc.db.scalars(select(VisitStat).where(VisitStat.tenant_id.in_(sc.tenant_ids), VisitStat.month.in_(months)))
    return {(r.tenant_id, r.month, r.kind): r.count for r in rows}


def _bookings(sc: Scope, a: datetime, b: datetime) -> list[Booking]:
    """Bookinger i perioden: firmaets egne (også i husets lokaler) eller alt i husets og firmaernes lokaler."""
    cond = Booking.tenant_id.in_(sc.tenant_ids)
    if sc.kind == "partner":
        cond = or_(cond, Booking.room_id.in_(sc.rooms_owned))
    return list(sc.db.scalars(select(Booking).where(cond, Booking.status == "confirmed", Booking.start_at >= a,
                                                    Booking.start_at < b)))


def _order_cond(sc: Scope, a: datetime, b: datetime):
    cond = CateringOrder.tenant_id.in_(sc.tenant_ids)
    if sc.kind == "partner":
        cond = or_(cond, CateringOrder.kitchen_id.in_(sc.kitchens))
    return (cond, CateringOrder.status != "cancelled", CateringOrder.deliver_at >= a, CateringOrder.deliver_at < b)


def _orders(sc: Scope, a: datetime, b: datetime) -> list[CateringOrder]:
    return list(sc.db.scalars(select(CateringOrder).where(*_order_cond(sc, a, b))))


def _hours(b: Booking, a: datetime | None = None, z: datetime | None = None) -> float:
    s, e = max(b.start_at, a) if a else b.start_at, min(b.end_at, z) if z else b.end_at
    return max(0.0, (e - s).total_seconds() / 3600)


def _month_of(dt: datetime) -> str:
    d = to_local(dt)
    return f"{d.year}-{d.month:02d}"


def build(db: Session, tenant: Tenant | None = None, partner: Partner | None = None, period: str | None = None) -> dict:
    sc = Scope(db, tenant, partner)
    kind, ps, pe, key = parse_period(period)
    n = len(months_between(ps, pe))
    prev_s = add_months(ps, -n)
    trend_end = pe
    trend_start = add_months(trend_end, -max(13, n))
    trend_months = months_between(trend_start, trend_end)
    cur_months, prev_months = months_between(ps, pe), months_between(prev_s, ps)

    stats = _visits(sc, sorted(set(trend_months) | set(prev_months)))
    firm_ids = [t.id for t in sc.firms]

    def visits(months, kind_, tid=None):
        return sum(v for (t, m, k), v in stats.items() if m in months and k == kind_ and (tid is None or t == tid))

    guests, deliveries = visits(cur_months, "guest"), visits(cur_months, "delivery")
    guests_prev, deliveries_prev = visits(prev_months, "guest"), visits(prev_months, "delivery")
    month_labels = [{"key": m, "label": MONTHS_SHORT[int(m[5:]) - 1] + (" " + m[2:4] if m.endswith("-01") else ""),
                     "current": m in cur_months} for m in trend_months]

    a, b = utc_bounds(ps, pe)
    pa, pb = utc_bounds(prev_s, ps)
    out = {
        "scope": {"kind": sc.kind, **sc.brand},
        "period": {"type": kind, "key": key, "label": period_label(kind, ps),
                   "prev_label": period_label(kind, prev_s), "start": ps.isoformat(), "end": (pe - timedelta(days=1)).isoformat(),
                   "prev_key": period_key(kind, prev_s), "next_key": period_key(kind, pe),
                   "is_current": ps <= datetime.now(TZ).date() < pe},
        "generated": datetime.now(TZ).strftime("%d.%m.%Y kl. %H:%M"),
        "months": month_labels,
        "guests": {"value": guests, "prev": guests_prev, "delta": delta(guests, guests_prev),
                   "trend": [visits([m], "guest") for m in trend_months]},
        "deliveries": {"value": deliveries, "prev": deliveries_prev, "delta": delta(deliveries, deliveries_prev),
                       "trend": [visits([m], "delivery") for m in trend_months]},
        "rooms": None, "catering": None, "firms": None,
    }

    # Mødelokaler
    bks = _bookings(sc, a, b)
    if sc.has("rooms") or bks:
        prev_bks = _bookings(sc, pa, pb)
        trend_bks = _bookings(sc, *utc_bounds(trend_start, trend_end))
        per_month = defaultdict(int)
        for bk in trend_bks:
            per_month[_month_of(bk.start_at)] += 1
        owned = list(db.scalars(select(Room).where(Room.id.in_(sc.rooms_owned)).order_by(Room.sort_order, Room.name)))
        capacity_h = workdays(ps, pe) * WORK_HOURS
        room_hours = defaultdict(float)
        room_count = defaultdict(int)
        owned_ids = {r.id for r in owned}
        if owned_ids:
            for bk in db.scalars(select(Booking).where(Booking.room_id.in_(sc.rooms_owned), Booking.status == "confirmed",
                                                       Booking.start_at < b, Booking.end_at > a)):
                room_hours[bk.room_id] += _hours(bk, a, b)
                room_count[bk.room_id] += 1
        per_room = [{"name": r.name, "bookings": room_count[r.id], "hours": round(room_hours[r.id], 1),
                     "utilization": round(100 * room_hours[r.id] / capacity_h, 1) if capacity_h else 0}
                    for r in owned]
        util = round(sum(x["utilization"] for x in per_room) / len(per_room), 1) if per_room else None
        weekday = [0] * 7
        for bk in bks:
            weekday[to_local(bk.start_at).weekday()] += 1
        hours = round(sum(_hours(x) for x in bks), 1)
        att = [x.attendees for x in bks if x.attendees]
        out["rooms"] = {
            "bookings": {"value": len(bks), "prev": len(prev_bks), "delta": delta(len(bks), len(prev_bks)),
                         "trend": [per_month[m] for m in trend_months]},
            "hours": hours, "avg_attendees": round(sum(att) / len(att), 1) if att else None,
            "on_screen": sum(1 for x in bks if x.source == "screen"),
            "utilization": util, "per_room": sorted(per_room, key=lambda x: -x["utilization"]),
            "weekdays": [{"label": WEEKDAYS[i], "value": weekday[i]} for i in range(7)],
        }

    # Forplejning
    ords = _orders(sc, a, b)
    if sc.has("catering") or ords:
        prev_ords = _orders(sc, pa, pb)
        trend_ords = _orders(sc, *utc_bounds(trend_start, trend_end))
        per_month = defaultdict(int)
        for o in trend_ords:
            per_month[_month_of(o.deliver_at)] += o.total
        items = defaultdict(lambda: [0, 0])
        if ords:
            q = select(CateringLine).where(CateringLine.order_id.in_(select(CateringOrder.id).where(*_order_cond(sc, a, b))))
            for ln in db.scalars(q):
                items[ln.name][0] += ln.qty
                items[ln.name][1] += ln.qty * ln.unit_price
        groups = defaultdict(int)
        names = {t.id: t.name for t in sc.firms}
        for o in ords:
            label = (o.cost_center or "Uden omkostningssted") if sc.kind == "tenant" else names.get(o.tenant_id, "Andre")
            groups[label] += o.total
        revenue, prev_rev = sum(o.total for o in ords), sum(o.total for o in prev_ords)
        out["catering"] = {
            "revenue": {"value": revenue, "text": kr(revenue), "prev": prev_rev, "delta": delta(revenue, prev_rev),
                        "trend": [per_month[m] for m in trend_months]},
            "orders": len(ords), "avg_text": kr(round(revenue / len(ords))) if ords else "",
            "top_items": [{"name": k, "qty": v[0], "amount": v[1], "amount_text": kr(v[1])}
                          for k, v in sorted(items.items(), key=lambda kv: -kv[1][1])[:8]],
            "groups_title": "Pr. omkostningssted" if sc.kind == "tenant" else "Pr. firma",
            "groups": [{"name": k, "amount": v, "amount_text": kr(v)} for k, v in sorted(groups.items(), key=lambda kv: -kv[1])],
        }

    # Pr. firma i huset
    if sc.kind == "partner":
        bk_by = defaultdict(int)
        for x in bks:
            bk_by[x.tenant_id] += 1
        food_by = defaultdict(int)
        for o in ords:
            food_by[o.tenant_id] += o.total
        out["firms"] = sorted([{"name": t.name, "guests": visits(cur_months, "guest", t.id),
                                "deliveries": visits(cur_months, "delivery", t.id), "bookings": bk_by[t.id],
                                "catering": food_by[t.id], "catering_text": kr(food_by[t.id])} for t in sc.firms
                               # husets egen reception vises kun, hvis den selv har aktivitet
                               if not (t.house_screen and not visits(cur_months, "guest", t.id) and not bk_by[t.id]
                                       and not food_by[t.id])],
                              key=lambda r: (-r["guests"], r["name"]))
    return out


# ---------- CSV ----------

def to_csv(r: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    p = r["period"]
    w.writerow(["Overblik", r["scope"]["name"], p["label"]])
    w.writerow([])
    w.writerow(["Nøgletal", p["label"], p["prev_label"], "Ændring %"])
    pct = lambda d: "" if d is None else str(d).replace(".", ",")  # noqa: E731
    w.writerow(["Gæster", r["guests"]["value"], r["guests"]["prev"], pct(r["guests"]["delta"])])
    w.writerow(["Pakker", r["deliveries"]["value"], r["deliveries"]["prev"], pct(r["deliveries"]["delta"])])
    if r["rooms"]:
        x = r["rooms"]
        w.writerow(["Mødebookinger", x["bookings"]["value"], x["bookings"]["prev"], pct(x["bookings"]["delta"])])
        w.writerow(["Bookede timer", str(x["hours"]).replace(".", ",")])
        if x["utilization"] is not None:
            w.writerow(["Gennemsnitlig belægning %", str(x["utilization"]).replace(".", ",")])
    if r["catering"]:
        x = r["catering"]
        fmt = lambda o: f"{o / 100:.2f}".replace(".", ",")  # noqa: E731
        w.writerow(["Forplejning kr.", fmt(x["revenue"]["value"]), fmt(x["revenue"]["prev"]), pct(x["revenue"]["delta"])])
        w.writerow(["Bestillinger", x["orders"]])
    w.writerow([])
    w.writerow(["Måned", "Gæster", "Pakker"] + (["Bookinger"] if r["rooms"] else []) + (["Forplejning kr."] if r["catering"] else []))
    for i, m in enumerate(r["months"]):
        row = [m["key"], r["guests"]["trend"][i], r["deliveries"]["trend"][i]]
        if r["rooms"]:
            row.append(r["rooms"]["bookings"]["trend"][i])
        if r["catering"]:
            row.append(f"{r['catering']['revenue']['trend'][i] / 100:.2f}".replace(".", ","))
        w.writerow(row)
    if r["rooms"] and r["rooms"]["per_room"]:
        w.writerow([])
        w.writerow(["Lokale", "Bookinger", "Timer", "Belægning %"])
        for x in r["rooms"]["per_room"]:
            w.writerow([x["name"], x["bookings"], str(x["hours"]).replace(".", ","), str(x["utilization"]).replace(".", ",")])
    if r["firms"]:
        w.writerow([])
        w.writerow(["Firma", "Gæster", "Pakker", "Bookinger", "Forplejning kr."])
        for x in r["firms"]:
            w.writerow([x["name"], x["guests"], x["deliveries"], x["bookings"], f"{x['catering'] / 100:.2f}".replace(".", ",")])
    return "﻿" + buf.getvalue()


# ---------- mail ----------

def _delta_html(d: float | None) -> str:
    if d is None:
        return '<span style="color:#5d6470">ingen sammenligning</span>'
    arrow, color = ("▲", "#127a4c") if d > 0 else ("▼", "#b42318") if d < 0 else ("■", "#5d6470")
    return f'<span style="color:{color}">{arrow} {str(abs(d)).replace(".", ",")} %</span>'


def report_link(sc_kind: str, sc_id: int, key: str) -> str:
    q = "tenant_id" if sc_kind == "tenant" else "partner_id"
    return f"{settings.public_url.rstrip('/')}/admin/rapport?{q}={sc_id}&period={key}"


def mail_for(r: dict, link: str) -> tuple[str, str, str]:
    """(emne, tekst, html). Simpel tabel-HTML, som ser ordentlig ud i Outlook og Gmail."""
    p, name = r["period"], r["scope"]["name"]
    tiles = [("Gæster", f"{r['guests']['value']:,}".replace(",", "."), r["guests"]["delta"]),
             ("Pakker", f"{r['deliveries']['value']:,}".replace(",", "."), r["deliveries"]["delta"])]
    if r["rooms"]:
        tiles.append(("Mødebookinger", str(r["rooms"]["bookings"]["value"]), r["rooms"]["bookings"]["delta"]))
    if r["catering"]:
        whole = f"{round(r['catering']['revenue']['value'] / 100):,}".replace(",", ".") + " kr."
        tiles.append(("Forplejning", whole, r["catering"]["revenue"]["delta"]))
    subject = f"Overblik for {p['label']} · {name}"
    text = "\n".join([f"Overblik for {name}, {p['label']}", ""] +
                     [f"{t}: {v}" + ("" if d is None else f" ({'+' if d > 0 else ''}{str(d).replace('.', ',')} % mod {p['prev_label']})")
                      for t, v, d in tiles] + ["", f"Se hele overblikket: {link}", "", "Tallene ligger også i den vedhæftede CSV-fil."])
    color = html.escape(r["scope"]["color"] or "#12352e")
    cells = "".join(
        f'<td style="padding:14px 16px;border:1px solid #e2e4e0;border-radius:12px;background:#fff;width:{100 // len(tiles)}%">'
        f'<div style="font-size:13px;color:#5d6470">{html.escape(t)}</div>'
        f'<div style="font-size:26px;font-weight:700;color:#14171d;margin:4px 0">{html.escape(v)}</div>'
        f'<div style="font-size:12px">{_delta_html(d)} mod {html.escape(p["prev_label"])}</div></td>' for t, v, d in tiles)
    extra = ""
    if r["rooms"] and r["rooms"]["per_room"]:
        rows = "".join(f'<tr><td style="padding:6px 0;border-top:1px solid #eceeea">{html.escape(x["name"])}</td>'
                       f'<td style="padding:6px 0;border-top:1px solid #eceeea;text-align:right">{x["bookings"]} bookinger</td>'
                       f'<td style="padding:6px 0;border-top:1px solid #eceeea;text-align:right">{str(x["utilization"]).replace(".", ",")} %</td></tr>'
                       for x in r["rooms"]["per_room"][:6])
        extra += f'<h3 style="font-size:15px;margin:24px 0 6px">Belægning pr. lokale</h3><table width="100%" style="font-size:14px;border-collapse:collapse">{rows}</table>'
    if r["catering"] and r["catering"]["top_items"]:
        rows = "".join(f'<tr><td style="padding:6px 0;border-top:1px solid #eceeea">{html.escape(x["name"])}</td>'
                       f'<td style="padding:6px 0;border-top:1px solid #eceeea;text-align:right">{x["qty"]} stk.</td>'
                       f'<td style="padding:6px 0;border-top:1px solid #eceeea;text-align:right">{html.escape(x["amount_text"])}</td></tr>'
                       for x in r["catering"]["top_items"][:5])
        extra += f'<h3 style="font-size:15px;margin:24px 0 6px">Mest bestilte forplejning</h3><table width="100%" style="font-size:14px;border-collapse:collapse">{rows}</table>'
    body = f"""<div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;background:#f4f5f2;padding:24px">
<div style="max-width:640px;margin:0 auto">
<div style="background:{color};color:#fff;border-radius:16px 16px 0 0;padding:20px 24px">
<div style="font-size:13px;opacity:.85">Overblik</div><div style="font-size:24px;font-weight:700">{html.escape(name)}</div>
<div style="font-size:15px;opacity:.9">{html.escape(p['label'][0].upper() + p['label'][1:])}</div></div>
<div style="background:#f9faf8;border:1px solid #e2e4e0;border-top:0;border-radius:0 0 16px 16px;padding:20px 24px">
<table width="100%" cellspacing="8" style="border-collapse:separate"><tr>{cells}</tr></table>
{extra}
<p style="margin:24px 0 8px"><a href="{html.escape(link)}" style="background:{color};color:#fff;text-decoration:none;padding:12px 20px;border-radius:999px;font-weight:700;display:inline-block">Se hele overblikket</a></p>
<p style="font-size:12px;color:#5d6470">Tallene ligger også i den vedhæftede CSV-fil, som kan åbnes i Excel. Rapporten indeholder ingen navne på gæster og ingen mødetitler.</p>
</div></div></div>"""
    return subject, text, body


def recipients(raw: str) -> list[str]:
    return [x.strip() for x in (raw or "").split(",") if valid_email(x.strip())]


def deliver_report(r: dict, to: list[str], link: str) -> tuple[str, str]:
    """Send rapporten. Returnerer (status, fejl). I testtilstand sendes intet."""
    if settings.notify_mode != "live":
        return "test", ""
    subject, text, body = mail_for(r, link)
    attach = [(f"overblik-{r['period']['key']}.csv", to_csv(r).encode("utf-8"), "text/csv")]
    try:
        for addr in to:
            send_email(addr, subject, text, r["scope"]["name"], html=body, attachments=attach)
        return "sendt", ""
    except Exception as e:  # noqa: BLE001 - fejlen gemmes på rækken
        log.warning("Månedsrapport fejlede: %s", e)
        return "fejl", str(e)[:500]


def send_due(db_factory, today: date | None = None) -> int:
    """Send sidste måneds rapport til alle, der har bedt om den og har modulet. Returnerer antal sendte."""
    today = today or datetime.now(TZ).date()
    last = add_months(date(today.year, today.month, 1), -1)
    key = f"{last.year}-{last.month:02d}"
    sent = 0
    with db_factory() as db:
        targets = [("tenant", t) for t in db.scalars(select(Tenant).where(Tenant.report_email != "")).all()] + \
                  [("partner", p) for p in db.scalars(select(Partner).where(Partner.report_email != "")).all()]
        for kind, obj in targets:
            to = recipients(obj.report_email)
            ok = modules.tenant_has(obj, "reports") if kind == "tenant" else modules.partner_has(obj, "reports")
            if not to or not ok or (kind == "tenant" and not obj.active):
                continue
            run = ReportRun(scope=kind, scope_id=obj.id, month=key, recipients=", ".join(to))
            db.add(run)
            try:
                db.commit()  # den unikke nøgle forhindrer, at samme rapport sendes to gange
            except IntegrityError:
                db.rollback()
                continue
            r = build(db, tenant=obj if kind == "tenant" else None, partner=obj if kind == "partner" else None, period=key)
            run.status, run.error = deliver_report(r, to, report_link(kind, obj.id, key))
            db.commit()
            sent += 1
    return sent


# ---------- planlægger ----------

def _next_run(now: datetime) -> datetime:
    first = datetime(now.year, now.month, 1, 7, 0, tzinfo=TZ)
    return first if now < first else datetime(*add_months(first.date(), 1).timetuple()[:3], 7, 0, tzinfo=TZ)


def start_scheduler(db_factory) -> None:
    """Send manglende rapporter ved opstart (efter et minut) og derefter den 1. i måneden kl. 07."""
    if not settings.report_scheduler:
        return

    def loop():
        time.sleep(60)
        while True:
            try:
                now = datetime.now(TZ)
                if now >= datetime(now.year, now.month, 1, 7, 0, tzinfo=TZ):
                    n = send_due(db_factory)
                    if n:
                        log.info("Sendte %s månedsrapporter", n)
            except Exception:  # noqa: BLE001 - planlæggeren må aldrig dø
                log.exception("Månedsrapporter fejlede")
            wait = (_next_run(datetime.now(TZ)) - datetime.now(TZ)).total_seconds()
            time.sleep(max(60, min(wait, 6 * 3600)))  # vågn mindst hver 6. time for at tjekke uret (ingen databasekald)

    threading.Thread(target=loop, name="maanedsrapporter", daemon=True).start()


def runs_for(db: Session, kind: str, oid: int) -> list[dict]:
    rows = db.scalars(select(ReportRun).where(ReportRun.scope == kind, ReportRun.scope_id == oid)
                      .order_by(ReportRun.month.desc()).limit(12))
    status_da = {"sendt": "Sendt", "test": "Testtilstand (ikke sendt)", "fejl": "Fejl", "venter": "Venter"}
    return [{"month": r.month, "label": period_label("month", date(int(r.month[:4]), int(r.month[5:]), 1)),
             "status": r.status, "status_text": status_da.get(r.status, r.status), "recipients": r.recipients,
             "error": r.error, "at": to_local(r.created_at).strftime("%d.%m.%Y %H:%M")} for r in rows]

