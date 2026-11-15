"""Demo til salgsmøder: et fiktivt firma og et kontorhotel med realistiske data, som kan nulstilles med ét klik.

- "Nordlys Arkitekter (demo)": pakken Komplet + Tidsregistrering. Personer, besøg de sidste 60 dage og statistik for et år,
  forventede gæster, tre mødelokaler med bookinger, køkken med menu og bestillinger, en infoskærm og arbejdstid.
- "Havnehuset (demo)": et kontorhotel med to lejere, en fælles husskærm, husets lokaler og køkken.

Demo-kunderne er markeret med is_demo. De sender aldrig rigtige beskeder (notify.deliver), faktureres aldrig
(billing.due_accounts), får ingen månedsrapport og kommer ikke med i CRM'et. Alle tider regnes fra i dag, så demoen
altid ser levende ud. Navne, firmaer og telefonnumre er opdigtede.
"""
import json
import random
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select, true
from sqlalchemy.orm import Session

from . import billing, invitations, legal, timereg
from .media import storage
from .models import (Booking, CateringLine, CateringOrder, Host, Invitation, Kitchen, MenuItem, Partner, Room,
                     SignageScreen, Tenant, TimeEntry, Visit, VisitStat, new_token, utcnow)
from .seed import _placeholder_portrait
from .signage import default_content
from .timeutil import TZ

FIRM_TOKEN, HOUSE_TOKEN = "demo-nordlys", "demo-havnehus"

FIRST = ["Mette", "Lars", "Sara", "Mads", "Ida", "Kasper", "Julie", "Nikolaj", "Camilla", "Rasmus", "Emma", "Frederik",
         "Louise", "Jens", "Maria", "Oliver", "Anna", "Søren", "Laura", "Mikkel", "Freja", "Henrik", "Signe", "Peter"]
LAST = ["Jensen", "Nielsen", "Hansen", "Pedersen", "Andersen", "Christensen", "Larsen", "Sørensen", "Rasmussen",
        "Jørgensen", "Petersen", "Madsen", "Kristensen", "Olsen", "Thomsen", "Poulsen", "Johansen", "Møller"]
COMPANIES = ["Vestas", "Mærsk", "COWI", "Rambøll", "Danske Bank", "Novo Nordisk", "Carlsberg", "Københavns Kommune",
             "Aarhus Universitet", "Netcompany", "Lego", "DSV", "Grundfos", "Arla", "Ørsted", "Velux", "", ""]
COLORS = [("#c7d2fe", "#3730a3"), ("#bbf7d0", "#166534"), ("#fecdd3", "#9f1239"), ("#fde68a", "#92400e"),
          ("#bae6fd", "#075985"), ("#e9d5ff", "#6b21a8"), ("#fed7aa", "#9a3412"), ("#ccfbf1", "#115e59")]
MEETINGS = ["Projektmøde: Havnebadet", "Kundemøde", "Ugemøde", "Tegnestue-review", "Workshop: ny skole", "1:1",
            "Tilbudsgennemgang", "Byggemøde", "Frokostmøde med bygherre", "Ledermøde"]


def _logo(name: str, sub: str, color: str) -> str:
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 360 90"><circle cx="40" cy="45" r="26" fill="{color}"/>'
           f'<path d="M26 52l14-18 14 18" stroke="#fff" stroke-width="6" fill="none" stroke-linejoin="round"/>'
           f'<text x="80" y="46" font-family="Helvetica,Arial,sans-serif" font-weight="800" font-size="28" letter-spacing="1.5" '
           f'fill="#14171f">{name}</text><text x="80" y="72" font-family="Georgia,serif" font-style="italic" font-size="20" '
           f'fill="{color}">{sub}</text></svg>')
    fname = f"{uuid.uuid4().hex}.svg"  # samme navneformat som uploadede billeder
    storage.save(fname, svg.encode("utf-8"))
    return fname


def _utc(d: date, h: int, m: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, h, m, tzinfo=TZ).astimezone(timezone.utc).replace(tzinfo=None)


def _people(db: Session, t: Tenant, rows: list[tuple[str, str]], rnd: random.Random) -> list[Host]:
    hosts = []
    for i, (name, title) in enumerate(rows):
        bg, fg = COLORS[i % len(COLORS)]
        first = name.split()[0].lower().replace("ø", "oe").replace("æ", "ae").replace("å", "aa")
        h = Host(tenant_id=t.id, name=name, title=title, email=f"{first}@example.com",
                 phone=f"+45 20 {rnd.randint(10, 99)} {rnd.randint(10, 99)} {rnd.randint(10, 99)}", sort_order=i,
                 notify_sms=True, notify_email=True, photo_path=_placeholder_portrait(name, bg, fg))
        db.add(h)
        hosts.append(h)
    db.flush()
    return hosts


def _guest(rnd: random.Random) -> tuple[str, str, str]:
    return (f"{rnd.choice(FIRST)} {rnd.choice(LAST)}", rnd.choice(COMPANIES),
            f"+45 {rnd.randint(20, 61)} {rnd.randint(10, 99)} {rnd.randint(10, 99)} {rnd.randint(10, 99)}")


def _visits(db: Session, t: Tenant, hosts: list[Host], rnd: random.Random, per_day: tuple[int, int]) -> None:
    """Besøg de sidste 60 dage på hverdage og statistik for et år."""
    today = timereg.today()
    now = utcnow()
    counts: dict[str, list[int]] = {}
    for back in range(60, -1, -1):
        d = today - timedelta(days=back)
        if d.weekday() >= 5:
            continue
        for _ in range(rnd.randint(*per_day)):
            h = rnd.choice(hosts)
            start = _utc(d, rnd.randint(8, 15), rnd.choice((0, 5, 10, 15, 20, 30, 40, 45, 50)))
            if start > now:
                continue
            end = start + timedelta(minutes=rnd.randint(30, 180))
            inside = back == 0 and end > now
            name, company, phone = _guest(rnd)
            kind = "delivery" if rnd.random() < .12 else "guest"
            db.add(Visit(tenant_id=t.id, host_id=h.id, host_name=h.name, guest_name=name if kind == "guest" else "GLS",
                         guest_phone=phone if kind == "guest" else "", guest_company=company if kind == "guest" else "GLS",
                         checked_in_at=start, checked_out_at=None if inside or kind == "delivery" else end, kind=kind))
            c = counts.setdefault(start.strftime("%Y-%m"), [0, 0])
            c[0 if kind == "guest" else 1] += 1
    # Tidligere måneder (før de 60 dage): et jævnt voksende antal, så overblikket har et år at vise.
    m = today.replace(day=1)
    for i in range(1, 13):
        m = (m - timedelta(days=1)).replace(day=1)
        key = m.strftime("%Y-%m")
        if key not in counts:
            base = per_day[1] * 14
            counts[key] = [int(base * (1 - i * 0.04 + rnd.random() * .2)), rnd.randint(8, 25)]
    for key, (g, dl) in counts.items():
        db.add(VisitStat(tenant_id=t.id, month=key, kind="guest", count=max(0, g)))
        db.add(VisitStat(tenant_id=t.id, month=key, kind="delivery", count=dl))


def _rooms(db: Session, rows: list[tuple[str, str, int, list[str]]], tenant_id=None, partner_id=None) -> list[Room]:
    rooms = []
    for i, (name, loc, cap, eq) in enumerate(rows):
        r = Room(tenant_id=tenant_id, partner_id=partner_id, name=name, location=loc, capacity=cap,
                 description=f"Plads til {cap}.", setups=json.dumps(["Mødebord", "U-bord"], ensure_ascii=False),
                 equipment=json.dumps(eq, ensure_ascii=False), sort_order=i)
        db.add(r)
        rooms.append(r)
    db.flush()
    return rooms


def _bookings(db: Session, t: Tenant, rooms: list[Room], hosts: list[Host], rnd: random.Random) -> list[Booking]:
    out = []
    today = timereg.today()
    for back in range(-3, 10):
        d = today + timedelta(days=back)
        if d.weekday() >= 5:
            continue
        for r in rooms:
            hour = 8
            for _ in range(rnd.randint(1, 3)):
                hour += rnd.randint(0, 2)
                length = rnd.choice((1, 1, 2))
                if hour + length > 17:
                    break
                h = rnd.choice(hosts)
                b = Booking(room_id=r.id, tenant_id=t.id, host_id=h.id, title=rnd.choice(MEETINGS), organizer=h.name,
                            start_at=_utc(d, hour), end_at=_utc(d, hour + length),
                            attendees=min(r.capacity, rnd.randint(2, max(2, r.capacity))), source="admin")
                db.add(b)
                out.append(b)
                hour += length
    db.flush()
    return out


def _kitchen(db: Session, name: str, tenant_id=None, partner_id=None) -> tuple[Kitchen, list[MenuItem]]:
    from .routes_catering import SAMPLE_MENU
    k = Kitchen(tenant_id=tenant_id, partner_id=partner_id, name=name, kind="internal", email="kantine@example.com",
                phone="+45 20 00 00 99", lead_hours=12, note="Bestil senest dagen før kl. 12.")
    db.add(k)
    db.flush()
    items = []
    for n, (cat, iname, desc, price, unit, tags) in enumerate(SAMPLE_MENU):
        i = MenuItem(kitchen_id=k.id, category=cat, name=iname, description=desc, price=price * 100, unit=unit,
                     tags=json.dumps(tags, ensure_ascii=False), sort_order=n)
        db.add(i)
        items.append(i)
    db.flush()
    return k, items


def _orders(db: Session, k: Kitchen, items: list[MenuItem], bookings: list[Booking], t: Tenant, rnd: random.Random) -> None:
    for b in rnd.sample(bookings, min(8, len(bookings))):
        o = CateringOrder(booking_id=b.id, kitchen_id=k.id, tenant_id=t.id, deliver_at=b.start_at,
                          status="confirmed" if b.start_at < utcnow() + timedelta(days=1) else "new")
        db.add(o)
        db.flush()
        total = 0
        for i in rnd.sample(items, rnd.randint(1, 3)):
            qty = b.attendees if "person" in i.unit else rnd.randint(1, 3)
            db.add(CateringLine(order_id=o.id, menu_item_id=i.id, name=i.name, unit=i.unit, unit_price=i.price, qty=qty))
            total += i.price * qty
        o.total = total


def _time(db: Session, t: Tenant, hosts: list[Host], rnd: random.Random) -> None:
    today = timereg.today()
    monday = timereg.monday_of(today)
    now = utcnow()
    local_hour = datetime.now(TZ).hour
    for h in hosts:
        h.time_enabled, h.time_norm_min = True, 37 * 60
        timereg.set_pin(h, "1234")
        for back in range(21, -1, -1):
            d = today - timedelta(days=back)
            if d.weekday() >= 5:
                continue
            start = _utc(d, rnd.choice((7, 8, 8, 8, 9)), rnd.choice((0, 10, 20, 30, 45)))
            if d == today:
                if 8 <= local_hour < 18 and start < now:
                    db.add(TimeEntry(tenant_id=t.id, host_id=h.id, name=h.name, start_at=start, source="kiosk"))
                continue
            end = start + timedelta(hours=rnd.choice((7, 7, 8, 8, 8, 9)), minutes=rnd.choice((0, 15, 30, 45)))
            approved = d < monday
            db.add(TimeEntry(tenant_id=t.id, host_id=h.id, name=h.name, start_at=start, end_at=end, break_min=30,
                             source=rnd.choice(("kiosk", "kiosk", "phone")), approved_at=now if approved else None,
                             approved_by="Demo" if approved else ""))


def _base_tenant(name: str, token: str, color: str, logo: str, **kw) -> Tenant:
    return Tenant(name=name, kiosk_token=token, color=color, logo_path=logo, is_demo=True, welcome_text=f"Velkommen til {name.split(' (')[0]}",
                  sms_sender=name.split()[0][:11], languages="da,en", lang_mode="toggle", wifi_name="Gæst",
                  wifi_password="velkommen2026", delivery_enabled=True, reception_email="reception@example.com",
                  dpa_version=legal.version(), dpa_accepted_at=utcnow(), dpa_accepted_by="Demo",
                  checklist_hidden=True, **kw)  # demoen skal se færdig ud


def remove(db: Session) -> int:
    """Slet alle demo-kunder og demo-huse."""
    from .routes_access import remove_partner
    from .routes_admin import remove_tenant
    n = 0
    for t in db.scalars(select(Tenant).where(Tenant.is_demo == true())).all():
        remove_tenant(db, t)
        n += 1
    for p in db.scalars(select(Partner).where(Partner.is_demo == true())).all():
        remove_partner(db, p)
    db.commit()
    return n


def build(db: Session, seed: int = 7) -> dict:
    """Lav demoen forfra. Returnerer id'erne og skærmlinks."""
    remove(db)
    rnd = random.Random(seed)
    today = timereg.today()

    # ---------- firmaet ----------
    firm = _base_tenant("Nordlys Arkitekter (demo)", FIRM_TOKEN, "#0f766e", _logo("NORDLYS", "Arkitekter", "#0f766e"),
                        terms_enabled=True, terms_title="Husregler",
                        terms_text="Bær gæstekortet synligt. Følg altid din vært. Fotografering er ikke tilladt i tegnestuen.",
                        group_checkin=True,  # ingen åbningstider: demoen skal virke, uanset hvornår den vises
                        time_break_min=30)
    db.add(firm)
    db.flush()
    acc = billing.account_for(db, tenant=firm)
    for code in ("komplet", "time"):
        billing.subscribe(db, acc, billing.product_by_code(db, code), today.replace(day=1))
    staff = _people(db, firm, [("Karen Lindholm", "Partner, arkitekt MAA"), ("Jakob Winther", "Arkitekt"),
                               ("Nanna Skov", "Projektleder"), ("Ahmed Rahimi", "Konstruktør"),
                               ("Pernille Juhl", "Landskabsarkitekt"), ("Thomas Krogh", "Økonomi"),
                               ("Ida Bech", "Studentermedhjælper"), ("Morten Holst", "IT")], rnd)
    _visits(db, firm, staff, rnd, (4, 11))
    for i in range(4):
        h = staff[i]
        name, company, phone = _guest(rnd)
        db.add(Invitation(tenant_id=firm.id, host_id=h.id, host_name=h.name, guest_name=name, guest_company=company,
                          guest_phone=phone, expected_at=_utc(today + timedelta(days=i // 2), 10 + i, 0),
                          code=invitations.new_code(db, firm.id), created_by=h.name))
        db.flush()
    rooms = _rooms(db, [("Fjorden", "Stuen", 12, ["Skærm", "Whiteboard", "Teams-kamera"]),
                        ("Skagen", "1. sal", 6, ["Skærm", "Whiteboard"]),
                        ("Telefonboksen", "1. sal", 2, ["Skærm"])], tenant_id=firm.id)
    bookings = _bookings(db, firm, rooms, staff, rnd)
    k, items = _kitchen(db, "Kantinen", tenant_id=firm.id)
    _orders(db, k, items, bookings, firm, rnd)
    content = default_content("Nordlys Arkitekter")
    content.setdefault("ticker", ["Fredagsbar kl. 15 i kantinen", "Husk at booke lokaler i god tid"])
    db.add(SignageScreen(tenant_id=firm.id, name="Receptionen", content=json.dumps(content, ensure_ascii=False)))
    _time(db, firm, staff[:5], rnd)

    # ---------- kontorhotellet ----------
    house = Partner(name="Havnehuset (demo)", is_demo=True, dpa_version=legal.version(), dpa_accepted_at=utcnow(),
                    dpa_accepted_by="Demo")
    db.add(house)
    db.flush()
    hacc = billing.account_for(db, partner=house)
    billing.subscribe(db, hacc, billing.product_by_code(db, "hus"), today.replace(day=1))
    screen = _base_tenant("Havnehuset (demo)", HOUSE_TOKEN, "#1e3a8a", _logo("HAVNEHUSET", "Kontorhotel", "#1e3a8a"),
                          partner_id=house.id, house_screen=True)
    db.add(screen)
    tenants = []
    for name, sub, color, people in (
            ("Lund & Co Advokater", "Advokatfirma", "#7c2d12", [("Birgitte Lund", "Partner"), ("Simon Dahl", "Advokat"),
                                                                ("Mia Kjeldsen", "Advokatsekretær")]),
            ("Byg & Bolig ApS", "Rådgivende ingeniører", "#b45309", [("Ole Vestergaard", "Direktør"),
                                                                     ("Katrine Friis", "Ingeniør"), ("Bo Mortensen", "Byggeleder")])):
        t = _base_tenant(f"{name} (demo)", new_token(), color, _logo(name.split()[0].upper(), sub, color), partner_id=house.id)
        db.add(t)
        db.flush()
        hosts = _people(db, t, people, rnd)
        _visits(db, t, hosts, rnd, (1, 5))
        tenants.append((t, hosts))
    db.flush()
    hrooms = _rooms(db, [("Havnesalen", "Stuen", 30, ["Projektor", "Mikrofon", "Teams-kamera"]),
                         ("Kajen", "2. sal", 8, ["Skærm", "Whiteboard"])], partner_id=house.id)
    for t, hosts in tenants:
        _bookings(db, t, hrooms[:1] if t is tenants[0][0] else hrooms[1:], hosts, rnd)
    _kitchen(db, "Havnehusets café", partner_id=house.id)
    db.commit()
    return {"firm_id": firm.id, "house_id": house.id, "firm_kiosk": f"/k/{FIRM_TOKEN}", "house_kiosk": f"/k/{HOUSE_TOKEN}",
            "tenants": 2 + len(tenants)}


def status(db: Session) -> dict:
    firm = db.scalar(select(Tenant).where(Tenant.is_demo == true(), Tenant.kiosk_token == FIRM_TOKEN))
    house = db.scalar(select(Partner).where(Partner.is_demo == true()))
    return {"exists": firm is not None, "firm_id": firm.id if firm else None, "house_id": house.id if house else None,
            "created_at": firm.created_at.isoformat() if firm else None}
