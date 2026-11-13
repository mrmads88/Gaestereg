"""Fase 4: husets skærm, hvem er i huset, evakueringsliste, statistik og faste gæster."""
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import app


def soon(hours=1):
    return (datetime.now() + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M")


@pytest.fixture(scope="module")
def plat(client):
    c = TestClient(app)
    assert c.post("/api/admin/login", json={"password": "hemmelig"}).status_code == 200
    return c


@pytest.fixture()
def hotel(plat):
    """Et kontorhotel med husets skærm og to firmaer med hver én person."""
    partner = plat.post("/api/admin/partners", json={"name": "Huset ved Havnen"}).json()
    mk = lambda name: plat.post("/api/admin/tenants", json={"name": name, "partner_id": partner["id"]}).json()  # noqa: E731
    lobby, a, b = mk("Huset (lobby)"), mk("Alfa ApS"), mk("Beta A/S")
    ha = plat.post(f"/api/admin/tenants/{a['id']}/hosts", json={"name": "Anna Alfa", "phone": "11111111"}).json()
    hb = plat.post(f"/api/admin/tenants/{b['id']}/hosts", json={"name": "Bo Beta", "email": "bo@beta.dk"}).json()
    r = plat.patch(f"/api/admin/tenants/{lobby['id']}", json={"house_screen": True, "delivery_enabled": True})
    assert r.status_code == 200 and r.json()["house_screen"]
    yield {"partner": partner, "lobby": lobby, "a": a, "b": b, "ha": ha, "hb": hb}
    for t in (lobby, a, b):
        plat.delete(f"/api/admin/tenants/{t['id']}")
    plat.delete(f"/api/admin/partners/{partner['id']}")


def test_house_screen_shows_firms_and_routes_visit_to_firm(plat, hotel):
    tok = hotel["lobby"]["kiosk_token"]
    cfg = plat.get(f"/api/kiosk/{tok}/config").json()
    assert cfg["house"] and [f["name"] for f in cfg["firms"]] == ["Alfa ApS", "Beta A/S"]  # lobbyen har ingen personer
    assert cfg["firms"][0]["hosts"][0]["name"] == "Anna Alfa" and "phone" not in str(cfg["firms"])

    r = plat.post(f"/api/kiosk/{tok}/checkin", json={"firm_id": hotel["a"]["id"], "host_id": hotel["ha"]["id"],
                                                        "guest_name": "Gæst Hos Alfa", "guest_phone": "22222222"})
    assert r.status_code == 200, r.text
    alfa_visits = plat.get(f"/api/admin/tenants/{hotel['a']['id']}/visits").json()
    assert [v["guest_name"] for v in alfa_visits] == ["Gæst Hos Alfa"]
    assert plat.get(f"/api/admin/tenants/{hotel['lobby']['id']}/visits").json() == []
    notes = plat.get(f"/api/admin/tenants/{hotel['a']['id']}/notifications").json()
    assert any(n["recipient"] == "11111111" for n in notes)
    # Tjek-ud-listen på husets skærm viser gæster fra alle firmaer, og gæsten kan tjekke ud der.
    inside = plat.get(f"/api/kiosk/{tok}/inside").json()
    assert [g["name"] for g in inside] == ["Gæst A."]  # fornavn + efternavnets forbogstav
    assert plat.post(f"/api/kiosk/{tok}/checkout/{inside[0]['id']}").status_code == 200

    # En person fra et andet firma end det valgte afvises, og et firma uden for huset afvises.
    assert plat.post(f"/api/kiosk/{tok}/checkin", json={"firm_id": hotel["a"]["id"], "host_id": hotel["hb"]["id"],
                                                           "guest_name": "Forkert", "guest_phone": "22222222"}).status_code == 404
    outsider = plat.post("/api/admin/tenants", json={"name": "Udenfor"}).json()
    assert plat.post(f"/api/kiosk/{tok}/checkin", json={"firm_id": outsider["id"], "guest_name": "X Y",
                                                           "guest_phone": "22222222"}).status_code == 404
    # Et firmas egen skærm kan ikke bruges som husets skærm.
    assert not plat.get(f"/api/kiosk/{hotel['a']['kiosk_token']}/config").json()["house"]
    plat.delete(f"/api/admin/tenants/{outsider['id']}")


def test_house_screen_rules(plat, hotel):
    lone = plat.post("/api/admin/tenants", json={"name": "Alene"}).json()
    assert plat.patch(f"/api/admin/tenants/{lone['id']}", json={"house_screen": True}).status_code == 422
    plat.delete(f"/api/admin/tenants/{lone['id']}")
    # Kunde-admins må ikke gøre deres skærm til husets skærm.
    a = hotel["a"]
    plat.patch(f"/api/admin/tenants/{a['id']}/subscription", json={"self_service": True})
    link = plat.post(f"/api/admin/tenants/{a['id']}/users", json={"email": "admin@alfa.dk"}).json()["invite_url"]
    c = TestClient(app)
    c.post("/api/admin/invite/accept", json={"token": link.split("#invite=")[1], "password": "alfa-kode-1234"})
    assert c.patch(f"/api/admin/tenants/{a['id']}", json={"house_screen": True}).status_code == 403
    # ...og kan ikke se husets liste eller evakueringslink.
    assert c.get(f"/api/admin/partners/{hotel['partner']['id']}/inside").status_code == 404
    assert c.get(f"/api/admin/partners/{hotel['partner']['id']}/evac-link").status_code == 404
    assert c.get(f"/api/admin/tenants/{hotel['b']['id']}/inside").status_code == 404


def test_codes_and_deliveries_across_firms(plat, hotel):
    tok = hotel["lobby"]["kiosk_token"]
    inv = plat.post(f"/api/admin/tenants/{hotel['b']['id']}/invitations", json={
        "host_id": hotel["hb"]["id"], "guest_name": "Kode Gæst", "expected_at": soon(), "send": False}).json()
    pre = plat.post(f"/api/kiosk/{tok}/code", json={"code": inv["code"]}).json()
    assert pre["firm_id"] == hotel["b"]["id"] and pre["host_id"] == hotel["hb"]["id"]
    r = plat.post(f"/api/kiosk/{tok}/checkin", json={"firm_id": hotel["b"]["id"], "host_id": hotel["hb"]["id"],
                                                        "guest_name": "Kode Gæst", "guest_phone": "33333333",
                                                        "invitation_code": inv["code"]})
    assert r.status_code == 200
    assert plat.get(f"/api/admin/tenants/{hotel['b']['id']}/invitations?all=true").json()[0]["status"] == "used"

    r = plat.post(f"/api/kiosk/{tok}/delivery", json={"firm_id": hotel["a"]["id"], "host_id": hotel["ha"]["id"],
                                                         "courier_company": "GLS"}).json()
    assert r["to"] == "Anna Alfa"
    r = plat.post(f"/api/kiosk/{tok}/delivery", json={"firm_id": hotel["b"]["id"]}).json()
    assert r["to"] == "Beta A/S"
    r = plat.post(f"/api/kiosk/{tok}/delivery", json={}).json()
    assert r["to"] == "Godsmodtagelsen"
    assert any(v["kind"] == "delivery" for v in plat.get(f"/api/admin/tenants/{hotel['a']['id']}/visits").json())


def test_inside_and_evacuation_link(plat, hotel):
    tok = hotel["lobby"]["kiosk_token"]
    for firm, host, name in ((hotel["a"], hotel["ha"], "Ib Inde"), (hotel["b"], hotel["hb"], "Jo Inde")):
        plat.post(f"/api/kiosk/{tok}/checkin", json={"firm_id": firm["id"], "host_id": host["id"], "guest_name": name,
                                                        "guest_phone": "44444444"})
    pid = hotel["partner"]["id"]
    inside = plat.get(f"/api/admin/partners/{pid}/inside").json()
    assert {(g["name"], g["firm"]) for g in inside} == {("Ib Inde", "Alfa ApS"), ("Jo Inde", "Beta A/S")}
    assert inside[0]["phone"] == "44444444"  # fuldt navn og mobil til brandvagten
    assert [g["name"] for g in plat.get(f"/api/admin/tenants/{hotel['a']['id']}/inside").json()] == ["Ib Inde"]

    url = plat.get(f"/api/admin/partners/{pid}/evac-link").json()["url"]
    token = url.split("/e/")[1]
    anon = TestClient(app)
    assert anon.get(f"/e/{token}").status_code == 200
    ev = anon.get(f"/api/evac/{token}").json()
    assert ev["name"] == "Huset ved Havnen" and len(ev["guests"]) == 2
    # Firmaets eget link viser kun firmaets gæster.
    turl = plat.get(f"/api/admin/tenants/{hotel['b']['id']}/evac-link").json()["url"]
    assert [g["name"] for g in anon.get(f"/api/evac/{turl.split('/e/')[1]}").json()["guests"]] == ["Jo Inde"]
    # Nyt link: det gamle virker ikke længere.
    plat.post(f"/api/admin/partners/{pid}/evac-link")
    assert anon.get(f"/api/evac/{token}").status_code == 404
    assert anon.get("/api/evac/falsk").status_code == 404


def test_monthly_stats_and_csv(plat, hotel):
    tok = hotel["lobby"]["kiosk_token"]
    plat.patch(f"/api/admin/tenants/{hotel['lobby']['id']}", json={"group_checkin": True})
    plat.post(f"/api/kiosk/{tok}/checkin", json={"firm_id": hotel["a"]["id"], "host_id": hotel["ha"]["id"],
                                                    "guest_name": "Gruppe En", "guest_phone": "55555555",
                                                    "extra_guests": ["Gruppe To", "Gruppe Tre"]})
    plat.post(f"/api/kiosk/{tok}/delivery", json={"firm_id": hotel["a"]["id"]})
    month = datetime.now().strftime("%Y-%m")
    st = plat.get(f"/api/admin/partners/{hotel['partner']['id']}/stats?months=3").json()
    assert st["months"][-1] == month and len(st["months"]) == 3
    alfa = next(f for f in st["firms"] if f["name"] == "Alfa ApS")
    assert alfa["guests"][-1] == 3 and alfa["deliveries"][-1] == 1
    csv = plat.get(f"/api/admin/partners/{hotel['partner']['id']}/stats?format=csv")
    assert csv.status_code == 200 and "text/csv" in csv.headers["content-type"]
    assert "Alfa ApS;Gæster" in csv.text and csv.text.startswith("﻿Firma;Type")
    # Tallene bliver, selv om besøgene slettes (GDPR).
    for v in plat.get(f"/api/admin/tenants/{hotel['a']['id']}/visits").json():
        plat.delete(f"/api/admin/tenants/{hotel['a']['id']}/visits/{v['id']}")
    st = plat.get(f"/api/admin/tenants/{hotel['a']['id']}/stats").json()
    assert st["firms"][0]["guests"][-1] == 3


def test_recurring_guest_code_works_again_and_again(plat, hotel):
    a, ha = hotel["a"], hotel["ha"]
    until = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    assert plat.post(f"/api/admin/tenants/{a['id']}/invitations", json={
        "host_id": ha["id"], "guest_name": "Henning Håndværker", "expected_at": soon(0), "recurring": True,
        "send": False}).status_code == 422  # mangler slutdato
    inv = plat.post(f"/api/admin/tenants/{a['id']}/invitations", json={
        "host_id": ha["id"], "guest_name": "Henning Håndværker", "guest_phone": "66666666", "expected_at": soon(0),
        "recurring": True, "valid_until": until}).json()
    assert inv["recurring"] and inv["valid_until"].startswith(until)
    sms = next(n for n in plat.get(f"/api/admin/tenants/{a['id']}/notifications").json() if n["recipient"] == "66666666")
    assert "fast gæst" in sms["body"] and inv["code"] in sms["body"]
    tok = a["kiosk_token"]
    for _ in range(2):
        assert plat.post(f"/api/kiosk/{tok}/code", json={"code": inv["code"]}).status_code == 200
        assert plat.post(f"/api/kiosk/{tok}/checkin", json={"host_id": ha["id"], "guest_name": "Henning Håndværker",
                                                               "guest_phone": "66666666",
                                                               "invitation_code": inv["code"]}).status_code == 200
    listed = plat.get(f"/api/admin/tenants/{a['id']}/invitations").json()
    assert [x["status"] for x in listed if x["id"] == inv["id"]] == ["pending"]
    past = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    assert plat.post(f"/api/admin/tenants/{a['id']}/invitations", json={
        "host_id": ha["id"], "guest_name": "For sent", "expected_at": soon(0), "recurring": True,
        "valid_until": past, "send": False}).status_code == 422
