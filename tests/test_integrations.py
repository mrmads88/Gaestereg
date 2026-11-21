"""Integrationer: signerede webhooks med nye forsøg og log, API-nøgler og /api/v1."""
import hashlib
import hmac
import json
from datetime import date

import httpx
import pytest
from fastapi.testclient import TestClient

from app import integrations
from app.config import settings
from app.db import SessionLocal
from app.main import app
from app.models import IntegrationDelivery

A = "/api/admin"


class Receiver:
    """Falsk modtager: gemmer kald og svarer med den statuskode, testen vælger."""
    def __init__(self):
        self.calls, self.status = [], 200

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        return httpx.Response(self.status, text="ok" if self.status < 300 else "nej")


@pytest.fixture()
def rx(monkeypatch):
    r = Receiver()
    retries = []
    monkeypatch.setattr(integrations, "run_inline", True)
    monkeypatch.setattr(integrations, "client_factory", lambda: httpx.Client(transport=httpx.MockTransport(r.handler)))
    monkeypatch.setattr(integrations, "schedule_retry", lambda delay, fn: retries.append((delay, fn)))
    r.retries = retries
    return r


@pytest.fixture(scope="module")
def plat(client):
    c = TestClient(app)
    assert c.post(f"{A}/login", json={"password": "hemmelig"}).status_code == 200
    return c


def firm(plat, name, module=True):
    t = plat.post(f"{A}/tenants", json={"name": name}).json()
    if module:
        plat.post(f"{A}/billing/account/subscriptions?tenant_id={t['id']}",
                  json={"product": "integrations", "start": date.today().isoformat()})
    h = plat.post(f"{A}/tenants/{t['id']}/hosts", json={"name": "Vært Hansen", "email": "vaert@x.dk"}).json()
    return t, h


def test_webhook_is_signed_retried_and_logged(plat, rx):
    t, h = firm(plat, "Webhook ApS")
    r = plat.post(f"{A}/integrations", json={"tenant_id": t["id"], "name": "ServiceNow",
                                             "url": "https://hooks.example.com/nodd", "events": ["visit.checked_in", "visit.checked_out"]})
    assert r.status_code == 200, r.text
    hook = r.json()
    secret = hook["secret"]
    assert secret.startswith("whsec_") and "secret" not in plat.get(f"{A}/integrations", params={"tenant_id": t["id"]}).json()["webhooks"][0]

    k = TestClient(app)
    v = k.post(f"/api/kiosk/{t['kiosk_token']}/checkin", json={"guest_name": "Gæst Gæstesen", "host_id": h["id"],
                                                                "guest_phone": "20304050"}).json()
    assert len(rx.calls) == 1
    req = rx.calls[0]
    body = req.content
    assert req.headers["x-nodd-event"] == "visit.checked_in"
    expected = "sha256=" + hmac.new(secret.encode(), req.headers["x-nodd-timestamp"].encode() + b"." + body, hashlib.sha256).hexdigest()
    assert req.headers["x-nodd-signature"] == expected
    data = json.loads(body)
    assert data["event"] == "visit.checked_in" and data["data"]["visit"]["guest_name"] == "Gæst Gæstesen"
    assert data["account"]["name"] == "Webhook ApS" and "20304050" not in body.decode()  # ingen mobilnummer

    # Modtageren fejler: prøves igen senere, og opgives efter sidste forsøg.
    rx.status = 500
    k.post(f"/api/kiosk/{t['kiosk_token']}/checkout/{v['visit_id']}")
    out = plat.get(f"{A}/integrations", params={"tenant_id": t["id"]}).json()["webhooks"][0]
    d = out["deliveries"][0]
    assert d["event"] == "visit.checked_out" and d["status"] == "failed" and d["response_code"] == 500
    assert out["last_error"].startswith("Svar 500") and rx.retries[-1][0] == 60
    for _ in range(len(integrations.RETRY_SECONDS)):
        rx.retries.pop()[1]()
    with SessionLocal() as db:
        assert db.get(IntegrationDelivery, d["id"]).status == "dead"
    # Manuelt nyt forsøg, når modtageren virker igen.
    rx.status = 200
    assert plat.post(f"{A}/deliveries/{d['id']}/retry").json()["status"] == "ok"

    # Test-knappen, ny hemmelighed, slå fra (ingen afsendelser) og slet.
    assert plat.post(f"{A}/integrations/{hook['id']}/test").json()["status"] == "ok"
    assert plat.post(f"{A}/integrations/{hook['id']}/secret").json()["secret"] != secret
    plat.patch(f"{A}/integrations/{hook['id']}", json={"enabled": False})
    n = len(rx.calls)
    k.post(f"/api/kiosk/{t['kiosk_token']}/checkin", json={"guest_name": "Igen", "host_id": h["id"], "guest_phone": "20304050"})
    assert len(rx.calls) == n
    assert plat.delete(f"{A}/integrations/{hook['id']}").status_code == 200
    plat.delete(f"{A}/tenants/{t['id']}")


def test_webhook_validation_and_module(plat, rx, monkeypatch):
    t, _ = firm(plat, "Uden modul ApS", module=False)
    pa = plat.post(f"{A}/partners", json={"name": "Integrationshuset"}).json()
    link = plat.post(f"{A}/partners/{pa['id']}/users", json={"email": "hus@integration.dk"}).json()["invite_url"]
    house = TestClient(app)
    house.post(f"{A}/invite/accept", json={"token": link.split("#invite=")[1], "password": "lang-kode-1234"})
    # Huset har ikke modulet: 403. Leverandøren må altid.
    assert house.get(f"{A}/integrations", params={"partner_id": pa["id"]}).status_code == 403
    assert plat.get(f"{A}/integrations", params={"partner_id": pa["id"]}).status_code == 200
    bad = plat.post(f"{A}/integrations", json={"tenant_id": t["id"], "url": "https://x.example.com", "events": ["nope"]})
    assert bad.status_code == 422 and "Ukendt hændelse" in bad.json()["detail"]
    assert plat.post(f"{A}/integrations", json={"tenant_id": t["id"], "url": "https://x.example.com",
                                                "events": ["invoice.finalized"]}).status_code == 422  # kun leverandøren
    # Uden for lokalt miljø: kun https og kun offentlige adresser.
    monkeypatch.setattr(settings, "env", "dev")
    monkeypatch.setattr(integrations, "resolve", lambda host: ["10.0.0.5"] if host == "intern.example.com" else ["93.184.216.34"])
    for url, msg in (("http://x.example.com", "https://"), ("https://intern.example.com/hook", "internt"),
                     ("https://user:pw@x.example.com", "brugernavn")):
        r = plat.post(f"{A}/integrations", json={"tenant_id": t["id"], "url": url, "events": ["visit.checked_in"]})
        assert r.status_code == 422 and msg in r.json()["detail"], (url, r.text)
    assert plat.post(f"{A}/integrations", json={"tenant_id": t["id"], "url": "https://x.example.com/hook",
                                                "events": ["visit.checked_in"]}).status_code == 200
    plat.delete(f"{A}/tenants/{t['id']}")
    plat.delete(f"{A}/partners/{pa['id']}")


def test_platform_gets_invoice_finalized(plat, rx):
    hook = plat.post(f"{A}/integrations", json={"platform": True, "name": "Make → e-conomic", "url": "https://hook.eu1.make.com/abc",
                                                "events": ["invoice.finalized"]}).json()
    t = plat.post(f"{A}/tenants", json={"name": "Faktura ApS"}).json()
    plat.patch(f"{A}/billing/account?tenant_id={t['id']}", json={"cvr": "12345678"})
    plat.post(f"{A}/billing/account/subscriptions?tenant_id={t['id']}", json={"product": "start", "start": "2031-01-01"})
    plat.post(f"{A}/billing/run", json={"period_start": "2031-01-01"})
    draft = next(i for i in plat.get(f"{A}/billing/invoices?status=draft").json() if i["customer"] == "Faktura ApS")
    plat.post(f"{A}/billing/invoices/{draft['id']}/finalize")
    sent = [json.loads(c.content) for c in rx.calls if c.headers["x-nodd-event"] == "invoice.finalized"]
    assert sent and sent[-1]["data"]["invoice"]["customer_cvr"] == "12345678" and sent[-1]["data"]["invoice"]["number"]
    plat.delete(f"{A}/integrations/{hook['id']}")
    plat.delete(f"{A}/tenants/{t['id']}")


def test_api_keys_and_v1(plat, rx):
    t, h = firm(plat, "API ApS")
    k = plat.post(f"{A}/api-keys", json={"tenant_id": t["id"], "name": "Power BI"}).json()
    key = k["key"]
    assert key.startswith("nodd_") and k["prefix"] == key[:12] and k["scopes"] == ["read"]
    assert "key" not in plat.get(f"{A}/integrations", params={"tenant_id": t["id"]}).json()["api_keys"][0]
    api = TestClient(app)
    H = {"Authorization": f"Bearer {key}"}
    assert api.get("/api/v1/me").status_code == 401
    me = api.get("/api/v1/me", headers=H).json()
    assert me["account"]["name"] == "API ApS" and me["companies"][0]["id"] == t["id"]
    api.post(f"/api/kiosk/{t['kiosk_token']}/checkin", json={"guest_name": "API Gæst", "host_id": h["id"], "guest_phone": "20304050"})
    vis = api.get("/api/v1/visits", headers=H).json()
    assert vis["count"] == 1 and vis["visits"][0]["guest_name"] == "API Gæst"
    assert api.get("/api/v1/visits", params={"from": "2025-01-01", "to": "2025-12-31"}, headers=H).json()["count"] == 0
    assert api.get("/api/v1/visits", params={"from": "2020-01-01", "to": "2026-01-01"}, headers=H).status_code == 422
    assert api.get("/api/v1/hosts", headers=H).json()["hosts"][0]["email"] == "vaert@x.dk"
    # Personsync kræver people:write.
    sync = {"people": [{"name": "Vært Hansen", "title": "Direktør", "email": "VAERT@x.dk"}, {"name": "Ny Person", "email": "ny@x.dk"}],
            "deactivate_missing": True}
    assert api.post("/api/v1/hosts/sync", json=sync, headers=H).status_code == 403
    k2 = plat.post(f"{A}/api-keys", json={"tenant_id": t["id"], "name": "HR", "scopes": ["read", "people:write"]}).json()
    r = api.post("/api/v1/hosts/sync", json=sync, headers={"Authorization": f"Bearer {k2['key']}"}).json()
    assert r == {"created": 1, "updated": 1, "deactivated": 0, "total": 2}
    cfg = TestClient(app).get(f"/api/kiosk/{t['kiosk_token']}/config").json()
    assert {x["name"] for x in cfg["hosts"]} == {"Vært Hansen", "Ny Person"}
    assert api.get("/api/v1/bookings", headers=H).json() == {"bookings": []}
    assert api.get("/api/v1/time-entries", headers=H).json() == {"entries": []}
    # Tilbagekaldt nøgle virker ikke.
    assert plat.delete(f"{A}/api-keys/{k['id']}").json()["revoked"]
    assert api.get("/api/v1/me", headers=H).status_code == 401
    plat.delete(f"{A}/tenants/{t['id']}")
    assert api.get("/api/v1/me", headers={"Authorization": f"Bearer {k2['key']}"}).status_code == 401  # slettet med firmaet


def test_house_key_sees_its_firms_only(plat, rx):
    pa = plat.post(f"{A}/partners", json={"name": "API-huset"}).json()
    plat.post(f"{A}/billing/account/subscriptions?partner_id={pa['id']}", json={"product": "integrations", "start": date.today().isoformat()})
    a = plat.post(f"{A}/tenants", json={"name": "Husfirma A", "partner_id": pa["id"]}).json()
    other, _ = firm(plat, "Uden for huset")
    key = plat.post(f"{A}/api-keys", json={"partner_id": pa["id"], "name": "Husets BI"}).json()["key"]
    H = {"Authorization": f"Bearer {key}"}
    api = TestClient(app)
    assert [c["name"] for c in api.get("/api/v1/me", headers=H).json()["companies"]] == ["Husfirma A"]
    assert api.get("/api/v1/visits", params={"tenant_id": other["id"]}, headers=H).status_code == 404
    assert api.post("/api/v1/hosts/sync", json={"people": []}, headers=H).status_code in (403, 422)
    plat.delete(f"{A}/tenants/{a['id']}")
    plat.delete(f"{A}/tenants/{other['id']}")
    plat.delete(f"{A}/partners/{pa['id']}")
