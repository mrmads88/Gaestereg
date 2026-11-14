"""Fase 5a: mødelokaler, booking, diskretion og lokaleskærmen."""
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import ratelimit, rooms
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
    """Et hus med et fælles lokale og to firmaer, hvor Alfa også har sit eget lokale."""
    ratelimit.reset()
    partner = plat.post("/api/admin/partners", json={"name": "Lokalehuset"}).json()
    plat.post(f"/api/admin/billing/account/subscriptions?partner_id={partner['id']}", json={"product": "rooms"})
    mk = lambda name: plat.post("/api/admin/tenants", json={"name": name, "partner_id": partner["id"]}).json()  # noqa: E731
    a, b = mk("Alfa ApS"), mk("Beta A/S")
    ha = plat.post(f"/api/admin/tenants/{a['id']}/hosts", json={"name": "Anna Alfa", "phone": "11111111"}).json()
    hb = plat.post(f"/api/admin/tenants/{b['id']}/hosts", json={"name": "Bo Beta", "phone": "22222222"}).json()
    shared = plat.post("/api/admin/rooms", json={"partner_id": partner["id"], "name": "Store sal", "capacity": 20,
                                                 "setups": ["Biograf", "Hestesko"], "equipment": ["Skærm", "Tavle"]})
    assert shared.status_code == 200, shared.text
    own = plat.post("/api/admin/rooms", json={"tenant_id": a["id"], "name": "Alfas mødelokale", "capacity": 6}).json()
    link = lambda h: plat.get(f"/api/admin/hosts/{h['id']}/invite-link").json()["url"].split("/i/")[1]  # noqa: E731
    yield {"partner": partner, "a": a, "b": b, "ha": ha, "hb": hb, "shared": shared.json(), "own": own,
           "ta": link(ha), "tb": link(hb)}
    for t in (a, b):
        plat.delete(f"/api/admin/tenants/{t['id']}")
    plat.delete(f"/api/admin/partners/{partner['id']}")


def screen(plat, room):
    return plat.get(f"/api/room/{room['screen_url'].split('/room/')[1]}/state")


def test_host_books_shared_room_and_others_see_only_busy(plat, house):
    shared = house["shared"]
    r = plat.post(f"/api/book/{house['ta']}", json={"room_id": shared["id"], "title": "Fyringsrunde 1",
                                                    "start": at(1), "end": at(2), "attendees": 4, "setup": "Hestesko",
                                                    "equipment": ["Skærm", "Kaffemaskine"]})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["title"] == "Fyringsrunde 1" and b["organizer"] == "Anna Alfa" and b["equipment"] == ["Skærm"]

    # Alfa ser sit eget møde på bookingsiden, Beta ser kun "Optaget".
    day = at(1)[:10]
    mine = plat.get(f"/api/book/{house['ta']}?date={day}").json()
    assert [x["title"] for x in mine["bookings"]] == ["Fyringsrunde 1"] and mine["bookings"][0]["mine"]
    assert {x["name"] for x in mine["rooms"]} == {"Store sal", "Alfas mødelokale"}
    other = plat.get(f"/api/book/{house['tb']}?date={day}").json()
    assert {x["name"] for x in other["rooms"]} == {"Store sal"}  # Beta kan ikke booke Alfas eget lokale
    assert other["bookings"][0]["title"] == "Optaget" and "Fyringsrunde" not in str(other)
    assert other["bookings"][0]["organizer"] == "" and not other["bookings"][0]["mine"]

    # Lokaleskærmen viser heller ikke titlen (standard er "optaget").
    st = screen(plat, shared).json()
    assert st["room"]["name"] == "Store sal" and "Fyringsrunde" not in str(st) and "Anna" not in str(st)
    assert st["bookings"][0]["title"] == "Optaget"

    # Beta kan ikke aflyse Alfas møde, Anna kan.
    assert plat.delete(f"/api/book/{house['tb']}/{b['id']}").status_code == 404
    assert plat.delete(f"/api/book/{house['ta']}/{b['id']}").status_code == 200
    assert screen(plat, shared).json()["bookings"] == []  # cachen tømmes ved ændringer


def test_overlap_capacity_and_validation(plat, house):
    own, ta = house["own"], house["ta"]
    ok = plat.post(f"/api/book/{ta}", json={"room_id": own["id"], "start": at(3), "end": at(4)})
    assert ok.status_code == 200
    clash = plat.post(f"/api/book/{ta}", json={"room_id": own["id"], "start": at(3, 30), "end": at(5)})
    assert clash.status_code == 409 and "optaget" in clash.json()["detail"]
    # Lige efter det første møde er fint.
    assert plat.post(f"/api/book/{ta}", json={"room_id": own["id"], "start": at(4), "end": at(5)}).status_code == 200
    assert plat.post(f"/api/book/{ta}", json={"room_id": own["id"], "start": at(6), "end": at(6),
                                              }).status_code == 422
    assert plat.post(f"/api/book/{ta}", json={"room_id": own["id"], "start": at(6), "end": at(7),
                                              "attendees": 7}).status_code == 422  # plads til 6
    assert plat.post(f"/api/book/{ta}", json={"room_id": own["id"], "start": at(-3), "end": at(-2)}).status_code == 422
    assert plat.post(f"/api/book/{ta}", json={"room_id": house["shared"]["id"], "start": at(6), "end": at(7),
                                              "setup": "Klasselokale"}).status_code == 422
    # Beta kan ikke booke Alfas lokale, og et ugyldigt link giver 404.
    assert plat.post(f"/api/book/{house['tb']}", json={"room_id": own["id"], "start": at(8), "end": at(9)}).status_code == 404
    assert plat.get("/api/book/forkert-token").status_code == 404


def test_privacy_layers(plat, house):
    shared, partner, a = house["shared"], house["partner"], house["a"]
    plat.post(f"/api/book/{house['ta']}", json={"room_id": shared["id"], "title": "Strategi", "start": at(1),
                                                "end": at(2)})
    label = lambda: screen(plat, shared).json()["bookings"][0]  # noqa: E731
    assert label()["title"] == "Optaget"
    # Huset vælger "arrangør" for alle sine skærme.
    assert plat.patch(f"/api/admin/partners/{partner['id']}", json={"meeting_privacy": "organizer"}).status_code == 200
    assert label()["title"] == "Optaget" and label()["organizer"] == "Anna Alfa" and label()["firm"] == "Alfa ApS"
    # Firmaet vil gerne vise titler på sine møder.
    assert plat.patch(f"/api/admin/tenants/{a['id']}", json={"meeting_privacy": "title"}).status_code == 200
    assert label()["title"] == "Strategi"
    # Men skærmen ved netop dette lokale skjuler alt.
    assert plat.patch(f"/api/admin/rooms/{shared['id']}", json={"privacy": "busy"}).status_code == 200
    assert label() == {**label(), "title": "Optaget", "organizer": "", "firm": ""}


def test_room_screen_quick_book(plat, house):
    own = house["own"]
    tok = own["screen_url"].split("/room/")[1]
    st = plat.get(f"/api/room/{tok}/state").json()
    assert st["bookings"] == [] and st["brand"]["name"] == "Alfa ApS"
    r = plat.post(f"/api/room/{tok}/book", json={"minutes": 30})
    assert r.status_code == 200, r.text
    assert len(plat.get(f"/api/room/{tok}/state").json()["bookings"]) == 1
    assert plat.post(f"/api/room/{tok}/book", json={"minutes": 15}).status_code == 409  # optaget nu
    assert plat.post(f"/api/room/{tok}/book", json={"minutes": 45}).status_code == 422  # kun 15, 30 eller 60
    assert plat.get("/api/room/forkert/state").status_code == 404

    # Nyt skærmlink: det gamle holder op med at virke.
    new = plat.post(f"/api/admin/rooms/{own['id']}/screen-link").json()
    assert new["screen_url"] != own["screen_url"]
    assert plat.get(f"/api/room/{tok}/state").status_code == 404
    # Slås lokalet fra, kan det hverken vises eller bookes.
    plat.patch(f"/api/admin/rooms/{own['id']}", json={"active": False})
    assert screen(plat, new).status_code == 404
    assert plat.post(f"/api/book/{house['ta']}", json={"room_id": own["id"], "start": at(3), "end": at(4)}).status_code == 404


def test_quick_book_stops_at_next_meeting(plat, house):
    shared = house["shared"]
    plat.post(f"/api/book/{house['tb']}", json={"room_id": shared["id"], "start": at(0, 20), "end": at(1)})
    tok = shared["screen_url"].split("/room/")[1]
    r = plat.post(f"/api/room/{tok}/book", json={"minutes": 60})
    assert r.status_code == 200
    assert r.json()["end"][11:16] == at(0, 20)[11:16]


def test_admin_rooms_and_bookings_access(plat, house):
    a, b, partner = house["a"], house["b"], house["partner"]
    # Firma-admin for Beta (selvbetjening).
    plat.patch(f"/api/admin/tenants/{b['id']}/subscription", json={"self_service": True})
    link = plat.post(f"/api/admin/tenants/{b['id']}/users", json={"email": "admin@beta.dk"}).json()["invite_url"]
    c = TestClient(app)
    c.post("/api/admin/invite/accept", json={"token": link.split("#invite=")[1], "password": "beta-kode-1234"})

    listed = c.get(f"/api/admin/rooms?tenant_id={b['id']}").json()
    assert [r["name"] for r in listed] == ["Store sal"] and not listed[0]["can_manage"]
    assert c.get(f"/api/admin/rooms?tenant_id={a['id']}").status_code == 404
    assert c.get(f"/api/admin/rooms?partner_id={partner['id']}").status_code == 404
    assert c.patch(f"/api/admin/rooms/{house['shared']['id']}", json={"name": "Hacket"}).status_code == 404
    assert c.patch(f"/api/admin/rooms/{house['own']['id']}", json={"name": "Hacket"}).status_code == 404
    assert c.post("/api/admin/rooms", json={"partner_id": partner["id"], "name": "X"}).status_code == 404
    assert c.post("/api/admin/rooms", json={"tenant_id": a["id"], "name": "X"}).status_code == 404
    mine = c.post("/api/admin/rooms", json={"tenant_id": b["id"], "name": "Betas rum"})
    assert mine.status_code == 200

    # Alfa booker det fælles lokale. Beta-admin ser kun "Optaget" og kan ikke aflyse.
    day = at(1)[:10]
    alfa = plat.post(f"/api/book/{house['ta']}", json={"room_id": house["shared"]["id"], "title": "Hemmeligt",
                                                       "start": at(1), "end": at(2)}).json()
    seen = c.get(f"/api/admin/bookings?tenant_id={b['id']}&date={day}").json()
    assert seen[0]["title"] == "Optaget" and "Hemmeligt" not in str(seen)
    assert c.delete(f"/api/admin/bookings/{alfa['id']}").status_code == 404
    # Beta booker selv via admin.
    own = c.post("/api/admin/bookings", json={"room_id": house["shared"]["id"], "title": "Betas møde",
                                              "start": at(3), "end": at(4)})
    assert own.status_code == 200 and own.json()["firm"] == "Beta A/S"
    assert c.post("/api/admin/bookings", json={"room_id": house["own"]["id"], "start": at(3),
                                               "end": at(4)}).status_code == 404
    # Platform ser alt. Huset ser firmaernes møder som skærmen, men kan aflyse i sine egne lokaler.
    allp = plat.get(f"/api/admin/bookings?partner_id={partner['id']}&date={day}").json()
    assert "Hemmeligt" in str(allp)
    assert plat.delete(f"/api/admin/bookings/{alfa['id']}").status_code == 200
    c.delete(f"/api/admin/rooms/{mine.json()['id']}")


def test_partner_admin_sees_firm_meetings_discreetly(plat, house):
    partner = house["partner"]
    link = plat.post(f"/api/admin/partners/{partner['id']}/users", json={"email": "hus@lokalehuset.dk"}).json()
    c = TestClient(app)
    c.post("/api/admin/invite/accept", json={"token": link["invite_url"].split("#invite=")[1], "password": "hus-kode-1234"})
    alfa = plat.post(f"/api/book/{house['ta']}", json={"room_id": house["shared"]["id"], "title": "Hemmeligt",
                                                       "start": at(1), "end": at(2)}).json()
    seen = c.get(f"/api/admin/bookings?partner_id={partner['id']}&date={at(1)[:10]}").json()
    assert seen[0]["title"] == "Optaget"
    assert c.delete(f"/api/admin/bookings/{alfa['id']}").status_code == 200  # husets eget lokale
    # Partneren må kun ændre diskretion på huset, ikke navn.
    assert c.patch(f"/api/admin/partners/{partner['id']}", json={"meeting_privacy": "title"}).status_code == 200
    assert c.patch(f"/api/admin/partners/{partner['id']}", json={"name": "Nyt navn"}).status_code == 403


def test_delete_tenant_removes_bookings(plat, house):
    a = house["a"]
    plat.post(f"/api/book/{house['ta']}", json={"room_id": house["shared"]["id"], "start": at(1), "end": at(2)})
    assert plat.delete(f"/api/admin/tenants/{a['id']}").status_code == 200
    assert screen(plat, house["shared"]).json()["bookings"] == []
    rooms.clear_cache()
