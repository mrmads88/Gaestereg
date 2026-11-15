"""Opsætning af nye kunder ("Kom i gang"-tjekliste) og demoen til salgsmøder."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import billing, crm, reports
from app.config import settings
from app.db import SessionLocal
from app.main import app
from app.models import Notification, Tenant, Visit

A = "/api/admin"


@pytest.fixture(scope="module")
def plat(client):
    c = TestClient(app)
    assert c.post(f"{A}/login", json={"password": "hemmelig"}).status_code == 200
    return c


def test_checklist_ticks_itself_off(plat):
    t = plat.post(f"{A}/tenants", json={"name": "Tjekliste ApS"}).json()
    cl = plat.get(f"{A}/tenants/{t['id']}/checklist").json()
    keys = {x["key"]: x for x in cl["items"]}
    assert not cl["complete"] and not keys["people"]["done"] and not keys["package"]["done"] and keys["people"]["tab"] == "people"
    h = plat.post(f"{A}/tenants/{t['id']}/hosts", json={"name": "Første Person"}).json()
    plat.post(f"{A}/billing/account/subscriptions?tenant_id={t['id']}", json={"product": "start", "start": date.today().isoformat()})
    keys = {x["key"]: x for x in plat.get(f"{A}/tenants/{t['id']}/checklist").json()["items"]}
    assert keys["people"]["done"] and keys["package"]["done"] and "admin" not in keys  # Start har ikke selvbetjening
    assert TestClient(app).post(f"/api/kiosk/{t['kiosk_token']}/checkin",
                                json={"guest_name": "Gæst Gæstesen", "guest_phone": "20304050", "host_id": h["id"]}).status_code == 200
    keys = {x["key"]: x for x in plat.get(f"{A}/tenants/{t['id']}/checklist").json()["items"]}
    assert keys["guest"]["done"] and keys["screen"]["done"]
    assert plat.post(f"{A}/tenants/{t['id']}/checklist/hide", json={"hidden": True}).json()["hidden"]
    assert plat.get(f"{A}/tenants/{t['id']}").json()["is_demo"] is False
    plat.delete(f"{A}/tenants/{t['id']}")


def test_demo_is_rich_resettable_and_never_sends_or_bills(plat, monkeypatch):
    r = plat.post(f"{A}/demo").json()
    assert r["firm_kiosk"] == "/k/demo-nordlys" and r["tenants"] == 4
    st = plat.get(f"{A}/demo").json()
    assert st["exists"] and st["firm_id"] == r["firm_id"]
    firm = plat.get(f"{A}/tenants/{r['firm_id']}").json()
    assert firm["is_demo"] and all(firm["modules"][m]["on"] for m in ("rooms", "catering", "signage", "time", "reports"))
    cfg = TestClient(app).get("/api/kiosk/demo-nordlys/config").json()
    assert len(cfg["hosts"]) == 8 and len(cfg["staff"]) == 5
    week = plat.get(f"{A}/tenants/{r['firm_id']}/time/week").json()
    assert week["rows"] and any(row["approved"] for row in plat.get(
        f"{A}/tenants/{r['firm_id']}/time/week", params={"monday": "2000-01-03"}).json()["rows"]) is False
    assert plat.get(f"{A}/tenants/{r['firm_id']}/checklist").json()["complete"] is False  # skærmen er ikke tændt endnu

    # Selv i live-tilstand sendes intet for en demo-kunde.
    monkeypatch.setattr(settings, "notify_mode", "live")
    r_in = TestClient(app).post("/api/kiosk/demo-nordlys/checkin", json={
        "guest_name": "Salgsmøde Gæst", "guest_phone": "20304050", "host_id": cfg["hosts"][0]["id"], "accept_terms": True})
    assert r_in.status_code == 200, r_in.text
    with SessionLocal() as db:
        v = db.query(Visit).filter(Visit.guest_name == "Salgsmøde Gæst").one()
        rows = db.query(Notification).filter(Notification.visit_id == v.id).all()
        assert rows and all(n.status == "test" for n in rows)
        # Faktureres aldrig, ingen månedsrapport, ikke i CRM.
        demo_ids = {t.id for t in db.query(Tenant).filter(Tenant.is_demo == True).all()}  # noqa: E712
        assert not any(a.tenant_id in demo_ids for a in billing.due_accounts(db, date.today().replace(day=1)))
        db.get(Tenant, r["firm_id"]).report_email = "chef@example.com"
        db.commit()
        monkeypatch.setattr(settings, "notify_mode", "test")
        before = db.query(reports.ReportRun).filter(reports.ReportRun.scope == "tenant",
                                                     reports.ReportRun.scope_id == r["firm_id"]).count()
        reports.send_due(SessionLocal)
        assert db.query(reports.ReportRun).filter(reports.ReportRun.scope == "tenant",
                                                  reports.ReportRun.scope_id == r["firm_id"]).count() == before
        crm.sync_from_nodd(db)
        db.commit()
    names = [c["name"] for c in plat.get(f"{A}/crm/companies").json()]
    assert not any(n.startswith(("Nordlys", "Havnehuset", "Lund & Co", "Byg & Bolig")) for n in names)

    # Nulstil: samme demo igen, uden dubletter.
    r2 = plat.post(f"{A}/demo").json()
    with SessionLocal() as db:
        assert db.query(Tenant).filter(Tenant.is_demo == True).count() == 4  # noqa: E712
    assert plat.delete(f"{A}/demo").json()["removed"] == 4
    assert not plat.get(f"{A}/demo").json()["exists"]
    assert TestClient(app).get("/api/kiosk/demo-nordlys/config").status_code == 404
    assert r2["firm_kiosk"] == r["firm_kiosk"]
