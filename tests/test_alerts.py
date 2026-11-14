"""Nødbesked på alle skærme: rækkevidde (firma/hus), prioritet, udløb, evakueringslisten og adgang."""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app import alerts, ratelimit
from app.db import SessionLocal
from app.main import app
from app.models import EmergencyAlert, utcnow


@pytest.fixture(scope="module")
def plat(client):
    c = TestClient(app)
    assert c.post("/api/admin/login", json={"password": "hemmelig"}).status_code == 200
    return c


@pytest.fixture()
def house(plat):
    ratelimit.reset()
    partner = plat.post("/api/admin/partners", json={"name": "Alarmhuset"}).json()
    plat.post(f"/api/admin/billing/account/subscriptions?partner_id={partner['id']}", json={"product": "hus"})
    a = plat.post("/api/admin/tenants", json={"name": "Alarm A", "partner_id": partner["id"]}).json()
    b = plat.post("/api/admin/tenants", json={"name": "Alarm B", "partner_id": partner["id"]}).json()
    out = plat.post("/api/admin/tenants", json={"name": "Udenfor huset"}).json()
    room = plat.post("/api/admin/rooms", json={"partner_id": partner["id"], "name": "Husets sal"}).json()
    sig = plat.post("/api/admin/signage", json={"partner_id": partner["id"], "name": "Foyer"}).json()
    yield {"partner": partner, "a": a, "b": b, "out": out, "room": room, "sig": sig}
    for t in (a, b, out):
        plat.delete(f"/api/admin/tenants/{t['id']}")
    plat.delete(f"/api/admin/partners/{partner['id']}")


def screen(plat, kind, token):
    r = plat.get(f"/api/alert/{kind}/{token}")
    assert r.status_code == 200
    return r.json()["alert"]


def tokens(h):
    return {"kiosk_a": ("k", h["a"]["kiosk_token"]), "kiosk_b": ("k", h["b"]["kiosk_token"]),
            "room": ("room", h["room"]["screen_url"].split("/room/")[1]), "sig": ("s", h["sig"]["token"]),
            "out": ("k", h["out"]["kiosk_token"])}


def test_house_alert_reaches_all_house_screens(plat, house):
    tk = tokens(house)
    assert all(screen(plat, *v) is None for v in tk.values())
    r = plat.post("/api/admin/alerts", json={"partner_id": house["partner"]["id"], "kind": "evacuation"})
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "Evakuering" and "nødudgang" in r.json()["message"]
    assert r.json()["screens"] == 4  # to firmaers gæsteskærme, lokaleskærmen og infoskærmen
    for name in ("kiosk_a", "kiosk_b", "room", "sig"):
        a = screen(plat, *tk[name])
        assert a and a["kind"] == "evacuation", name
    assert screen(plat, *tk["out"]) is None  # et firma uden for huset
    listed = plat.get(f"/api/admin/alerts?partner_id={house['partner']['id']}").json()
    assert listed["active"][0]["created_by"] == "Leverandør" and listed["screens"] == 4
    assert plat.post(f"/api/admin/alerts/{r.json()['id']}/end").status_code == 200
    assert screen(plat, *tk["kiosk_a"]) is None and screen(plat, *tk["room"]) is None


def test_firm_alert_priority_and_expiry(plat, house):
    tk = tokens(house)
    pid, a = house["partner"]["id"], house["a"]
    plat.post("/api/admin/alerts", json={"partner_id": pid, "kind": "info", "title": "Elevatoren er i stykker"})
    plat.post("/api/admin/alerts", json={"tenant_id": a["id"], "kind": "warning", "title": "Vandskade på 2. sal",
                                         "message": "Brug trappen i østfløjen"})
    assert screen(plat, *tk["kiosk_a"])["title"] == "Vandskade på 2. sal"  # den vigtigste vinder
    assert screen(plat, *tk["kiosk_b"])["title"] == "Elevatoren er i stykker"  # firmabeskeden gælder kun firmaet
    # En ny besked i samme omfang afløser den gamle.
    plat.post("/api/admin/alerts", json={"tenant_id": a["id"], "kind": "info", "title": "Kantinen lukker kl. 13"})
    hist = plat.get(f"/api/admin/alerts?tenant_id={a['id']}").json()
    assert len(hist["active"]) == 1 and hist["active"][0]["title"] == "Kantinen lukker kl. 13"
    # Udløb af sig selv.
    plat.post("/api/admin/alerts", json={"partner_id": pid, "kind": "warning", "title": "Strømsvigt", "minutes": 30})
    assert screen(plat, *tk["kiosk_b"])["title"] == "Strømsvigt"
    with SessionLocal() as db:
        for row in db.query(EmergencyAlert).filter(EmergencyAlert.partner_id == pid, EmergencyAlert.ended_at.is_(None)):
            row.ends_at = utcnow() - timedelta(minutes=1)
        db.commit()
        alerts.refresh(db)
    assert screen(plat, *tk["kiosk_b"]) is None
    assert plat.post("/api/admin/alerts", json={"partner_id": pid, "kind": "brand"}).status_code == 422
    assert plat.post("/api/admin/alerts", json={"kind": "info"}).status_code == 422


def test_evacuation_from_evac_list(plat, house):
    tk = tokens(house)
    url = plat.get(f"/api/admin/partners/{house['partner']['id']}/evac-link").json()["url"]
    tok = url.split("/e/")[1]
    assert plat.get(f"/api/evac/{tok}/alert").json() == {"active": False}
    r = plat.post(f"/api/evac/{tok}/alert", json={"action": "start"})
    assert r.status_code == 200 and r.json()["active"] and r.json()["screens"] == 4
    assert screen(plat, *tk["kiosk_b"])["kind"] == "evacuation"
    assert plat.get(f"/api/evac/{tok}/alert").json() == {"active": True}
    hist = plat.get(f"/api/admin/alerts?partner_id={house['partner']['id']}").json()["history"]
    assert hist[0]["created_by"] == "Evakueringslisten"
    plat.post(f"/api/evac/{tok}/alert", json={"action": "end"})
    assert screen(plat, *tk["kiosk_b"]) is None
    assert plat.post("/api/evac/forkert/alert", json={"action": "start"}).status_code == 404


def test_unknown_screens_and_new_links(plat, house):
    assert screen(plat, "k", "findesikke") is None
    assert plat.get("/api/alert/x/abc").status_code == 422
    a = house["a"]
    plat.post("/api/admin/alerts", json={"tenant_id": a["id"], "kind": "evacuation"})
    old = a["kiosk_token"]
    assert screen(plat, "k", old)
    new = plat.post(f"/api/admin/tenants/{a['id']}/new-link").json()["kiosk_token"]
    assert screen(plat, "k", old) is None and screen(plat, "k", new)["kind"] == "evacuation"


def test_tenant_admin_only_own_firm(plat, house):
    a, pid = house["a"], house["partner"]["id"]
    plat.patch(f"/api/admin/tenants/{a['id']}/subscription", json={"self_service": True})
    link = plat.post(f"/api/admin/tenants/{a['id']}/users", json={"email": "admin@alarm-a.dk"}).json()["invite_url"]
    c = TestClient(app)
    c.post("/api/admin/invite/accept", json={"token": link.split("#invite=")[1], "password": "alarm-kode-1234"})
    r = c.post("/api/admin/alerts", json={"tenant_id": a["id"], "kind": "warning", "title": "Brandøvelse kl. 14"})
    assert r.status_code == 200 and r.json()["created_by"] == "admin@alarm-a.dk"
    assert c.post("/api/admin/alerts", json={"partner_id": pid, "kind": "evacuation"}).status_code == 404
    assert c.post("/api/admin/alerts", json={"tenant_id": house["b"]["id"], "kind": "evacuation"}).status_code == 404
    house_alert = plat.post("/api/admin/alerts", json={"partner_id": pid, "kind": "info"}).json()
    assert c.post(f"/api/admin/alerts/{house_alert['id']}/end").status_code == 404
    assert TestClient(app).post("/api/admin/alerts", json={"tenant_id": a["id"]}).status_code == 401


def _log(plat, t):
    return plat.get(f"/api/admin/tenants/{t['id']}/notifications").json()


def test_people_notify_is_off_by_default_and_follows_setting(plat, house):
    pid, a, b = house["partner"]["id"], house["a"], house["b"]
    plat.post(f"/api/admin/tenants/{a['id']}/hosts", json={"name": "Anna", "phone": "20 30 40 50", "email": "anna@a.dk"})
    plat.post(f"/api/admin/tenants/{a['id']}/hosts", json={"name": "Bo", "email": "bo@a.dk"})
    plat.post(f"/api/admin/tenants/{b['id']}/hosts", json={"name": "Anna igen", "phone": "+45 20304050"})  # samme nummer
    gone = plat.post(f"/api/admin/tenants/{b['id']}/hosts", json={"name": "Stoppet", "phone": "99887766"}).json()
    plat.patch(f"/api/admin/hosts/{gone['id']}", json={"active": False})
    plat.patch(f"/api/admin/tenants/{b['id']}", json={"teams_webhook": "https://example.com/teams"})

    # Slukket som standard: notify ignoreres.
    info = plat.get(f"/api/admin/alerts?partner_id={pid}").json()["notify"]
    assert not info["enabled"] and info["sms"] == 1 and info["email"] == 2 and info["teams"] == 1
    r = plat.post("/api/admin/alerts", json={"partner_id": pid, "kind": "evacuation", "notify": True}).json()
    assert not r["notify"]
    assert not any(n["recipient"] in ("20 30 40 50", "anna@a.dk") for n in _log(plat, a))
    plat.post(f"/api/admin/alerts/{r['id']}/end")

    # Huset slår det til. Evakuering sendes til alle én gang; information sendes aldrig.
    assert plat.patch(f"/api/admin/alerts/settings?partner_id={pid}", json={"alert_notify": True}).json()["enabled"]
    r = plat.post("/api/admin/alerts", json={"partner_id": pid, "kind": "evacuation", "notify": True}).json()
    assert r["notify"]
    log_a, log_b = _log(plat, a), _log(plat, b)
    sms = [n for n in log_a + log_b if n["channel"] == "sms" and n["subject"].startswith("Evakuering")]
    assert [n["recipient"] for n in sms] == ["20 30 40 50"]  # samme nummer kun én gang, ikke den stoppede person
    assert sms[0]["body"].startswith("EVAKUERING (Alarmhuset):") and sms[0]["status"] == "test"
    assert {n["recipient"] for n in log_a if n["channel"] == "email" and n["subject"].startswith("Evakuering")} == {"anna@a.dk", "bo@a.dk"}
    assert any(n["channel"] == "teams" for n in log_b)
    listed = plat.get(f"/api/admin/alerts?partner_id={pid}").json()["active"][0]
    assert listed["notified_count"] == 4
    # Afslut: alle får "Afblæst" én gang.
    plat.post(f"/api/admin/alerts/{r['id']}/end")
    plat.post(f"/api/admin/alerts/{r['id']}/end")
    cleared = [n for n in _log(plat, a) + _log(plat, b) if n["subject"].startswith("Afblæst")]
    assert len(cleared) == 4 and any("Du kan vende tilbage" in n["body"] for n in cleared)
    before = len(_log(plat, a))
    plat.post("/api/admin/alerts", json={"partner_id": pid, "kind": "info", "title": "Kaffe", "notify": True})
    assert len(_log(plat, a)) == before


def test_evac_list_follows_setting_and_tenant_admin_cannot_enable(plat, house):
    pid, a = house["partner"]["id"], house["a"]
    plat.post(f"/api/admin/tenants/{a['id']}/hosts", json={"name": "Cia", "phone": "11223344"})
    tok = plat.get(f"/api/admin/partners/{pid}/evac-link").json()["url"].split("/e/")[1]
    plat.post(f"/api/evac/{tok}/alert", json={"action": "start"})
    assert not any(n["recipient"] == "11223344" for n in _log(plat, a))  # slukket
    plat.post(f"/api/evac/{tok}/alert", json={"action": "end"})
    plat.patch(f"/api/admin/alerts/settings?partner_id={pid}", json={"alert_notify": True})
    plat.post(f"/api/evac/{tok}/alert", json={"action": "start"})
    assert any(n["recipient"] == "11223344" and n["subject"].startswith("Evakuering") for n in _log(plat, a))
    plat.post(f"/api/evac/{tok}/alert", json={"action": "end"})
    assert any(n["recipient"] == "11223344" and n["subject"].startswith("Afblæst") for n in _log(plat, a))
    # Firmaets egne admins kan ikke slå SMS til (det koster).
    plat.patch(f"/api/admin/tenants/{a['id']}/subscription", json={"self_service": True})
    link = plat.post(f"/api/admin/tenants/{a['id']}/users", json={"email": "admin@alarm-sms.dk"}).json()["invite_url"]
    c = TestClient(app)
    c.post("/api/admin/invite/accept", json={"token": link.split("#invite=")[1], "password": "alarm-kode-1234"})
    assert c.patch(f"/api/admin/alerts/settings?tenant_id={a['id']}", json={"alert_notify": True}).status_code == 403
    assert c.get(f"/api/admin/alerts?tenant_id={a['id']}").json()["notify"]["enabled"]  # huset har slået det til
