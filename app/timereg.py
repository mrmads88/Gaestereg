"""Tidsregistrering for medarbejdere (modul "time").

Siden 1. juli 2024 skal arbejdsgivere i Danmark registrere medarbejdernes daglige arbejdstid i et objektivt,
pålideligt og tilgængeligt system, og registreringerne skal gemmes i 5 år. Derfor:
- Medarbejdere stempler selv ind og ud på receptionsskærmen (med PIN) eller på telefonen (personligt link /t/<token>),
  hvor de også kan se deres egne registreringer.
- Rettelser i admin gemmes i edit_log (hvem, hvornår, fra og til). Godkendte uger er låst, til de genåbnes.
- Poster gemmes i 5 år (plus en måned), også efter personen er slettet. Ældre poster slettes ved opstart.

En post tilhører den lokale dag, den starter på. En stempling, der har været åben i mere end 16 timer, regnes som
glemt: næste stempling starter en ny post, og den gamle står som "mangler udstempling" i admin.
"""
import csv
import io
import json
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .auth import hash_password, verify_password
from .models import Host, Tenant, TimeEntry, utcnow
from .timeutil import TZ, local_iso, to_local

STALE_HOURS = 16
AUTO_BREAK_AFTER_MIN = 6 * 60
KEEP_DAYS = 5 * 365 + 31
DAYS_DA = ["Man", "Tir", "Ons", "Tor", "Fre", "Lør", "Søn"]


# ---------- tid ----------

def local_day(dt: datetime) -> date:
    return to_local(dt).date()


def day_bounds_utc(d: date) -> tuple[datetime, datetime]:
    """Start og slut på en lokal dag i UTC (uden tidszone, som i databasen)."""
    a = datetime(d.year, d.month, d.day, tzinfo=TZ)
    b = datetime.combine(d + timedelta(days=1), datetime.min.time(), tzinfo=TZ)  # også på dage med sommertid
    return a.astimezone(timezone.utc).replace(tzinfo=None), b.astimezone(timezone.utc).replace(tzinfo=None)


def monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def today() -> date:
    return datetime.now(TZ).date()


def minutes(e: TimeEntry, now: datetime | None = None) -> int:
    end = e.end_at or min(now or utcnow(), e.start_at + timedelta(hours=STALE_HOURS))
    return max(0, int((end - e.start_at).total_seconds() // 60) - (e.break_min or 0))


def stale(e: TimeEntry, now: datetime | None = None) -> bool:
    return e.end_at is None and (now or utcnow()) - e.start_at > timedelta(hours=STALE_HOURS)


def hm(mins: int) -> str:
    sign = "-" if mins < 0 else ""
    mins = abs(mins)
    return f"{sign}{mins // 60}:{mins % 60:02d}"


# ---------- PIN ----------

def set_pin(h: Host, pin: str) -> None:
    h.time_pin = hash_password(pin)


def check_pin(h: Host, pin: str) -> bool:
    return bool(h.time_pin) and verify_password(pin, h.time_pin)


# ---------- stempling ----------

def open_entry(db: Session, host: Host) -> TimeEntry | None:
    """Den igangværende post (startet inden for 16 timer), eller None."""
    since = utcnow() - timedelta(hours=STALE_HOURS)
    return db.scalar(select(TimeEntry).where(TimeEntry.host_id == host.id, TimeEntry.tenant_id == host.tenant_id,
                                             TimeEntry.end_at.is_(None), TimeEntry.start_at >= since)
                     .order_by(TimeEntry.start_at.desc()))


def clock(db: Session, host: Host, source: str) -> tuple[str, TimeEntry]:
    """Stempl ind eller ud. Returnerer ("in" | "out", posten). Kalderen committer."""
    now = utcnow().replace(microsecond=0)
    e = open_entry(db, host)
    if e is not None:
        e.end_at = now
        t = db.get(Tenant, host.tenant_id)
        if not e.break_min and t.time_break_min and (now - e.start_at).total_seconds() / 60 > AUTO_BREAK_AFTER_MIN:
            e.break_min = t.time_break_min
        return "out", e
    e = TimeEntry(tenant_id=host.tenant_id, host_id=host.id, name=host.name, start_at=now, source=source)
    db.add(e)
    db.flush()
    return "in", e


def day_total(db: Session, host: Host, d: date) -> int:
    a, b = day_bounds_utc(d)
    return sum(minutes(e) for e in db.scalars(select(TimeEntry).where(
        TimeEntry.host_id == host.id, TimeEntry.tenant_id == host.tenant_id, TimeEntry.start_at >= a,
        TimeEntry.start_at < b)).all())


def inside(db: Session, tenant_ids) -> list[dict]:
    """Medarbejdere, der er stemplet ind lige nu (til evakueringslisten og admin)."""
    since = utcnow() - timedelta(hours=STALE_HOURS)
    rows = db.scalars(select(TimeEntry).where(TimeEntry.tenant_id.in_(tenant_ids), TimeEntry.end_at.is_(None),
                                              TimeEntry.start_at >= since).order_by(TimeEntry.name)).all()
    names = {t.id: t.name for t in db.scalars(select(Tenant).where(Tenant.id.in_(tenant_ids))).all()}
    return [{"id": e.id, "host_id": e.host_id, "name": e.name, "since": local_iso(e.start_at),
             "since_hhmm": to_local(e.start_at).strftime("%H:%M"), "firm": names.get(e.tenant_id, "")} for e in rows]


# ---------- ud ----------

def entry_out(e: TimeEntry) -> dict:
    return {"id": e.id, "host_id": e.host_id, "name": e.name, "start": local_iso(e.start_at),
            "end": local_iso(e.end_at), "day": local_day(e.start_at).isoformat(), "break_min": e.break_min,
            "minutes": minutes(e), "source": e.source, "note": e.note, "approved": e.approved_at is not None,
            "approved_by": e.approved_by, "open": e.end_at is None, "stale": stale(e),
            "edits": json.loads(e.edit_log or "[]")}


def entries(db: Session, tenant_id: int, a: date, b: date, host_id: int | None = None) -> list[TimeEntry]:
    """Poster, der starter fra dag a til og med dag b (lokal tid)."""
    ua, _ = day_bounds_utc(a)
    _, ub = day_bounds_utc(b)
    q = select(TimeEntry).where(TimeEntry.tenant_id == tenant_id, TimeEntry.start_at >= ua, TimeEntry.start_at < ub)
    if host_id is not None:
        q = q.where(TimeEntry.host_id == host_id)
    return list(db.scalars(q.order_by(TimeEntry.start_at)).all())


def week(db: Session, t: Tenant, monday: date) -> dict:
    days = [monday + timedelta(days=i) for i in range(7)]
    rows = entries(db, t.id, days[0], days[-1])
    staff = [h for h in t.hosts if h.time_enabled]
    by_host: dict[int | None, dict] = {}
    for h in staff:
        by_host[h.id] = {"host_id": h.id, "name": h.name, "norm": h.time_norm_min, "days": [0] * 7, "entries": [],
                         "approved": True, "has": False, "missing": 0}
    for e in rows:
        r = by_host.setdefault(e.host_id, {"host_id": e.host_id, "name": e.name, "norm": 0, "days": [0] * 7,
                                           "entries": [], "approved": True, "has": False, "missing": 0, "former": True})
        i = (local_day(e.start_at) - monday).days
        r["days"][i] += minutes(e)
        r["entries"].append(entry_out(e))
        r["has"] = True
        r["approved"] = r["approved"] and e.approved_at is not None
        r["missing"] += 1 if stale(e) else 0
    out = []
    for r in by_host.values():
        r["total"] = sum(r["days"])
        r["diff"] = r["total"] - r["norm"] if r["norm"] else None
        r["approved"] = r["approved"] and r["has"]
        out.append(r)
    out.sort(key=lambda r: r["name"].lower())
    iso = monday.isocalendar()
    return {"monday": monday.isoformat(), "week": iso[1], "year": iso[0],
            "days": [{"date": d.isoformat(), "label": f"{DAYS_DA[i]} {d.day}.{d.month}", "today": d == today()}
                     for i, d in enumerate(days)],
            "rows": out, "inside": inside(db, [t.id]),
            "missing": sum(r["missing"] for r in out),
            "total": sum(r["total"] for r in out)}


def personal(db: Session, h: Host, monday: date) -> dict:
    """Medarbejderens egen side: status, ugen og måneden (retten til at se sine registreringer)."""
    days = [monday + timedelta(days=i) for i in range(7)]
    rows = entries(db, h.tenant_id, days[0], days[-1], h.id)
    first = today().replace(day=1)
    month = sum(minutes(e) for e in entries(db, h.tenant_id, first, today(), h.id))
    cur = open_entry(db, h)
    return {"name": h.name, "inside": cur is not None, "since": local_iso(cur.start_at) if cur else None,
            "today": day_total(db, h, today()), "month": month, "month_label": first.strftime("%m.%Y"),
            "norm": h.time_norm_min, "monday": monday.isoformat(), "week": monday.isocalendar()[1],
            "days": [{"date": d.isoformat(), "label": f"{DAYS_DA[i]} {d.day}.{d.month}",
                      "entries": [entry_out(e) for e in rows if local_day(e.start_at) == d],
                      "minutes": sum(minutes(e) for e in rows if local_day(e.start_at) == d)} for i, d in enumerate(days)],
            "total": sum(minutes(e) for e in rows)}


# ---------- rettelser ----------

def log_edit(e: TimeEntry, by: str, what: str, before: dict, after: dict) -> None:
    log = json.loads(e.edit_log or "[]")
    log.append({"at": local_iso(utcnow()), "by": by, "what": what, "from": before, "to": after})
    e.edit_log = json.dumps(log, ensure_ascii=False)


def snapshot(e: TimeEntry) -> dict:
    return {"start": local_iso(e.start_at), "end": local_iso(e.end_at), "break_min": e.break_min, "note": e.note}


def purge(db: Session) -> int:
    """Slet poster ældre end 5 år (plus en måned)."""
    n = db.execute(delete(TimeEntry).where(TimeEntry.start_at < utcnow() - timedelta(days=KEEP_DAYS))).rowcount
    db.commit()
    return n


# ---------- eksport ----------

def export_csv(db: Session, t: Tenant, a: date, b: date) -> str:
    """Én linje pr. post plus en sum pr. medarbejder. Semikolon og komma, så dansk Excel, Danløn og Salary kan læse den."""
    rows = entries(db, t.id, a, b)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Medarbejder", "Dato", "Ind", "Ud", "Pause (min.)", "Timer", "Godkendt", "Note"])
    totals: dict[str, int] = {}
    for e in rows:
        m = minutes(e)
        totals[e.name] = totals.get(e.name, 0) + m
        w.writerow([e.name, local_day(e.start_at).strftime("%d-%m-%Y"), to_local(e.start_at).strftime("%H:%M"),
                    to_local(e.end_at).strftime("%H:%M") if e.end_at else "mangler", e.break_min,
                    f"{m / 60:.2f}".replace(".", ","), "ja" if e.approved_at else "nej", e.note])
    w.writerow([])
    w.writerow(["Medarbejder", "I alt (timer)"])
    for name in sorted(totals, key=str.lower):
        w.writerow([name, f"{totals[name] / 60:.2f}".replace(".", ",")])
    return "﻿" + buf.getvalue()
