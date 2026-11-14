"""Leverandørens CRM: firmaer, kontakter, pipeline, opgaver, kobling til Nodd og morgenmail."""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app import crm
from app.db import SessionLocal
from app.main import app
from app.models import ReportRun

B = "/api/admin/crm"


@pytest.fixture(scope="module")
def plat(client):
    c = TestClient(app)
    assert c.post("/api/admin/login", json={"password": "hemmelig"}).status_code == 200
    return c


def test_company_contacts_deals_and_tasks(plat):
    c = plat.post(f"{B}/companies", json={"name": "  Havnens Advokater  ", "segment": "firma", "cvr": "12345678"}).json()
    assert c["name"] == "Havnens Advokater" and c["status"] == "emne" and c["timeline"][0]["text"] == "Oprettet i CRM"
    cid = c["id"]

    a = plat.post(f"{B}/companies/{cid}/contacts", json={"name": "Anne Berg", "email": "anne@havnen.dk"}).json()
    assert a["is_primary"]  # den første er primær
    b = plat.post(f"{B}/companies/{cid}/contacts", json={"name": "Bo Lund", "title": "Direktør", "is_primary": True}).json()
    cs = {x["name"]: x for x in plat.get(f"{B}/companies/{cid}").json()["contacts"]}
    assert cs["Bo Lund"]["is_primary"] and not cs["Anne Berg"]["is_primary"]

    d = plat.post(f"{B}/companies/{cid}/deals", json={"title": "Plus + lokaler", "stage": "demo", "monthly": 89800,
                                                       "once": 250000}).json()
    assert d["stage"] == "demo" and d["chance"] == 50 and d["open"]
    ov = plat.get(f"{B}/overview").json()
    assert ov["stages"]["demo"]["count"] >= 1 and ov["weighted"] >= 44900

    # Opgave uden dato = i dag, og den står i overblikket, til den er klaret.
    t = plat.post(f"{B}/companies/{cid}/activities", json={"kind": "opgave", "text": "Ring til Bo om tilbuddet",
                                                            "contact_id": b["id"], "deal_id": d["id"]}).json()
    assert t["due_date"] == crm.today().isoformat()
    assert any(x["id"] == t["id"] and x["company"] == "Havnens Advokater" for x in plat.get(f"{B}/overview").json()["due"])
    plat.post(f"{B}/companies/{cid}/activities", json={"kind": "opkald", "text": "Bo var positiv"})
    assert plat.patch(f"{B}/activities/{t['id']}", json={"done": True}).json()["done"]
    assert not any(x["id"] == t["id"] for x in plat.get(f"{B}/overview").json()["due"])
    old = plat.post(f"{B}/companies/{cid}/activities", json={"kind": "opgave", "text": "Send kontrakt",
                                                              "due_date": (crm.today() - timedelta(days=2)).isoformat()}).json()
    assert old["overdue"]

    # Vundet: firmaet bliver kunde, og det står i tidslinjen.
    w = plat.patch(f"/api/admin/crm/deals/{d['id']}", json={"stage": "vundet"}).json()
    assert w["stage"] == "vundet" and w["closed_at"] and not w["open"]
    full = plat.get(f"{B}/companies/{cid}").json()
    assert full["status"] == "kunde"
    texts = [x["text"] for x in full["timeline"]]
    assert "Plus + lokaler: Demo → Vundet" in texts and "Status: Emne → Kunde" in texts and "Bo var positiv" in texts
    assert [x["text"] for x in full["tasks"]][0] == "Send kontrakt"  # åbne opgaver først
    assert plat.get(f"{B}/overview").json()["won_month"]["count"] >= 1

    # Søg på kontaktens e-mail, filtrér på status og hent som CSV til Excel.
    rows = plat.get(f"{B}/companies", params={"q": "anne@havnen"}).json()
    assert [r["name"] for r in rows] == ["Havnens Advokater"] and rows[0]["contact"]["name"] == "Bo Lund"
    assert all(r["status"] == "emne" for r in plat.get(f"{B}/companies", params={"status": "emne"}).json())
    csv = plat.get(f"{B}/companies.csv", params={"q": "Havnens"})
    assert csv.text.startswith("﻿Firma;Status") and "Havnens Advokater;Kunde;Firma;12345678;Bo Lund" in csv.text

    # Systemlinjer kan ikke rettes eller slettes; en slettet salgsmulighed fjerner kun koblingen fra aktiviteterne.
    sys_id = next(x["id"] for x in full["timeline"] if x["kind"] == "system")
    assert plat.delete(f"/api/admin/crm/activities/{sys_id}").status_code == 404
    assert plat.delete(f"/api/admin/crm/deals/{d['id']}").status_code == 200
    assert plat.delete(f"/api/admin/crm/contacts/{b['id']}").status_code == 200
    task = next(x for x in plat.get(f"{B}/companies/{cid}").json()["tasks"] if x["id"] == t["id"])
    assert task["deal_id"] is None and task["contact_id"] is None
    assert plat.delete(f"{B}/companies/{cid}").status_code == 200
    assert plat.get(f"{B}/companies/{cid}").status_code == 404


def test_activity_must_belong_to_company(plat):
    a = plat.post(f"{B}/companies", json={"name": "Firma A"}).json()
    b = plat.post(f"{B}/companies", json={"name": "Firma B"}).json()
    x = plat.post(f"{B}/companies/{a['id']}/contacts", json={"name": "Kun hos A"}).json()
    r = plat.post(f"{B}/companies/{b['id']}/activities", json={"text": "Hej", "contact_id": x["id"]})
    assert r.status_code == 404
    plat.delete(f"{B}/companies/{a['id']}")
    plat.delete(f"{B}/companies/{b['id']}")


def test_link_to_nodd_shows_numbers_and_survives_delete(plat):
    t = plat.post("/api/admin/tenants", json={"name": "CRM Kunde ApS"}).json()
    price = next(p["price"] for p in plat.get("/api/admin/billing/products").json() if p["code"] == "start")
    plat.post(f"/api/admin/billing/account/subscriptions?tenant_id={t['id']}",
              json={"product": "start", "start": crm.today().isoformat()})
    c = plat.post(f"{B}/companies", json={"name": "CRM Kunde"}).json()
    r = plat.patch(f"{B}/companies/{c['id']}", json={"link": f"tenant:{t['id']}", "status": "kunde"}).json()
    assert r["linked"]["name"] == "CRM Kunde ApS" and r["linked"]["mrr"] == price
    assert any(x["text"].startswith("Oprettet i Nodd") for x in r["timeline"])
    assert next(x for x in plat.get(f"{B}/companies").json() if x["id"] == c["id"])["mrr"] == price
    assert any(o["value"] == f"tenant:{t['id']}" for o in plat.get(f"{B}/nodd-options").json())
    other = plat.post(f"{B}/companies", json={"name": "Dublet"}).json()
    assert plat.patch(f"{B}/companies/{other['id']}", json={"link": f"tenant:{t['id']}"}).status_code == 409
    assert plat.patch(f"{B}/companies/{other['id']}", json={"link": "tenant:999999"}).status_code == 404
    assert plat.patch(f"{B}/companies/{other['id']}", json={"link": "noget"}).status_code == 422

    # Slettes firmaet i Nodd, bliver det i CRM som tidligere kunde.
    plat.delete(f"/api/admin/tenants/{t['id']}")
    after = plat.get(f"{B}/companies/{c['id']}").json()
    assert after["linked"] is None and after["status"] == "tidligere"
    assert any(x["text"] == "Firmaet er slettet i Nodd" for x in after["timeline"])
    plat.delete(f"{B}/companies/{c['id']}")
    plat.delete(f"{B}/companies/{other['id']}")


def test_sync_from_nodd_is_idempotent(plat):
    partner = plat.post("/api/admin/partners", json={"name": "CRM Huset"}).json()
    under = plat.post("/api/admin/tenants", json={"name": "Firma i huset", "partner_id": partner["id"]}).json()
    alone = plat.post("/api/admin/tenants", json={"name": "Selvstændigt firma"}).json()
    assert plat.post(f"{B}/sync").json()["created"] >= 2
    names = {r["name"]: r for r in plat.get(f"{B}/companies").json()}
    assert names["CRM Huset"]["segment"] == "kontorhotel" and names["CRM Huset"]["linked"]
    assert "Selvstændigt firma" in names and "Firma i huset" not in names  # hører med til huset
    assert plat.post(f"{B}/sync").json()["created"] == 0
    assert plat.get(f"{B}/overview").json()["unlinked"] == 0
    house = plat.get(f"{B}/companies/{names['CRM Huset']['id']}").json()
    assert house["linked"]["firms"] == 1
    plat.delete(f"/api/admin/tenants/{under['id']}")
    plat.delete(f"/api/admin/tenants/{alone['id']}")
    plat.delete(f"/api/admin/partners/{partner['id']}")
    assert plat.get(f"{B}/companies/{house['id']}").json()["status"] == "tidligere"


def test_morning_digest_once_a_day(plat, monkeypatch):
    c = plat.post(f"{B}/companies", json={"name": "Morgenfirma"}).json()
    plat.post(f"{B}/companies/{c['id']}/activities", json={"kind": "opgave", "text": "Følg op på demo"})
    with SessionLocal() as db:
        subject, text = crm.digest_text(db)
    assert "opfølgning" in subject and "Morgenfirma: Følg op på demo (i dag)" in text and "/admin#crm" in text
    monkeypatch.setattr(crm.settings, "ops_email", "mads@example.com")
    day = crm.today() + timedelta(days=4000)  # en dag, ingen andre tests bruger
    assert crm.send_digest(SessionLocal, day) == "test"  # testtilstand: intet sendes
    assert crm.send_digest(SessionLocal, day) == "allerede"
    with SessionLocal() as db:
        db.query(ReportRun).filter(ReportRun.scope == "crm").delete()
        db.commit()
    monkeypatch.setattr(crm.settings, "ops_email", "")
    assert crm.send_digest(SessionLocal, day) == "ingen modtager"
    plat.delete(f"{B}/companies/{c['id']}")
