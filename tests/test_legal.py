"""Databehandleraftale ved første login og gæsternes privatlivsside."""
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


@pytest.fixture(scope="module")
def plat(client):
    c = TestClient(app)
    assert c.post("/api/admin/login", json={"password": "hemmelig"}).status_code == 200
    return c


def tenant_admin(plat, t, email):
    plat.patch(f"/api/admin/tenants/{t['id']}/subscription", json={"self_service": True})
    link = plat.post(f"/api/admin/tenants/{t['id']}/users", json={"email": email}).json()["invite_url"]
    c = TestClient(app)
    assert c.post("/api/admin/invite/accept", json={"token": link.split("#invite=")[1],
                                                     "password": "lang-kode-1234"}).status_code == 200
    return c


def test_dpa_page_is_a_marked_draft():
    html = TestClient(app).get("/databehandleraftale").text
    assert "Databehandleraftale" in html and "UDKAST" in html and "[Leverandørens navn]" in html
    assert "GatewayAPI" in html and "Sverige" in html


def test_tenant_must_accept_once(plat):
    t = plat.post("/api/admin/tenants", json={"name": "Aftalefirma ApS"}).json()
    c = tenant_admin(plat, t, "admin@aftalefirma.dk")
    assert c.get("/api/admin/me").json()["dpa_required"]
    d = c.get("/api/admin/dpa").json()
    assert d["required"] and d["org_name"] == "Aftalefirma ApS" and "Aftalefirma ApS" in d["html"]
    assert d["version"].endswith("-udkast")
    assert c.post("/api/admin/dpa/accept", json={"version": "gammel"}).status_code == 409
    assert c.post("/api/admin/dpa/accept", json={"version": d["version"]}).status_code == 200
    assert not c.get("/api/admin/me").json()["dpa_required"]
    st = plat.get(f"/api/admin/tenants/{t['id']}").json()["dpa"]
    assert st["current"] and st["accepted_by"] == "<admin@aftalefirma.dk>" and st["accepted_at"]
    assert not plat.get("/api/admin/me").json()["dpa_required"]  # leverandøren selv skal ikke
    assert plat.post("/api/admin/dpa/accept", json={"version": d["version"]}).status_code == 422
    # Når juristen har godkendt (DPA_FINAL=1), er det en ny version, som skal accepteres igen.
    old = settings.dpa_final
    settings.dpa_final = True
    try:
        assert c.get("/api/admin/me").json()["dpa_required"]
        assert "UDKAST" not in c.get("/api/admin/dpa").json()["html"]
    finally:
        settings.dpa_final = old
    plat.delete(f"/api/admin/tenants/{t['id']}")


def test_house_acceptance_covers_firms_and_prod_blocks_changes(plat):
    partner = plat.post("/api/admin/partners", json={"name": "Aftalehuset"}).json()
    t = plat.post("/api/admin/tenants", json={"name": "Husfirma Aftale", "partner_id": partner["id"]}).json()
    c = tenant_admin(plat, t, "admin@husfirma-aftale.dk")
    link = plat.post(f"/api/admin/partners/{partner['id']}/users", json={"email": "hus@aftalehuset.dk"}).json()["invite_url"]
    pa = TestClient(app)  # logges ind før "prod", hvor login-cookien kun sendes over https
    pa.post("/api/admin/invite/accept", json={"token": link.split("#invite=")[1], "password": "lang-kode-1234"})
    old = settings.env
    settings.env = "prod"
    try:
        r = c.patch(f"/api/admin/tenants/{t['id']}", json={"welcome_text": "Hej"})
        assert r.status_code == 403 and "databehandleraftalen" in r.json()["detail"]
        assert c.get(f"/api/admin/tenants/{t['id']}").status_code == 200  # at se er tilladt
        v = pa.get("/api/admin/dpa").json()
        assert v["org_kind"] == "hus"
        assert pa.post("/api/admin/dpa/accept", json={"version": v["version"]}).status_code == 200
        assert not c.get("/api/admin/me").json()["dpa_required"]  # huset dækker sine firmaer
        assert c.patch(f"/api/admin/tenants/{t['id']}", json={"welcome_text": "Hej"}).status_code == 200
    finally:
        settings.env = old
    plat.delete(f"/api/admin/tenants/{t['id']}")
    plat.delete(f"/api/admin/partners/{partner['id']}")


def test_privacy_page_for_guests(plat):
    t = plat.post("/api/admin/tenants", json={"name": "Privat & Co"}).json()
    plat.patch(f"/api/admin/tenants/{t['id']}", json={"retention_days": 45, "reception_email": "reception@privat.dk"})
    c = TestClient(app)
    da = c.get(f"/privatliv/{t['kiosk_token']}").text
    assert "Privat &amp; Cos legitime" in da and "Privat &amp; Co" in da and "45 dage" in da and "reception@privat.dk" in da and "Datatilsynet" in da
    en = c.get(f"/privatliv/{t['kiosk_token']}?lang=en").text
    assert "45 days" in en and "data processor" in en
    assert c.get("/privatliv/findesikke").status_code == 404
    plat.delete(f"/api/admin/tenants/{t['id']}")
