"""Overblik og månedsrapport. Data lægges ind med faste datoer i oktober 2025."""
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from app import reports
from app.db import SessionLocal
from app.main import app
from app.models import Booking, CateringLine, CateringOrder, VisitStat


@pytest.fixture(scope="module")
def plat(client):
    c = TestClient(app)
    assert c.post("/api/admin/login", json={"password": "hemmelig"}).status_code == 200
    return c


@pytest.fixture()
def house(plat):
    partner = plat.post("/api/admin/partners", json={"name": "Rapporthuset"}).json()
    plat.post(f"/api/admin/billing/account/subscriptions?partner_id={partner['id']}", json={"product": "hus"})
    a = plat.post("/api/admin/tenants", json={"name": "Alfa Rapport", "partner_id": partner["id"]}).json()
    b = plat.post("/api/admin/tenants", json={"name": "Beta Rapport", "partner_id": partner["id"]}).json()
    room = plat.post("/api/admin/rooms", json={"partner_id": partner["id"], "name": "Sal"}).json()
    k = plat.post("/api/admin/kitchens", json={"partner_id": partner["id"], "name": "Køkken"}).json()
    with SessionLocal() as db:
        for tid, month, kind, n in [(a["id"], "2025-10", "guest", 40), (a["id"], "2025-09", "guest", 20),
                                    (b["id"], "2025-10", "guest", 10), (a["id"], "2025-10", "delivery", 5)]:
            db.add(VisitStat(tenant_id=tid, month=month, kind=kind, count=n))
        bk = Booking(room_id=room["id"], tenant_id=a["id"], title="Fyringsrunde 1", organizer="Anna",
                     start_at=datetime(2025, 10, 15, 7, 0), end_at=datetime(2025, 10, 15, 10, 0), attendees=6, source="link")
        quick = Booking(room_id=room["id"], tenant_id=None, title="Booket på skærmen", start_at=datetime(2025, 10, 16, 8, 0),
                        end_at=datetime(2025, 10, 16, 9, 0), source="screen")
        db.add_all([bk, quick])
        db.flush()
        o = CateringOrder(booking_id=bk.id, kitchen_id=k["id"], tenant_id=a["id"], deliver_at=datetime(2025, 10, 15, 7, 0),
                          cost_center="Ledelse", total=60000, status="confirmed")
        db.add(o)
        db.flush()
        db.add_all([CateringLine(order_id=o.id, name="Sandwich", unit="stk.", unit_price=7500, qty=6),
                    CateringLine(order_id=o.id, name="Kaffe", unit="kande", unit_price=7500, qty=2)])
        db.commit()
    yield {"partner": partner, "a": a, "b": b, "room": room}
    for t in (a, b):
        plat.delete(f"/api/admin/tenants/{t['id']}")
    plat.delete(f"/api/admin/partners/{partner['id']}")


def test_periods():
    assert reports.parse_period("2025-10")[:3] == ("month", date(2025, 10, 1), date(2025, 11, 1))
    assert reports.parse_period("2025-Q4")[:3] == ("quarter", date(2025, 10, 1), date(2026, 1, 1))
    assert reports.parse_period("2025")[:3] == ("year", date(2025, 1, 1), date(2026, 1, 1))
    assert reports.parse_period(None, today=date(2026, 1, 10))[3] == "2025-12"  # sidste hele måned
    assert reports.period_label("quarter", date(2025, 10, 1)) == "4. kvartal 2025"
    with pytest.raises(Exception):
        reports.parse_period("2025-Q7")


def test_house_report(plat, house):
    r = plat.get(f"/api/admin/report?partner_id={house['partner']['id']}&period=2025-10").json()
    assert r["period"]["label"] == "oktober 2025" and r["period"]["prev_key"] == "2025-09"
    assert r["guests"]["value"] == 50 and r["guests"]["prev"] == 20 and r["guests"]["delta"] == 150.0
    assert r["deliveries"]["value"] == 5 and len(r["months"]) == 13 and r["months"][-1]["current"]
    assert r["guests"]["trend"][-1] == 50 and r["guests"]["trend"][-2] == 20
    rooms = r["rooms"]
    assert rooms["bookings"]["value"] == 2 and rooms["on_screen"] == 1 and rooms["hours"] == 4.0
    assert rooms["per_room"][0]["name"] == "Sal"
    assert rooms["per_room"][0]["utilization"] == round(100 * 4 / (23 * 9), 1)  # 23 hverdage i oktober 2025
    assert rooms["weekdays"][2]["value"] == 1  # onsdag
    cat = r["catering"]
    assert cat["revenue"]["value"] == 60000 and cat["orders"] == 1
    assert [i["name"] for i in cat["top_items"]] == ["Sandwich", "Kaffe"] and cat["top_items"][0]["qty"] == 6
    assert cat["groups"][0]["name"] == "Alfa Rapport"
    firms = {f["name"]: f for f in r["firms"]}
    assert firms["Alfa Rapport"]["guests"] == 40 and firms["Beta Rapport"]["guests"] == 10
    assert firms["Alfa Rapport"]["bookings"] == 1
    assert "Fyringsrunde" not in str(r) and "Anna" not in str(r)  # ingen mødetitler eller navne

    q4 = plat.get(f"/api/admin/report?partner_id={house['partner']['id']}&period=2025-Q4").json()
    assert q4["guests"]["value"] == 50 and q4["period"]["prev_label"] == "3. kvartal 2025" and q4["guests"]["prev"] == 20


def test_firm_report_csv_and_mail(plat, house):
    a = house["a"]
    r = plat.get(f"/api/admin/report?tenant_id={a['id']}&period=2025-10").json()
    assert r["guests"]["value"] == 40 and r["firms"] is None
    assert r["rooms"]["bookings"]["value"] == 1  # kun Alfas egne bookinger
    assert r["catering"]["groups"][0]["name"] == "Ledelse"
    csv = plat.get(f"/api/admin/report?tenant_id={a['id']}&period=2025-10&format=csv").text
    assert "Gæster;40;20;100,0" in csv and "Forplejning kr.;600,00" in csv
    mail = plat.get(f"/api/admin/report/mail-preview?tenant_id={a['id']}&period=2025-10").text
    assert "Alfa Rapport" in mail and "oktober 2025" in mail.lower() and "Fyringsrunde" not in mail
    assert "/admin/rapport?tenant_id=" in mail
    assert plat.get(f"/api/admin/report?tenant_id={a['id']}&period=forkert").status_code == 422


def test_monthly_send_once(plat, house):
    pid, a = house["partner"]["id"], house["a"]
    assert plat.patch(f"/api/admin/partners/{pid}", json={"report_email": "chef@rapporthuset.dk"}).status_code == 200
    plat.patch(f"/api/admin/tenants/{a['id']}", json={"report_email": "direktion@alfa.dk"})
    first = reports.send_due(SessionLocal, today=date(2025, 11, 1))
    assert first >= 2
    assert reports.send_due(SessionLocal, today=date(2025, 11, 1)) == 0  # sendes kun én gang
    runs = plat.get(f"/api/admin/report/settings?partner_id={pid}").json()["runs"]
    assert runs[0]["month"] == "2025-10" and runs[0]["status"] == "test" and runs[0]["recipients"] == "chef@rapporthuset.dk"
    r = plat.post(f"/api/admin/report/send-test?tenant_id={a['id']}", json={})
    assert r.status_code == 200 and r.json()["status"] == "test" and r.json()["recipients"] == ["direktion@alfa.dk"]
    assert plat.post(f"/api/admin/report/send-test?tenant_id={house['b']['id']}", json={}).status_code == 422


def test_report_needs_module_for_customers(plat, house):
    pid = house["partner"]["id"]
    lone = plat.post("/api/admin/tenants", json={"name": "Uden rapport"}).json()
    plat.patch(f"/api/admin/tenants/{lone['id']}/subscription", json={"self_service": True})
    link = plat.post(f"/api/admin/tenants/{lone['id']}/users", json={"email": "admin@udenrapport.dk"}).json()["invite_url"]
    c = TestClient(app)
    c.post("/api/admin/invite/accept", json={"token": link.split("#invite=")[1], "password": "uden-kode-1234"})
    assert c.get(f"/api/admin/report?tenant_id={lone['id']}").status_code == 403  # Start/ingen pakke
    assert c.get(f"/api/admin/report?partner_id={pid}").status_code == 404
    assert c.get(f"/api/admin/report?tenant_id={house['a']['id']}").status_code == 404
    assert plat.get(f"/api/admin/report?tenant_id={lone['id']}").status_code == 200  # leverandøren kan altid vise det
    plat.post(f"/api/admin/billing/account/subscriptions?tenant_id={lone['id']}", json={"product": "plus"})
    assert c.get(f"/api/admin/report?tenant_id={lone['id']}").status_code == 200
    # Uden modul sendes ingen månedsrapport, selv om der står en adresse.
    plat.delete(f"/api/admin/tenants/{lone['id']}")
    assert TestClient(app).get(f"/api/admin/report?partner_id={pid}").status_code == 401
