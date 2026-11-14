"""Moduler under abonnement: Mødelokaler og Forplejning pr. firma og pr. hus."""
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import ratelimit
from app.main import app
from app.timeutil import TZ


def at(hours: float) -> str:
    return (datetime.now(TZ) + timedelta(hours=hours)).replace(second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M")


@pytest.fixture(scope="module")
def plat(client):
    c = TestClient(app)
    assert c.post("/api/admin/login", json={"password": "hemmelig"}).status_code == 200
    return c


@pytest.fixture()
def house(plat):
    ratelimit.reset()
    partner = plat.post("/api/admin/partners", json={"name": "Modulhuset"}).json()
    a = plat.post("/api/admin/tenants", json={"name": "Alfa", "partner_id": partner["id"]}).json()
    b = plat.post("/api/admin/tenants", json={"name": "Beta", "partner_id": partner["id"]}).json()
    ha = plat.post(f"/api/admin/tenants/{a['id']}/hosts", json={"name": "Anna"}).json()
    ta = plat.get(f"/api/admin/hosts/{ha['id']}/invite-link").json()["url"].split("/i/")[1]
    yield {"partner": partner, "a": a, "b": b, "ta": ta}
    for t in (a, b):
        plat.delete(f"/api/admin/tenants/{t['id']}")
    plat.delete(f"/api/admin/partners/{partner['id']}")


def enroll(plat, product, tenant_id=None, partner_id=None):
    q = f"tenant_id={tenant_id}" if tenant_id else f"partner_id={partner_id}"
    r = plat.post(f"/api/admin/billing/account/subscriptions?{q}", json={"product": product})
    assert r.status_code == 200, r.text
    return next(s for s in r.json()["subscriptions"] if s["product"]["code"] == product and s["state"] == "active")


def stop(plat, s):
    assert plat.post(f"/api/admin/billing/subscriptions/{s['id']}/end", json={}).status_code == 200


def test_nothing_without_modules(plat, house):
    pid, a = house["partner"]["id"], house["a"]
    r = plat.post("/api/admin/rooms", json={"partner_id": pid, "name": "Sal"})
    assert r.status_code == 403 and "Mødelokaler er ikke slået til" in r.json()["detail"]
    assert plat.post("/api/admin/kitchens", json={"tenant_id": a["id"], "name": "K"}).status_code == 403
    assert plat.get(f"/api/book/{house['ta']}").status_code == 403
    assert not plat.get(f"/api/host/{house['ta']}").json()["has_rooms"]
    t = plat.get(f"/api/admin/tenants/{a['id']}").json()
    assert not any(m["on"] for m in t["modules"].values()) and set(t["modules"]) >= {"rooms", "catering", "signage"}


def test_house_module_covers_all_firms_and_can_be_turned_off(plat, house):
    pid, a, b = house["partner"]["id"], house["a"], house["b"]
    s = enroll(plat, "rooms", partner_id=pid)
    assert plat.get(f"/api/admin/tenants/{b['id']}").json()["modules"]["rooms"] == {"on": True, "via": "house"}
    room = plat.post("/api/admin/rooms", json={"partner_id": pid, "name": "Sal"}).json()
    own = plat.post("/api/admin/rooms", json={"tenant_id": b["id"], "name": "Betas rum"})
    assert own.status_code == 200  # husets modul dækker også firmaernes egne lokaler
    assert [r["name"] for r in plat.get(f"/api/book/{house['ta']}").json()["rooms"]] == ["Sal"]
    tok = room["screen_url"].split("/room/")[1]
    assert plat.get(f"/api/room/{tok}/state").status_code == 200

    # Slås modulet fra, forsvinder det hele, men intet slettes.
    stop(plat, s)
    assert plat.get(f"/api/room/{tok}/state").status_code == 404
    assert plat.post(f"/api/room/{tok}/book", json={"minutes": 15}).status_code == 404
    assert plat.get(f"/api/book/{house['ta']}").status_code == 403
    enroll(plat, "rooms", partner_id=pid)
    assert plat.get(f"/api/room/{tok}/state").status_code == 200
    assert [r["name"] for r in plat.get(f"/api/book/{house['ta']}").json()["rooms"]] == ["Sal"]


def test_firm_module_only_gives_own_rooms_and_kitchens(plat, house):
    pid, a = house["partner"]["id"], house["a"]
    # Huset har lokaler (fra før), men har ikke modulet nu. Alfa køber selv modulerne.
    hus = enroll(plat, "hus", partner_id=pid)
    plat.post("/api/admin/rooms", json={"partner_id": pid, "name": "Husets sal"})
    hk = plat.post("/api/admin/kitchens", json={"partner_id": pid, "name": "Husets køkken"}).json()
    plat.post(f"/api/admin/kitchens/{hk['id']}/items", json={"name": "Kaffe", "price": 10})
    stop(plat, hus)
    enroll(plat, "komplet", tenant_id=a["id"])
    assert plat.get(f"/api/admin/tenants/{a['id']}").json()["modules"]["rooms"] == {"on": True, "via": "firm"}
    mine = plat.post("/api/admin/rooms", json={"tenant_id": a["id"], "name": "Alfas rum"}).json()
    k = plat.post("/api/admin/kitchens", json={"tenant_id": a["id"], "name": "Alfas tekøkken"}).json()
    item = plat.post(f"/api/admin/kitchens/{k['id']}/items", json={"name": "Te", "price": 5}).json()
    info = plat.get(f"/api/book/{house['ta']}").json()
    assert [r["name"] for r in info["rooms"]] == ["Alfas rum"]
    assert [x["name"] for x in info["kitchens"]] == ["Alfas tekøkken"]
    # Husets køkken kan ikke bruges, og husets køkkenside er lukket.
    r = plat.post(f"/api/book/{house['ta']}", json={"room_id": mine["id"], "start": at(5), "end": at(6), "catering": {
        "kitchen_id": hk["id"], "items": [{"item_id": 1, "qty": 1}]}})
    assert r.status_code == 404
    hk_tok = plat.get(f"/api/admin/kitchens?partner_id={pid}").json()
    hk_tok = next(x for x in hk_tok if x["id"] == hk["id"])["kitchen_url"].split("/kitchen/")[1]
    assert plat.get(f"/api/kitchen/{hk_tok}").status_code == 404
    # Eget lokale med eget køkken virker.
    r = plat.post(f"/api/book/{house['ta']}", json={"room_id": mine["id"], "start": at(5), "end": at(6), "catering": {
        "kitchen_id": k["id"], "items": [{"item_id": item["id"], "qty": 2}]}})
    assert r.status_code == 200, r.text
    assert r.json()["catering"]["total"] == 1000
    # Huset kan ikke oprette lokaler uden eget modul.
    assert plat.post("/api/admin/rooms", json={"partner_id": pid, "name": "Ny sal"}).status_code == 403


def test_only_platform_handles_billing(plat, house):
    pid, a = house["partner"]["id"], house["a"]
    enroll(plat, "rooms", partner_id=pid)
    link = plat.post(f"/api/admin/partners/{pid}/users", json={"email": "hus@modulhuset.dk"}).json()["invite_url"]
    pa = TestClient(app)
    pa.post("/api/admin/invite/accept", json={"token": link.split("#invite=")[1], "password": "hus-kode-1234"})
    assert pa.get(f"/api/admin/billing/account?partner_id={pid}").status_code == 403
    assert pa.post(f"/api/admin/billing/account/subscriptions?tenant_id={a['id']}", json={"product": "catering"}).status_code == 403
    assert pa.get("/api/admin/billing/products").status_code == 403
    mine = pa.get("/api/admin/partners").json()[0]
    assert mine["modules"]["rooms"]["on"] and "34" not in str({k: v for k, v in mine.items() if k != "id"})
    # Huset må selv vælge, hvem der får månedsrapporten.
    r = pa.patch(f"/api/admin/partners/{pid}", json={"report_email": "chef@modulhuset.dk; Bogholderi@modulhuset.dk"})
    assert r.status_code == 200 and r.json()["report_email"] == "chef@modulhuset.dk, Bogholderi@modulhuset.dk"
    assert pa.patch(f"/api/admin/partners/{pid}", json={"report_email": "ikke en mail"}).status_code == 422


def test_self_service_follows_package(plat, house):
    a = house["a"]
    link = plat.post(f"/api/admin/tenants/{a['id']}/users", json={"email": "admin@alfa-modul.dk"}).json()["invite_url"]
    c = TestClient(app)
    r = c.post("/api/admin/invite/accept", json={"token": link.split("#invite=")[1], "password": "alfa-kode-1234"})
    assert r.status_code == 403  # Start har ikke selvbetjening
    enroll(plat, "plus", tenant_id=a["id"])
    c.post("/api/admin/invite/accept", json={"token": link.split("#invite=")[1], "password": "alfa-kode-1234"})
    assert c.post("/api/admin/login", json={"email": "admin@alfa-modul.dk", "password": "alfa-kode-1234"}).status_code == 200
    assert plat.get(f"/api/admin/tenants/{a['id']}").json()["self_service"]
