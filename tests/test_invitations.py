"""Fase 3: forventede gæster med kode og QR, værtens invitationslink og QR-plakat."""
import re
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import presence, ratelimit
from app.main import app


def soon(hours=1):
    return (datetime.now() + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M")


@pytest.fixture(scope="module")
def plat(client):
    c = TestClient(app)
    assert c.post("/api/admin/login", json={"password": "hemmelig"}).status_code == 200
    return c


@pytest.fixture()
def firm(plat):
    t = plat.post("/api/admin/tenants", json={"name": "Invitation ApS"}).json()
    h = plat.post(f"/api/admin/tenants/{t['id']}/hosts", json={"name": "Ida Inviter", "email": "ida@inv.dk",
                                                                 "phone": "20304050"}).json()
    yield t, h
    plat.delete(f"/api/admin/tenants/{t['id']}")


def test_admin_invites_guest_who_checks_in_with_code(plat, firm):
    t, h = firm
    r = plat.post(f"/api/admin/tenants/{t['id']}/invitations", json={
        "host_id": h["id"], "guest_name": "Gerda Gæst", "guest_phone": "11223344", "guest_email": "Gerda@Gaest.dk",
        "guest_company": "Gæst A/S", "expected_at": soon()})
    assert r.status_code == 200, r.text
    inv = r.json()
    assert re.fullmatch(r"\d{6}", inv["code"]) and inv["status"] == "pending" and "/g/" in inv["guest_url"]
    assert inv["guest_email"] == "gerda@gaest.dk" and inv["created_by"] == "Leverandør"

    notes = plat.get(f"/api/admin/tenants/{t['id']}/notifications").json()
    sms = next(n for n in notes if n["recipient"] == "11223344")
    mail = next(n for n in notes if n["recipient"] == "gerda@gaest.dk")
    assert inv["code"] in sms["body"] and "/g/" in sms["body"] and "Ida" in sms["body"]
    assert inv["code"] in mail["body"] and "Du er ventet hos Invitation ApS" in mail["subject"]

    token = inv["guest_url"].split("/g/")[1]
    assert plat.get(f"/g/{token}").status_code == 200
    g = plat.get(f"/api/guest/{token}").json()
    assert g["code"] == inv["code"] and g["qr"].startswith("<svg") and g["host"] == "Ida Inviter"

    upcoming = plat.get(f"/api/admin/tenants/{t['id']}/invitations").json()
    assert [x["id"] for x in upcoming] == [inv["id"]]

    tok = t["kiosk_token"]
    pre = plat.post(f"/api/kiosk/{tok}/code", json={"code": inv["code"]}).json()
    assert pre["host_id"] == h["id"] and pre["guest_name"] == "Gerda Gæst" and pre["guest_company"] == "Gæst A/S"
    r = plat.post(f"/api/kiosk/{tok}/checkin", json={"host_id": h["id"], "guest_name": "Gerda Gæst",
                                                        "guest_phone": "11223344", "invitation_code": inv["code"]})
    assert r.status_code == 200
    # Koden er brugt og virker ikke igen.
    assert plat.post(f"/api/kiosk/{tok}/code", json={"code": inv["code"]}).status_code == 404
    assert plat.get(f"/api/guest/{token}").json()["status"] == "used"
    assert plat.get(f"/api/admin/tenants/{t['id']}/invitations").json() == []
    all_ = plat.get(f"/api/admin/tenants/{t['id']}/invitations?all=true").json()
    assert all_[0]["status"] == "used"


def test_validation_and_cancel(plat, firm):
    t, h = firm
    base = {"host_id": h["id"], "guest_name": "X", "guest_phone": "11223344"}
    past = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")
    assert plat.post(f"/api/admin/tenants/{t['id']}/invitations", json={**base, "expected_at": past}).status_code == 422
    assert plat.post(f"/api/admin/tenants/{t['id']}/invitations", json={**base, "expected_at": "i morgen"}).status_code == 422
    r = plat.post(f"/api/admin/tenants/{t['id']}/invitations", json={"guest_name": "Uden kontakt", "expected_at": soon()})
    assert r.status_code == 422
    # Uden at sende må man godt mangle mobil og e-mail.
    inv = plat.post(f"/api/admin/tenants/{t['id']}/invitations", json={"guest_name": "Stille", "expected_at": soon(),
                                                                       "send": False}).json()
    assert inv["host_name"] == "Receptionen"
    plat.delete(f"/api/admin/invitations/{inv['id']}")
    assert plat.post(f"/api/kiosk/{t['kiosk_token']}/code", json={"code": inv["code"]}).status_code == 404
    assert plat.post(f"/api/admin/invitations/{inv['id']}/send").status_code == 409


def test_codes_only_work_on_own_screen_and_are_rate_limited(plat, firm):
    t, h = firm
    inv = plat.post(f"/api/admin/tenants/{t['id']}/invitations", json={
        "host_id": h["id"], "guest_name": "Fremmed", "expected_at": soon(), "send": False}).json()
    other = plat.post("/api/admin/tenants", json={"name": "Anden skærm ApS"}).json()
    ratelimit.reset()
    assert plat.post(f"/api/kiosk/{other['kiosk_token']}/code", json={"code": inv["code"]}).status_code == 404
    for _ in range(14):
        plat.post(f"/api/kiosk/{other['kiosk_token']}/code", json={"code": "000000"})
    assert plat.post(f"/api/kiosk/{other['kiosk_token']}/code", json={"code": inv["code"]}).status_code == 429
    # Den rigtige skærm er ikke ramt.
    assert plat.post(f"/api/kiosk/{t['kiosk_token']}/code", json={"code": inv["code"]}).status_code == 200
    ratelimit.reset()
    plat.delete(f"/api/admin/tenants/{other['id']}")


def test_host_invites_from_personal_link(plat, firm):
    t, h = firm
    url = plat.get(f"/api/admin/hosts/{h['id']}/invite-link").json()["url"]
    token = url.split("/i/")[1]
    anon = TestClient(app)  # værten har ikke noget login
    assert anon.get(f"/i/{token}").status_code == 200
    info = anon.get(f"/api/host/{token}").json()
    assert info["host"] == "Ida Inviter" and info["upcoming"] == []
    r = anon.post(f"/api/host/{token}/invitations", json={"guest_name": "Værtens Gæst", "guest_email": "v@g.dk",
                                                           "expected_at": soon(3)})
    assert r.status_code == 200 and r.json()["created_by"] == "Ida Inviter" and r.json()["host_name"] == "Ida Inviter"
    info = anon.get(f"/api/host/{token}").json()
    assert [x["guest_name"] for x in info["upcoming"]] == ["Værtens Gæst"] and info["upcoming"][0]["when"]
    assert anon.delete(f"/api/host/{token}/invitations/{r.json()['id']}").json()["status"] == "cancelled"
    # Nyt link: det gamle virker ikke længere.
    new = plat.post(f"/api/admin/hosts/{h['id']}/invite-link").json()["url"]
    assert new != url
    assert anon.get(f"/api/host/{token}").status_code == 404
    assert anon.get("/api/host/falsk").status_code == 404


def test_tenant_admin_cannot_touch_other_firms_invitations(plat, firm):
    t, h = firm
    inv = plat.post(f"/api/admin/tenants/{t['id']}/invitations", json={"host_id": h["id"], "guest_name": "Hemmelig",
                                                                       "expected_at": soon(), "send": False}).json()
    other = plat.post("/api/admin/tenants", json={"name": "Nabo ApS"}).json()
    plat.patch(f"/api/admin/tenants/{other['id']}/subscription", json={"self_service": True})
    link = plat.post(f"/api/admin/tenants/{other['id']}/users", json={"email": "nabo@nabo.dk"}).json()["invite_url"]
    c = TestClient(app)
    c.post("/api/admin/invite/accept", json={"token": link.split("#invite=")[1], "password": "nabo-kode-123"})
    assert c.get(f"/api/admin/tenants/{t['id']}/invitations").status_code == 404
    assert c.delete(f"/api/admin/invitations/{inv['id']}").status_code == 404
    assert c.get(f"/api/admin/hosts/{h['id']}/invite-link").status_code == 404
    assert c.get(f"/api/admin/tenants/{t['id']}/poster").status_code == 404
    plat.delete(f"/api/admin/tenants/{other['id']}")


def test_poster_and_mobile_checkin_do_not_count_as_screen(plat, firm):
    t, h = firm
    r = plat.get(f"/api/admin/tenants/{t['id']}/poster")
    assert r.status_code == 200 and "<svg" in r.text and f"/k/{t['kiosk_token']}?m=1" in r.text
    presence.reset()
    plat.get(f"/api/kiosk/{t['kiosk_token']}/config?m=1")
    assert plat.get(f"/api/admin/tenants/{t['id']}").json()["screen"]["online"] is False


def test_deleting_host_keeps_invitation(plat, firm):
    t, h = firm
    inv = plat.post(f"/api/admin/tenants/{t['id']}/invitations", json={"host_id": h["id"], "guest_name": "Bliver",
                                                                       "expected_at": soon(), "send": False}).json()
    assert plat.delete(f"/api/admin/hosts/{h['id']}").status_code == 200
    pre = plat.post(f"/api/kiosk/{t['kiosk_token']}/code", json={"code": inv["code"]}).json()
    assert pre["host_id"] is None and pre["host_name"] == "Ida Inviter"
