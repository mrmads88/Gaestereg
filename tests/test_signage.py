"""Fase 8: infoskærme. Blokke følger pakken, diskretion og ingen kontaktoplysninger på skærmen."""
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import ratelimit
from app.db import SessionLocal
from app.main import app
from app.models import Booking, Invitation, utcnow
from app.timeutil import TZ


@pytest.fixture(scope="module")
def plat(client):
    c = TestClient(app)
    assert c.post("/api/admin/login", json={"password": "hemmelig"}).status_code == 200
    return c


def enroll(plat, product, **scope):
    q = "&".join(f"{k}={v}" for k, v in scope.items())
    r = plat.post(f"/api/admin/billing/account/subscriptions?{q}", json={"product": product})
    assert r.status_code == 200, r.text


@pytest.fixture()
def firm(plat):
    ratelimit.reset()
    t = plat.post("/api/admin/tenants", json={"name": "Skærmfirma"}).json()
    h = plat.post(f"/api/admin/tenants/{t['id']}/hosts", json={"name": "Anna Vært", "email": "anna@skaerm.dk",
                                                               "phone": "12345678"}).json()
    yield {"t": t, "h": h}
    plat.delete(f"/api/admin/tenants/{t['id']}")


def state(plat, s):
    return plat.get(f"/api/signage/{s['token']}/state")


def test_needs_signage_module(plat, firm):
    t = firm["t"]
    r = plat.post("/api/admin/signage", json={"tenant_id": t["id"], "name": "Lobby"})
    assert r.status_code == 403 and "Infoskærm er ikke slået til" in r.json()["detail"]
    enroll(plat, "signage", tenant_id=t["id"])
    s = plat.post("/api/admin/signage", json={"tenant_id": t["id"], "name": "Lobby"}).json()
    assert [x["type"] for x in s["content"]["slides"]] == ["welcome", "guests"] and s["url"].endswith("/s/" + s["token"])
    st = state(plat, s).json()
    assert st["brand"]["name"] == "Skærmfirma" and st["guests"] == [] and st["screen"]["layout"] == "sidebar"
    listed = plat.get(f"/api/admin/signage?tenant_id={t['id']}").json()
    assert listed["screens"][0]["online"] and listed["modules"]["signage"] and not listed["modules"]["rooms"]
    # Lokale-blokken kræver modulet Mødelokaler.
    r = plat.patch(f"/api/admin/signage/{s['id']}", json={"content": {"slides": [{"type": "rooms"}]}})
    assert r.status_code == 403 and "Mødelokaler" in r.json()["detail"]


def test_guests_rooms_and_discretion(plat, firm):
    t, h = firm["t"], firm["h"]
    enroll(plat, "komplet", tenant_id=t["id"])
    s = plat.post("/api/admin/signage", json={"tenant_id": t["id"], "name": "Reception"}).json()
    room = plat.post("/api/admin/rooms", json={"tenant_id": t["id"], "name": "Mødelokale 1"}).json()
    with SessionLocal() as db:
        db.add(Invitation(tenant_id=t["id"], host_id=h["id"], host_name="Anna Vært", guest_name="Mads Hansen",
                          guest_phone="99999999", guest_email="mads@acme.dk", guest_company="Acme A/S",
                          expected_at=utcnow(), code="123456"))
        db.add(Booking(room_id=room["id"], tenant_id=t["id"], title="Fyringsrunde 1", organizer="Anna",
                       start_at=utcnow() - timedelta(minutes=5), end_at=utcnow() + timedelta(minutes=55)))
        db.commit()
    content = {"slides": [{"type": "guests", "guest_mode": "company"}, {"type": "rooms", "duration": 20}],
               "side": [{"type": "clock"}, {"type": "wifi"}], "ticker": ["  Husk  fredagsbar  ", ""]}
    r = plat.patch(f"/api/admin/signage/{s['id']}", json={"content": content, "theme": "dark", "layout": "full"})
    assert r.status_code == 200, r.text
    assert r.json()["content"]["ticker"] == ["Husk fredagsbar"]
    st = state(plat, s).json()
    assert st["guests"] == [{"time": st["guests"][0]["time"], "name": "", "company": "Acme A/S"}]
    assert st["rooms"][0]["name"] == "Mødelokale 1" and st["rooms"][0]["bookings"][0]["title"] == "Optaget"
    text = str(st)
    for secret in ("Mads", "99999999", "mads@acme.dk", "anna@skaerm.dk", "12345678", "Fyringsrunde"):
        assert secret not in text, secret
    # Fornavn og forbogstav, hvis kunden vælger det.
    content["slides"][0]["guest_mode"] = "first"
    plat.patch(f"/api/admin/signage/{s['id']}", json={"content": content})
    assert state(plat, s).json()["guests"][0]["name"] == "Mads H."


def test_validation_images_and_links(plat, firm, data_dir):
    t = firm["t"]
    enroll(plat, "signage", tenant_id=t["id"])
    s = plat.post("/api/admin/signage", json={"tenant_id": t["id"], "name": "Kantine"}).json()
    bad = [{"slides": [{"type": "image", "image": "../../etc/passwd"}]},
           {"slides": [{"type": "qr", "url": "javascript:alert(1)"}]},
           {"slides": [{"type": "video"}]},
           {"slides": [{"type": "text", "duration": 2}]}]
    for c in bad:
        assert plat.patch(f"/api/admin/signage/{s['id']}", json={"content": c}).status_code == 422, c
    import io

    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), "#3a6").save(buf, "PNG")
    up = plat.post(f"/api/admin/signage/{s['id']}/image", files={"file": ("a.png", buf.getvalue(), "image/png")}).json()
    content = {"slides": [{"type": "image", "image": up["image"], "title": "Sommerfest"},
                          {"type": "menu", "week": ["Lasagne", "Fisk", "", "", "", "", ""]},
                          {"type": "qr", "url": "https://example.com/book", "title": "Book et lokale"}]}
    st_ok = plat.patch(f"/api/admin/signage/{s['id']}", json={"content": content})
    assert st_ok.status_code == 200, st_ok.text
    st = state(plat, s).json()
    assert st["images"][up["image"]] == up["url"] and "<svg" in st["qr"]["https://example.com/book"]
    from pathlib import Path
    media = Path(data_dir) / "media" / up["image"]
    assert media.exists()
    plat.patch(f"/api/admin/signage/{s['id']}", json={"content": {"slides": content["slides"][1:]}})
    assert not media.exists()  # billeder, der fjernes fra skærmen, slettes

    # Nyt link: det gamle holder op med at virke. Slået fra: skærmen svarer 404.
    new = plat.post(f"/api/admin/signage/{s['id']}/link").json()
    assert state(plat, s).status_code == 404 and state(plat, new).status_code == 200
    plat.patch(f"/api/admin/signage/{s['id']}", json={"active": False})
    assert state(plat, new).status_code == 404


def test_module_off_hides_screen_and_cache_follows_invitations(plat, firm):
    t, h = firm["t"], firm["h"]
    enroll(plat, "signage", tenant_id=t["id"])
    s = plat.post("/api/admin/signage", json={"tenant_id": t["id"], "name": "Lobby"}).json()
    assert state(plat, s).json()["guests"] == []
    link = plat.get(f"/api/admin/hosts/{h['id']}/invite-link").json()["url"].split("/i/")[1]
    soon = (datetime.now(TZ) + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M")
    r = plat.post(f"/api/host/{link}/invitations", json={"guest_name": "Bo Gæst", "guest_company": "Bo ApS",
                                                         "expected_at": soon, "send": False})
    assert r.status_code == 200, r.text
    if soon[:10] == datetime.now(TZ).strftime("%Y-%m-%d"):
        assert [g["company"] for g in state(plat, s).json()["guests"]] == ["Bo ApS"]
    acc = plat.get(f"/api/admin/billing/account?tenant_id={t['id']}").json()
    sub = next(x for x in acc["subscriptions"] if x["product"]["code"] == "signage")
    plat.post(f"/api/admin/billing/subscriptions/{sub['id']}/end", json={})
    assert state(plat, s).status_code == 404


def test_house_screen_and_access(plat):
    partner = plat.post("/api/admin/partners", json={"name": "Skærmhuset"}).json()
    enroll(plat, "hus", partner_id=partner["id"])
    a = plat.post("/api/admin/tenants", json={"name": "Husfirma A", "partner_id": partner["id"]}).json()
    plat.post("/api/admin/rooms", json={"partner_id": partner["id"], "name": "Husets sal"})
    s = plat.post("/api/admin/signage", json={"partner_id": partner["id"], "name": "Foyer"}).json()
    plat.patch(f"/api/admin/signage/{s['id']}", json={"content": {"slides": [{"type": "rooms"}]}})
    assert [r["name"] for r in state(plat, s).json()["rooms"]] == ["Husets sal"]
    # Et andet firmas admin kan ikke se eller rette husets skærm.
    other = plat.post("/api/admin/tenants", json={"name": "Udefra"}).json()
    plat.patch(f"/api/admin/tenants/{other['id']}/subscription", json={"self_service": True})
    link = plat.post(f"/api/admin/tenants/{other['id']}/users", json={"email": "admin@udefra-skaerm.dk"}).json()["invite_url"]
    c = TestClient(app)
    c.post("/api/admin/invite/accept", json={"token": link.split("#invite=")[1], "password": "udefra-kode-1234"})
    assert c.patch(f"/api/admin/signage/{s['id']}", json={"name": "Hacket"}).status_code == 404
    assert c.get(f"/api/admin/signage?partner_id={partner['id']}").status_code == 404
    assert c.delete(f"/api/admin/signage/{s['id']}").status_code == 404
    for t in (a, other):
        plat.delete(f"/api/admin/tenants/{t['id']}")
    assert plat.delete(f"/api/admin/partners/{partner['id']}").status_code == 200  # skærmen ryddes op
    assert state(plat, s).status_code == 404
