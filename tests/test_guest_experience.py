"""Fase 2: WiFi, pakker, åbningstider, flere gæster, husregler, værtens svar, påmindelse og Teams."""
import re

import pytest
from fastapi.testclient import TestClient

from app import replies
from app.main import app


@pytest.fixture(scope="module")
def plat(client):
    c = TestClient(app)
    assert c.post("/api/admin/login", json={"password": "hemmelig"}).status_code == 200
    return c


@pytest.fixture()
def firm(plat):
    t = plat.post("/api/admin/tenants", json={"name": "Oplevelse A/S"}).json()
    h = plat.post(f"/api/admin/tenants/{t['id']}/hosts", json={
        "name": "Vera Vært", "email": "vera@oplevelse.dk", "phone": "20304050"}).json()
    plat.patch(f"/api/admin/tenants/{t['id']}", json={"reception_email": "rec@oplevelse.dk", "reception_phone": "70707070"})
    yield t, h
    plat.delete(f"/api/admin/tenants/{t['id']}")


def notes(plat, tid):
    return plat.get(f"/api/admin/tenants/{tid}/notifications").json()


def test_public_config_has_only_what_the_screen_needs(plat, firm):
    t, _ = firm
    plat.patch(f"/api/admin/tenants/{t['id']}", json={
        "wifi_name": "Gæst", "wifi_password": "velkommen123", "delivery_enabled": True,
        "delivery_email": "gods@oplevelse.dk", "delivery_phone": "11112222", "delivery_note": "Læg pakken på hylden",
        "teams_webhook": "https://example.invalid/webhook", "escalate_minutes": 5})
    cfg = plat.get(f"/api/kiosk/{t['kiosk_token']}/config").json()
    assert cfg["wifi_name"] == "Gæst" and cfg["delivery_enabled"] and cfg["delivery_note"] == "Læg pakken på hylden"
    text = str(cfg)
    for secret in ("gods@oplevelse.dk", "11112222", "example.invalid", "rec@oplevelse.dk", "70707070", "vera@", "20304050"):
        assert secret not in text, secret
    assert "escalate_minutes" not in cfg and "teams_webhook" not in cfg


def test_opening_hours_validation(plat, firm):
    t, _ = firm
    week = [["08:00", "16:00"]] * 5 + [None, None]
    r = plat.patch(f"/api/admin/tenants/{t['id']}", json={"opening_hours": week, "closed_text": "Ring 70707070"})
    assert r.status_code == 200 and r.json()["opening_hours"] == week
    assert plat.get(f"/api/kiosk/{t['kiosk_token']}/config").json()["opening_hours"] == week
    for bad in ([["08:00", "16:00"]] * 6, [["16:00", "08:00"]] + [None] * 6, [["8", "16"]] + [None] * 6):
        assert plat.patch(f"/api/admin/tenants/{t['id']}", json={"opening_hours": bad}).status_code == 422
    assert plat.patch(f"/api/admin/tenants/{t['id']}", json={"opening_hours": []}).json()["opening_hours"] == []
    assert plat.patch(f"/api/admin/tenants/{t['id']}", json={"teams_webhook": "http://usikker"}).status_code == 422


def test_group_checkin_and_terms(plat, firm):
    t, h = firm
    tok = t["kiosk_token"]
    body = {"host_id": h["id"], "guest_name": "Anna", "guest_phone": "12345678", "extra_guests": ["Bo", "  Carl  ", ""]}
    # Uden gruppe-check-ind ignoreres de ekstra navne.
    r = plat.post(f"/api/kiosk/{tok}/checkin", json=body).json()
    assert [g["name"] for g in r["guests"]] == ["Anna"]
    plat.patch(f"/api/admin/tenants/{t['id']}", json={"group_checkin": True, "terms_enabled": True,
                                                       "terms_title": "husreglerne", "terms_text": "Bær gæstekort."})
    r = plat.post(f"/api/kiosk/{tok}/checkin", json=body)
    assert r.status_code == 422 and "husreglerne" in r.json()["detail"]
    r = plat.post(f"/api/kiosk/{tok}/checkin", json={**body, "accept_terms": True}).json()
    assert [g["name"] for g in r["guests"]] == ["Anna", "Bo", "Carl"]
    assert len({g["badge_no"] for g in r["guests"]}) == 3
    inside = plat.get(f"/api/kiosk/{tok}/inside").json()
    assert {"Anna", "Bo", "Carl"} <= {g["name"] for g in inside}
    # Værten får én besked med alle tre navne.
    sms = [n for n in notes(plat, t["id"]) if n["channel"] == "sms" and "Bo" in n["body"]]
    assert len(sms) == 1 and "Anna, Bo og Carl" in sms[0]["body"]


def test_host_reply_link_and_kiosk_polling(plat, firm):
    t, h = firm
    tok = t["kiosk_token"]
    r = plat.post(f"/api/kiosk/{tok}/checkin", json={"host_id": h["id"], "guest_name": "Svar Gæst",
                                                        "guest_phone": "12345678"}).json()
    vid = r["visit_id"]
    assert plat.get(f"/api/kiosk/{tok}/reply/{vid}").json()["answer"] is None
    sms = next(n for n in notes(plat, t["id"]) if n["channel"] == "sms" and "Svar Gæst" in n["body"])
    link = re.search(r"https?://\S+/r/(\S+)", sms["body"])
    assert link, sms["body"]
    token = link.group(1)
    page = plat.get(f"/r/{token}")
    assert page.status_code == 200 and "text/html" in page.headers["content-type"]
    info = plat.get(f"/api/reply/{token}").json()
    assert info["guests"] == "Svar Gæst" and info["host"] == "Vera" and info["answer"] is None
    r = plat.post(f"/api/reply/{token}", json={"answer": "5"}).json()
    assert r["answer"] == "5" and "5 minutter" in r["answer_text"]
    k = plat.get(f"/api/kiosk/{tok}/reply/{vid}").json()
    assert k["answer"] == "5" and "5 minutter" in k["text"]
    # En anden skærm kan ikke se svaret.
    other = plat.post("/api/admin/tenants", json={"name": "Anden skærm"}).json()
    assert plat.get(f"/api/kiosk/{other['kiosk_token']}/reply/{vid}").json()["answer"] is None
    plat.delete(f"/api/admin/tenants/{other['id']}")
    assert plat.get("/api/reply/falsk-token").status_code == 404
    assert plat.post(f"/api/reply/{token}", json={"answer": "måske"}).status_code == 422


def test_reply_link_can_be_switched_off(plat, firm):
    t, h = firm
    plat.patch(f"/api/admin/tenants/{t['id']}", json={"host_reply": False})
    plat.post(f"/api/kiosk/{t['kiosk_token']}/checkin", json={"host_id": h["id"], "guest_name": "Uden Link",
                                                                "guest_phone": "12345678"})
    sms = next(n for n in notes(plat, t["id"]) if "Uden Link" in n["body"])
    assert "/r/" not in sms["body"]


def test_host_declines_and_escalation_reaches_reception(plat, firm):
    from app.notify import escalate
    t, h = firm
    tok = t["kiosk_token"]
    vid = plat.post(f"/api/kiosk/{tok}/checkin", json={"host_id": h["id"], "guest_name": "Ventende Gæst",
                                                          "guest_phone": "12345678"}).json()["visit_id"]
    escalate(vid)  # som når timeren udløber uden svar
    rec = [n for n in notes(plat, t["id"]) if n["recipient"] in ("70707070", "rec@oplevelse.dk")]
    assert {n["channel"] for n in rec} == {"sms", "email"} and all("uden svar" in n["body"] for n in rec)

    vid2 = plat.post(f"/api/kiosk/{tok}/checkin", json={"host_id": h["id"], "guest_name": "Anden Gæst",
                                                           "guest_phone": "12345678"}).json()["visit_id"]
    token = replies.token_for(vid2)
    plat.post(f"/api/reply/{token}", json={"answer": "reception"})
    declined = [n for n in notes(plat, t["id"]) if "kan ikke tage imod Anden Gæst" in n["body"]]
    assert len(declined) == 2
    before = len(notes(plat, t["id"]))
    escalate(vid2)  # værten har svaret, så timeren gør ikke noget (svaret "reception" er allerede sendt)
    assert len(notes(plat, t["id"])) == before


def test_escalation_timer_is_cancelled_by_reply(monkeypatch):
    fired = []
    replies.reset()
    replies.schedule(424242, 1, lambda vid: fired.append(vid))
    assert 424242 in replies._timers
    replies.record(424242, "now")
    assert 424242 not in replies._timers
    replies._run(424242, lambda vid: fired.append(vid))  # selv hvis timeren nåede at gå i gang
    assert fired == []
    replies.reset()


def test_delivery(plat, firm):
    t, h = firm
    tok = t["kiosk_token"]
    assert plat.post(f"/api/kiosk/{tok}/delivery", json={}).status_code == 404  # ikke slået til
    plat.patch(f"/api/admin/tenants/{t['id']}", json={"delivery_enabled": True, "delivery_email": "gods@oplevelse.dk"})
    r = plat.post(f"/api/kiosk/{tok}/delivery", json={"host_id": h["id"], "courier_company": "GLS"}).json()
    assert r["to"] == "Vera Vært"
    r = plat.post(f"/api/kiosk/{tok}/delivery", json={"courier_company": "PostNord", "courier_name": "Bent"}).json()
    assert r["to"] == "Godsmodtagelsen"
    ns = notes(plat, t["id"])
    assert any(n["recipient"] == "20304050" and "pakke til dig" in n["body"] and "GLS" in n["body"] for n in ns)
    assert any(n["recipient"] == "gods@oplevelse.dk" and "PostNord" in n["body"] for n in ns)
    # Pakker er ikke gæster: de står ikke på tjek-ud-listen.
    assert all(g["host_name"] != "Godsmodtagelsen" for g in plat.get(f"/api/kiosk/{tok}/inside").json())
    log = plat.get(f"/api/admin/tenants/{t['id']}/visits").json()
    assert any(v["kind"] == "delivery" and v["guest_company"] == "PostNord" for v in log)


def test_teams_message(plat, firm, monkeypatch):
    from app import notify
    from app.config import settings
    sent = []

    class R:
        status_code = 202
        text = ""
    monkeypatch.setattr(notify.httpx, "post", lambda url, json, timeout: sent.append((url, json)) or R())
    monkeypatch.setattr(settings, "notify_mode", "live")
    t, h = firm
    plat.patch(f"/api/admin/tenants/{t['id']}", json={"teams_webhook": "https://teams.example/hook"})
    plat.post(f"/api/kiosk/{t['kiosk_token']}/checkin", json={"host_id": h["id"], "guest_name": "Teams Gæst",
                                                                "guest_phone": "12345678"})
    teams = [j for u, j in sent if u == "https://teams.example/hook"]
    assert len(teams) == 1
    card = teams[0]["attachments"][0]["content"]
    assert "Teams Gæst" in str(card["body"]) and card["type"] == "AdaptiveCard"
    tn = next(n for n in notes(plat, t["id"]) if n["channel"] == "teams")
    assert tn["status"] == "sendt"
