"""Fase 5b: forplejning. Køkkener, menu, bestilling sammen med bookingen, køkkenets side og faktureringsgrundlag."""
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import ratelimit
from app.main import app
from app.timeutil import TZ


def at(hours: float, minutes: int = 0) -> str:
    d = (datetime.now(TZ) + timedelta(hours=hours, minutes=minutes)).replace(second=0, microsecond=0)
    return d.strftime("%Y-%m-%dT%H:%M")


@pytest.fixture(scope="module")
def plat(client):
    c = TestClient(app)
    assert c.post("/api/admin/login", json={"password": "hemmelig"}).status_code == 200
    return c


@pytest.fixture()
def house(plat):
    """Et hus med et lokale og et køkken med tre varer, og to firmaer med hver én person."""
    ratelimit.reset()
    partner = plat.post("/api/admin/partners", json={"name": "Køkkenhuset"}).json()
    mk = lambda name: plat.post("/api/admin/tenants", json={"name": name, "partner_id": partner["id"]}).json()  # noqa: E731
    a, b = mk("Alfa ApS"), mk("Beta A/S")
    ha = plat.post(f"/api/admin/tenants/{a['id']}/hosts", json={"name": "Anna Alfa"}).json()
    hb = plat.post(f"/api/admin/tenants/{b['id']}/hosts", json={"name": "Bo Beta"}).json()
    room = plat.post("/api/admin/rooms", json={"partner_id": partner["id"], "name": "Store sal", "location": "Stuen",
                                               "capacity": 20}).json()
    k = plat.post("/api/admin/kitchens", json={"partner_id": partner["id"], "name": "Husets køkken",
                                               "email": "kok@huset.dk", "phone": "33333333", "lead_hours": 2})
    assert k.status_code == 200, k.text
    k = k.json()
    item = lambda d: plat.post(f"/api/admin/kitchens/{k['id']}/items", json=d).json()  # noqa: E731
    sandwich = item({"name": "Sandwich", "category": "Frokost", "price": 75, "unit": "stk.", "tags": ["Vegetar"]})
    kaffe = item({"name": "Kaffe", "category": "Drikkevarer", "price": 60.5, "unit": "kande"})
    gammel = item({"name": "Udgået kage", "price": 30, "active": False})
    link = lambda h: plat.get(f"/api/admin/hosts/{h['id']}/invite-link").json()["url"].split("/i/")[1]  # noqa: E731
    yield {"partner": partner, "a": a, "b": b, "room": room, "k": k, "sandwich": sandwich, "kaffe": kaffe,
           "gammel": gammel, "ta": link(ha), "tb": link(hb)}
    for t in (a, b):
        plat.delete(f"/api/admin/tenants/{t['id']}")
    plat.delete(f"/api/admin/partners/{partner['id']}")


def food(h, items, **kw):
    return {"kitchen_id": h["k"]["id"], "items": [{"item_id": i["id"], "qty": q} for i, q in items], **kw}


def book(plat, h, token="ta", hours=4, **catering):
    return plat.post(f"/api/book/{h[token]}", json={"room_id": h["room"]["id"], "title": "Bestyrelsesmøde",
                                                    "start": at(hours), "end": at(hours + 2), "attendees": 8,
                                                    "catering": catering or None})


def test_menu_is_shown_to_bookers_without_kitchen_contact(plat, house):
    info = plat.get(f"/api/book/{house['ta']}").json()
    assert [k["name"] for k in info["kitchens"]] == ["Husets køkken"]
    names = [i["name"] for i in info["kitchens"][0]["items"]]
    assert names == ["Kaffe", "Sandwich"] or set(names) == {"Kaffe", "Sandwich"}
    assert "Udgået kage" not in str(info)  # inaktive varer vises ikke
    assert "kok@huset.dk" not in str(info) and "33333333" not in str(info) and "order_token" not in str(info)
    assert house["kaffe"]["price"] == 6050 and house["kaffe"]["price_text"] == "60,50 kr."


def test_order_with_booking_notifies_kitchen_without_title(plat, house):
    r = book(plat, house, **food(house, [(house["sandwich"], 8), (house["kaffe"], 2)], note="2 er vegetarer",
                                 cost_center="Salg"))
    assert r.status_code == 200, r.text
    b = r.json()
    o = b["catering"]
    assert o["total"] == 8 * 7500 + 2 * 6050 and o["total_text"] == "721,00 kr." and o["status"] == "new"
    assert [(ln["name"], ln["qty"]) for ln in o["lines"]] == [("Sandwich", 8), ("Kaffe", 2)]
    assert o["deliver_at"][11:16] == at(4)[11:16]  # leveres ved mødets start

    notes = plat.get(f"/api/admin/tenants/{house['a']['id']}/notifications").json()
    kitchen = [n for n in notes if n["recipient"] in ("kok@huset.dk", "33333333")]
    assert {n["channel"] for n in kitchen} == {"email", "sms"}
    mail = next(n for n in kitchen if n["channel"] == "email")
    assert "8 × Sandwich" in mail["body"] and "Store sal (Stuen)" in mail["body"] and "Alfa ApS" in mail["body"]
    assert "Bestyrelsesmøde" not in str(kitchen)  # køkkenet ser ikke mødets titel
    assert "/kitchen/" in mail["body"]

    # Køkkenets side viser bestillingen, uden titel.
    tok = house["k"]["kitchen_url"].split("/kitchen/")[1]
    day = plat.get(f"/api/kitchen/{tok}?date={at(4)[:10]}").json()
    assert len(day["orders"]) == 1 and "Bestyrelsesmøde" not in str(day)
    assert day["orders"][0]["room"] == "Store sal" and day["orders"][0]["attendees"] == 8
    assert day["orders"][0]["firm"] == "Alfa ApS" and day["orders"][0]["cost_center"] == "Salg"
    # Køkkenet bekræfter, og den der bookede kan se det.
    oid = day["orders"][0]["id"]
    assert plat.post(f"/api/kitchen/{tok}/orders/{oid}", json={"status": "confirmed"}).json()["status"] == "confirmed"
    mine = plat.get(f"/api/book/{house['ta']}?date={at(4)[:10]}").json()["bookings"]
    assert mine[0]["catering"]["status_text"] == "Bekræftet"
    assert plat.post(f"/api/kitchen/forkert/orders/{oid}", json={"status": "delivered"}).status_code == 404

    # Et andet firma ser hverken titel eller forplejning.
    other = plat.get(f"/api/book/{house['tb']}?date={at(4)[:10]}").json()["bookings"]
    assert other[0]["catering"] is None and other[0]["title"] == "Optaget"


def test_change_and_cancel(plat, house):
    b = book(plat, house, **food(house, [(house["sandwich"], 4)])).json()
    tok = house["k"]["kitchen_url"].split("/kitchen/")[1]
    oid = b["catering"]["id"]
    plat.post(f"/api/kitchen/{tok}/orders/{oid}", json={"status": "confirmed"})
    # Ændring: køkkenet skal bekræfte igen.
    later = at(4, 30) if at(4, 30)[:10] == at(4)[:10] else at(4)  # samme dag som mødet, også tæt på midnat
    r = plat.put(f"/api/book/{house['ta']}/{b['id']}/catering", json=food(house, [(house["kaffe"], 3)], deliver_at=later[11:16]))
    assert r.status_code == 200, r.text
    o = r.json()["catering"]
    assert o["status"] == "new" and o["lines"][0]["name"] == "Kaffe" and o["deliver_at"][11:16] == later[11:16]
    # Levering skal ligge omkring mødet.
    assert plat.put(f"/api/book/{house['ta']}/{b['id']}/catering",
                    json=food(house, [(house["kaffe"], 3)], deliver_at=at(8)[11:16])).status_code == 422
    # Andre kan ikke rette i bestillingen.
    assert plat.put(f"/api/book/{house['tb']}/{b['id']}/catering", json=food(house, [(house["kaffe"], 1)])).status_code == 404
    # Aflyses bookingen, annulleres bestillingen, og køkkenet får besked.
    assert plat.delete(f"/api/book/{house['ta']}/{b['id']}").status_code == 200
    day = plat.get(f"/api/kitchen/{tok}?date={at(4)[:10]}").json()
    assert day["orders"][0]["status"] == "cancelled"
    notes = plat.get(f"/api/admin/tenants/{house['a']['id']}/notifications").json()
    assert any(n["subject"].startswith("Annulleret bestilling") for n in notes)

    # Forplejning kan fjernes fra en booking, der står ved magt.
    b2 = book(plat, house, hours=10, **food(house, [(house["sandwich"], 2)])).json()
    r = plat.put(f"/api/book/{house['ta']}/{b2['id']}/catering", json={"kitchen_id": house["k"]["id"], "items": []})
    assert r.json()["catering"] is None
    # ...og tilføjes igen bagefter.
    r = plat.put(f"/api/book/{house['ta']}/{b2['id']}/catering", json=food(house, [(house["kaffe"], 1)]))
    assert r.json()["catering"]["lines"][0]["name"] == "Kaffe"


def test_order_rules(plat, house):
    # For kort varsel (køkkenet vil have 2 timer).
    r = book(plat, house, hours=1, **food(house, [(house["sandwich"], 2)]))
    assert r.status_code == 422 and "2 timer" in r.json()["detail"]
    # Bookingen bliver heller ikke oprettet, når forplejningen fejler.
    day = plat.get(f"/api/book/{house['ta']}?date={at(1)[:10]}").json()
    assert not any(x["start"][11:16] == at(1)[11:16] for x in day["bookings"])
    # Inaktive varer og varer fra et andet køkken kan ikke bestilles.
    assert book(plat, house, **food(house, [(house["gammel"], 1)])).status_code == 422
    own = plat.post("/api/admin/kitchens", json={"tenant_id": house["b"]["id"], "name": "Betas tekøkken"}).json()
    kage = plat.post(f"/api/admin/kitchens/{own['id']}/items", json={"name": "Betakage", "price": 10}).json()
    r = book(plat, house, kitchen_id=own["id"], items=[{"item_id": kage["id"], "qty": 1}])
    assert r.status_code == 404  # Alfa kan ikke bestille fra Betas køkken
    assert [k["name"] for k in plat.get(f"/api/book/{house['ta']}").json()["kitchens"]] == ["Husets køkken"]
    assert {k["name"] for k in plat.get(f"/api/book/{house['tb']}").json()["kitchens"]} == {"Husets køkken", "Betas tekøkken"}
    # Et slået-fra køkken kan ikke bruges.
    plat.patch(f"/api/admin/kitchens/{house['k']['id']}", json={"active": False})
    assert book(plat, house, **food(house, [(house["sandwich"], 1)])).status_code == 404
    assert plat.get(f"/api/book/{house['ta']}").json()["kitchens"] == []


def test_billing_csv_and_kitchen_link(plat, house):
    book(plat, house, **food(house, [(house["sandwich"], 3)], cost_center="Marketing"))
    book(plat, house, token="tb", hours=7, **food(house, [(house["kaffe"], 1)]))
    month = at(4)[:7]
    pid = house["partner"]["id"]
    allm = plat.get(f"/api/admin/catering-orders?partner_id={pid}&month={month}").json()
    assert allm["count"] == 2 and allm["total"] == 3 * 7500 + 6050
    alfa = plat.get(f"/api/admin/catering-orders?tenant_id={house['a']['id']}&month={month}").json()
    assert alfa["count"] == 1 and alfa["orders"][0]["firm"] == "Alfa ApS"
    csv = plat.get(f"/api/admin/catering-orders?partner_id={pid}&month={month}&format=csv")
    assert csv.headers["content-type"].startswith("text/csv")
    assert "Marketing" in csv.text and "225,00" in csv.text and "Bestyrelsesmøde" not in csv.text
    # Nyt link til køkkenet: det gamle holder op med at virke.
    old = house["k"]["kitchen_url"].split("/kitchen/")[1]
    new = plat.post(f"/api/admin/kitchens/{house['k']['id']}/link").json()["kitchen_url"].split("/kitchen/")[1]
    assert new != old
    assert plat.get(f"/api/kitchen/{old}").status_code == 404
    assert plat.get(f"/api/kitchen/{new}").status_code == 200


def test_sample_menu_and_item_edits(plat, house):
    k = plat.post("/api/admin/kitchens", json={"partner_id": house["partner"]["id"], "name": "Kantinen", "kind": "external"}).json()
    k = plat.post(f"/api/admin/kitchens/{k['id']}/sample-menu").json()
    assert len(k["items"]) >= 6 and any(i["category"] == "Frokost" for i in k["items"])
    i = k["items"][0]
    r = plat.patch(f"/api/admin/menu-items/{i['id']}", json={"price": 49.95, "tags": ["Vegansk"], "active": False})
    assert r.json()["price"] == 4995 and r.json()["tags"] == ["Vegansk"] and not r.json()["active"]
    assert plat.patch(f"/api/admin/menu-items/{i['id']}", json={"unit": "spand"}).status_code == 422
    assert plat.delete(f"/api/admin/menu-items/{i['id']}").status_code == 200
    assert plat.delete(f"/api/admin/kitchens/{k['id']}").status_code == 200


def test_kitchen_admin_access(plat, house):
    a, b, pid = house["a"], house["b"], house["partner"]["id"]
    plat.patch(f"/api/admin/tenants/{b['id']}/subscription", json={"self_service": True})
    link = plat.post(f"/api/admin/tenants/{b['id']}/users", json={"email": "admin@beta-kok.dk"}).json()["invite_url"]
    c = TestClient(app)
    c.post("/api/admin/invite/accept", json={"token": link.split("#invite=")[1], "password": "beta-kode-1234"})
    seen = c.get(f"/api/admin/kitchens?tenant_id={b['id']}").json()
    assert [k["name"] for k in seen] == ["Husets køkken"] and not seen[0]["can_manage"]
    assert "kok@huset.dk" not in str(seen) and "kitchen_url" not in seen[0]
    k = house["k"]["id"]
    assert c.patch(f"/api/admin/kitchens/{k}", json={"name": "Hacket"}).status_code == 404
    assert c.post(f"/api/admin/kitchens/{k}/items", json={"name": "X"}).status_code == 404
    assert c.patch(f"/api/admin/menu-items/{house['sandwich']['id']}", json={"price": 1}).status_code == 404
    assert c.delete(f"/api/admin/menu-items/{house['sandwich']['id']}").status_code == 404
    assert c.post(f"/api/admin/kitchens/{k}/link").status_code == 404
    assert c.get(f"/api/admin/kitchens?tenant_id={a['id']}").status_code == 404
    assert c.get(f"/api/admin/catering-orders?partner_id={pid}").status_code == 404
    assert c.get(f"/api/admin/catering-orders?tenant_id={a['id']}").status_code == 404
    assert c.post("/api/admin/kitchens", json={"partner_id": pid, "name": "X"}).status_code == 404
    own = c.post("/api/admin/kitchens", json={"tenant_id": b["id"], "name": "Betas eget"})
    assert own.status_code == 200
    # Beta ser kun sine egne bestillinger i faktureringsgrundlaget.
    book(plat, house, **food(house, [(house["sandwich"], 1)]))
    assert c.get(f"/api/admin/catering-orders?tenant_id={b['id']}&month={at(4)[:7]}").json()["count"] == 0
    assert TestClient(app).get(f"/api/admin/kitchens?tenant_id={b['id']}").status_code == 401


def test_delete_tenant_and_partner_clean_up(plat, house):
    b = house["b"]
    own = plat.post("/api/admin/kitchens", json={"tenant_id": b["id"], "name": "Betas køkken"}).json()
    plat.post(f"/api/admin/kitchens/{own['id']}/items", json={"name": "Te", "price": 5})
    book(plat, house, token="tb", **food(house, [(house["kaffe"], 1)]))
    assert plat.delete(f"/api/admin/tenants/{b['id']}").status_code == 200
    tok = house["k"]["kitchen_url"].split("/kitchen/")[1]
    assert plat.get(f"/api/kitchen/{tok}?date={at(4)[:10]}").json()["orders"] == []
