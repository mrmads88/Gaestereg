"""Tidsregistrering: stempling på skærm og telefon, ugeskema, rettelser med log, godkendelse, eksport og 5 års opbevaring."""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app import ratelimit, timereg
from app.db import SessionLocal
from app.main import app
from app.models import TimeEntry, utcnow

A = "/api/admin"


@pytest.fixture(scope="module")
def plat(client):
    c = TestClient(app)
    assert c.post(f"{A}/login", json={"password": "hemmelig"}).status_code == 200
    return c


@pytest.fixture(autouse=True)
def _limits():
    ratelimit.reset()
    yield
    ratelimit.reset()


def firm_with_staff(plat, name, module=True):
    t = plat.post(f"{A}/tenants", json={"name": name}).json()
    if module:
        plat.post(f"{A}/billing/account/subscriptions?tenant_id={t['id']}",
                  json={"product": "time", "start": (timereg.today() - timedelta(days=40)).isoformat()})
    h = plat.post(f"{A}/tenants/{t['id']}/hosts", json={"name": "Anna Holm", "email": "anna@x.dk", "phone": "12345678"}).json()
    return t, h


def test_module_is_required(plat):
    t, h = firm_with_staff(plat, "Uden tid ApS", module=False)
    plat.patch(f"{A}/hosts/{h['id']}/time", json={"time_enabled": True})  # leverandøren må altid
    assert TestClient(app).get(f"/api/kiosk/{t['kiosk_token']}/config").json()["staff"] == []
    assert TestClient(app).post(f"/api/kiosk/{t['kiosk_token']}/time", json={"host_id": h["id"], "pin": "0000"}).status_code == 404
    path = plat.get(f"{A}/hosts/{h['id']}/time/link").json()["path"]
    assert TestClient(app).get("/api/time/" + path.split("/t/")[1]).status_code == 404
    plat.delete(f"{A}/tenants/{t['id']}")


def test_clock_on_screen_with_pin(plat):
    t, h = firm_with_staff(plat, "Stempel ApS")
    pin = plat.post(f"{A}/hosts/{h['id']}/time/pin").json()["pin"]
    assert len(pin) == 4 and pin.isdigit()
    k = TestClient(app)
    cfg = k.get(f"/api/kiosk/{t['kiosk_token']}/config").json()
    assert cfg["staff"] == [{"id": h["id"], "name": "Anna Holm", "photo_url": ""}]
    assert "anna@x.dk" not in str(cfg["staff"]) and "12345678" not in str(cfg["staff"])
    wrong = "0000" if pin != "0000" else "1111"
    r = k.post(f"/api/kiosk/{t['kiosk_token']}/time", json={"host_id": h["id"], "pin": wrong})
    assert r.status_code == 401
    r = k.post(f"/api/kiosk/{t['kiosk_token']}/time", json={"host_id": h["id"], "pin": pin}).json()
    assert r["state"] == "in" and r["first"] == "Anna"
    r = k.post(f"/api/kiosk/{t['kiosk_token']}/time", json={"host_id": h["id"], "pin": pin}).json()
    assert r["state"] == "out" and r["today"] == "0:00"
    for _ in range(5):
        k.post(f"/api/kiosk/{t['kiosk_token']}/time", json={"host_id": h["id"], "pin": wrong})
    assert k.post(f"/api/kiosk/{t['kiosk_token']}/time", json={"host_id": h["id"], "pin": pin}).status_code == 429
    # Slået fra på skærmen: ingen knap og ingen stempling.
    plat.patch(f"{A}/tenants/{t['id']}/time/settings", json={"time_kiosk": False})
    ratelimit.reset()
    assert k.get(f"/api/kiosk/{t['kiosk_token']}/config").json()["staff"] == []
    assert k.post(f"/api/kiosk/{t['kiosk_token']}/time", json={"host_id": h["id"], "pin": pin}).status_code == 404
    plat.delete(f"{A}/tenants/{t['id']}")


def test_phone_link_and_evacuation_list(plat):
    t, h = firm_with_staff(plat, "Telefon ApS")
    plat.patch(f"{A}/hosts/{h['id']}/time", json={"time_enabled": True, "time_norm_min": 37 * 60})
    tok = plat.get(f"{A}/hosts/{h['id']}/time/link").json()["path"].split("/t/")[1]
    me = TestClient(app)
    d = me.get(f"/api/time/{tok}").json()
    assert d["name"] == "Anna Holm" and not d["inside"] and d["norm"] == 37 * 60 and len(d["days"]) == 7
    assert me.post(f"/api/time/{tok}/clock").json()["state"] == "in"
    assert me.get(f"/api/time/{tok}").json()["inside"]
    with SessionLocal() as db:
        from app.house import evac_token
        from app.models import Tenant
        etok = evac_token("tenant", db.get(Tenant, t["id"]))
    staff = TestClient(app).get(f"/api/evac/{etok}").json()["staff"]
    assert [s["name"] for s in staff] == ["Anna Holm"]
    assert me.post(f"/api/time/{tok}/clock").json()["state"] == "out"
    assert TestClient(app).get(f"/api/evac/{etok}").json()["staff"] == []
    assert TestClient(app).get("/t/" + tok).status_code == 200
    plat.delete(f"{A}/tenants/{t['id']}")


def test_week_edit_log_approve_and_export(plat):
    t, h = firm_with_staff(plat, "Ugeskema ApS")
    plat.patch(f"{A}/hosts/{h['id']}/time", json={"time_enabled": True, "time_norm_min": 37 * 60})
    monday = timereg.monday_of(timereg.today()) - timedelta(days=7)  # sidste uge
    tue = monday + timedelta(days=1)
    e = plat.post(f"{A}/tenants/{t['id']}/time/entries", json={
        "host_id": h["id"], "start": f"{tue}T08:00:00", "end": f"{tue}T16:00:00", "break_min": 30}).json()
    assert e["minutes"] == 450 and e["source"] == "admin" and e["edits"][0]["what"] == "oprettet"
    assert plat.post(f"{A}/tenants/{t['id']}/time/entries", json={
        "host_id": h["id"], "start": f"{tue}T10:00:00", "end": f"{tue}T09:00:00"}).status_code == 422
    r = plat.patch(f"{A}/time/entries/{e['id']}", json={"end": f"{tue}T16:30:00", "note": "Kundemøde"}).json()
    assert r["minutes"] == 480 and r["edits"][-1]["what"] == "rettet" and r["edits"][-1]["by"] == "Leverandøren"
    assert "T16:00" in r["edits"][-1]["from"]["end"] and "T16:30" in r["edits"][-1]["to"]["end"]

    w = plat.get(f"{A}/tenants/{t['id']}/time/week", params={"monday": monday.isoformat()}).json()
    row = next(x for x in w["rows"] if x["host_id"] == h["id"])
    assert row["days"][1] == 480 and row["total"] == 480 and row["diff"] == 480 - 37 * 60 and not row["approved"]
    assert w["week"] == monday.isocalendar()[1] and len(w["days"]) == 7

    # En åben stempling i ugen forhindrer godkendelse.
    o = plat.post(f"{A}/tenants/{t['id']}/time/entries", json={"host_id": h["id"], "start": f"{monday}T09:00:00"}).json()
    assert plat.post(f"{A}/tenants/{t['id']}/time/approve", json={"monday": monday.isoformat()}).status_code == 409
    plat.patch(f"{A}/time/entries/{o['id']}", json={"end": f"{monday}T12:00:00"})
    assert plat.post(f"{A}/tenants/{t['id']}/time/approve", json={"monday": monday.isoformat()}).json()["changed"] == 2
    assert plat.patch(f"{A}/time/entries/{e['id']}", json={"break_min": 0}).status_code == 409  # låst
    assert plat.delete(f"{A}/time/entries/{e['id']}").status_code == 409
    w = plat.get(f"{A}/tenants/{t['id']}/time/week", params={"monday": monday.isoformat()}).json()
    assert next(x for x in w["rows"] if x["host_id"] == h["id"])["approved"]
    assert plat.post(f"{A}/tenants/{t['id']}/time/approve", json={"monday": monday.isoformat(), "approve": False}).json()["changed"] == 2
    assert plat.patch(f"{A}/time/entries/{e['id']}", json={"break_min": 0}).json()["edits"][-2]["what"] == "genåbnet"

    csv = plat.get(f"{A}/tenants/{t['id']}/time/export.csv",
                   params={"start": monday.isoformat(), "end": (monday + timedelta(days=6)).isoformat()})
    assert csv.text.startswith("﻿Medarbejder;Dato;Ind;Ud") and "Anna Holm;" in csv.text and "Kundemøde" in csv.text
    assert "Anna Holm;11,50" in csv.text  # 8,5 + 3 timer
    plat.delete(f"{A}/tenants/{t['id']}")


def test_forgotten_clock_out_auto_break_and_keeping_five_years(plat):
    t, h = firm_with_staff(plat, "Glemsom ApS")
    plat.patch(f"{A}/tenants/{t['id']}/time/settings", json={"time_break_min": 30})
    pin = plat.post(f"{A}/hosts/{h['id']}/time/pin").json()["pin"]
    k = TestClient(app)
    k.post(f"/api/kiosk/{t['kiosk_token']}/time", json={"host_id": h["id"], "pin": pin})
    with SessionLocal() as db:  # stemplet ind for 7 timer siden
        e = db.scalar(__import__("sqlalchemy").select(TimeEntry).where(TimeEntry.host_id == h["id"]))
        e.start_at = utcnow() - timedelta(hours=7)
        db.commit()
    r = k.post(f"/api/kiosk/{t['kiosk_token']}/time", json={"host_id": h["id"], "pin": pin}).json()
    assert r["state"] == "out" and r["today_min"] in range(389, 392)  # 7 timer minus 30 min. pause

    # Glemt udstempling (20 timer gammel): næste stempling er en ny indstempling, og den gamle mangler ud.
    with SessionLocal() as db:
        db.add(TimeEntry(tenant_id=t["id"], host_id=h["id"], name="Anna Holm", start_at=utcnow() - timedelta(hours=20)))
        db.add(TimeEntry(tenant_id=t["id"], host_id=h["id"], name="Anna Holm",
                         start_at=utcnow() - timedelta(days=6 * 365), end_at=utcnow() - timedelta(days=6 * 365 - 1)))
        db.commit()
    assert k.post(f"/api/kiosk/{t['kiosk_token']}/time", json={"host_id": h["id"], "pin": pin}).json()["state"] == "in"
    with SessionLocal() as db:
        assert timereg.purge(db) >= 1
        rows = db.scalars(__import__("sqlalchemy").select(TimeEntry).where(TimeEntry.host_id == h["id"])).all()
        assert len(rows) == 3 and sum(1 for x in rows if timereg.stale(x)) == 1
    # Slettes personen, bliver registreringerne (navnet er kopieret).
    plat.delete(f"{A}/hosts/{h['id']}")
    with SessionLocal() as db:
        assert db.query(TimeEntry).filter(TimeEntry.tenant_id == t["id"]).count() == 3
    plat.delete(f"{A}/tenants/{t['id']}")
    with SessionLocal() as db:
        assert db.query(TimeEntry).filter(TimeEntry.tenant_id == t["id"]).count() == 0
