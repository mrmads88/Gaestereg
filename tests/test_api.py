import io
import os
import shutil
import tempfile

import pytest

_tmp = tempfile.mkdtemp()
os.environ.update(DATA_DIR=_tmp, APP_ENV="local", ADMIN_PASSWORD="hemmelig", NOTIFY_MODE="test", SEED_DEMO="1")

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c
    shutil.rmtree(_tmp, ignore_errors=True)


@pytest.fixture(scope="module")
def admin(client):
    r = client.post("/api/admin/login", json={"password": "hemmelig"})
    assert r.status_code == 200
    return client


def png_bytes(w=800, h=500):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), "#336699").save(buf, "PNG")
    return buf.getvalue()


def test_admin_requires_login(client):
    client.cookies.clear()
    assert client.get("/api/admin/tenants").status_code == 401
    assert client.post("/api/admin/login", json={"password": "forkert"}).status_code == 401


def test_demo_seed_and_public_config_hides_contact_info(client):
    r = client.get("/api/kiosk/demo/config")
    assert r.status_code == 200
    cfg = r.json()
    assert cfg["hosts"] and cfg["logo_url"].startswith("/media/")
    for h in cfg["hosts"]:
        assert set(h) == {"id", "name", "title", "photo_url"}


def test_unknown_token_404(client):
    assert client.get("/api/kiosk/findesikke/config").status_code == 404


def test_full_customer_setup_and_checkin(admin):
    t = admin.post("/api/admin/tenants", json={"name": "Testkunde A/S"}).json()
    tid, token = t["id"], t["kiosk_token"]
    assert t["sms_sender"] == "Testkunde A"

    r = admin.patch(f"/api/admin/tenants/{tid}", json={"color": "#c8102e", "ask_company": True,
                                                      "welcome_text": "Velkommen"})
    assert r.json()["color"] == "#c8102e"
    assert admin.patch(f"/api/admin/tenants/{tid}", json={"color": "rød"}).status_code == 422

    logo = admin.post(f"/api/admin/tenants/{tid}/image/logo", files={"file": ("l.png", png_bytes(), "image/png")})
    assert logo.status_code == 200 and logo.json()["logo_url"].endswith(".png")

    both = admin.post(f"/api/admin/tenants/{tid}/hosts", json={
        "name": "Bente Both", "title": "CEO", "email": "bente@test.dk", "phone": "20 30 40 50",
        "notify_sms": True, "notify_email": True}).json()
    mail_only = admin.post(f"/api/admin/tenants/{tid}/hosts", json={
        "name": "Mads Mail", "email": "mads@test.dk", "phone": "11223344",
        "notify_sms": False, "notify_email": True}).json()

    ph = admin.post(f"/api/admin/hosts/{both['id']}/photo", files={"file": ("p.png", png_bytes(900, 1200), "image/png")})
    assert ph.status_code == 200
    stored = Image.open(os.path.join(_tmp, "media", ph.json()["photo_url"].split("/")[-1]))
    assert stored.size == (600, 600)

    # phone is required by default
    r = admin.post(f"/api/kiosk/{token}/checkin", json={"host_id": both["id"], "guest_name": "Gitte Gæst"})
    assert r.status_code == 422

    r = admin.post(f"/api/kiosk/{token}/checkin", json={
        "host_id": both["id"], "guest_name": "Gitte  Gæst", "guest_phone": "+45 99 88 77 66",
        "guest_company": "Firma X"})
    assert r.status_code == 200, r.text
    assert r.json()["guest_name"] == "Gitte Gæst"

    r = admin.post(f"/api/kiosk/{token}/checkin", json={
        "host_id": mail_only["id"], "guest_name": "Ole Olsen", "guest_phone": "55667788"})
    assert r.status_code == 200
    visit2 = r.json()["visit_id"]

    notes = admin.get(f"/api/admin/tenants/{tid}/notifications").json()
    by = sorted((n["channel"], n["recipient"]) for n in notes)
    assert by == [("email", "bente@test.dk"), ("email", "mads@test.dk"), ("sms", "20 30 40 50")]
    assert all(n["status"] == "test" for n in notes)
    sms = next(n for n in notes if n["channel"] == "sms")
    assert "Gitte Gæst" in sms["body"] and "+45 99 88 77 66" in sms["body"]

    inside = admin.get(f"/api/kiosk/{token}/inside").json()
    assert {g["name"] for g in inside} == {"Gitte G.", "Ole O."}
    assert admin.post(f"/api/kiosk/{token}/checkout/{visit2}").status_code == 200
    assert len(admin.get(f"/api/kiosk/{token}/inside").json()) == 1

    # host of another tenant cannot be used
    other = admin.get("/api/kiosk/demo/config").json()["hosts"][0]["id"]
    assert admin.post(f"/api/kiosk/{token}/checkin", json={"host_id": other, "guest_name": "X Y",
                                                            "guest_phone": "12345678"}).status_code == 404

    # preview stores nothing
    before = len(admin.get(f"/api/admin/tenants/{tid}/visits").json())
    admin.post(f"/api/kiosk/{token}/checkin", json={"host_id": both["id"], "guest_name": "Pre View",
                                                     "guest_phone": "12345678", "preview": True})
    assert len(admin.get(f"/api/admin/tenants/{tid}/visits").json()) == before

    # unknown host goes to reception
    admin.patch(f"/api/admin/tenants/{tid}", json={"reception_phone": "70707070"})
    r = admin.post(f"/api/kiosk/{token}/checkin", json={"host_id": None, "guest_name": "Ukendt Person",
                                                         "guest_phone": "12345678"})
    assert r.json()["host_name"] == "Receptionen"

    # test message button
    r = admin.post(f"/api/admin/hosts/{both['id']}/test").json()
    assert {x["channel"] for x in r} == {"sms", "email"}

    # new kiosk link invalidates the old one
    new = admin.post(f"/api/admin/tenants/{tid}/new-link").json()["kiosk_token"]
    assert admin.get(f"/api/kiosk/{token}/config").status_code == 404
    assert admin.get(f"/api/kiosk/{new}/config").status_code == 200

    # reorder
    order = admin.post(f"/api/admin/tenants/{tid}/hosts/order", json={"ids": [mail_only["id"], both["id"]]}).json()
    assert [h["id"] for h in order] == [mail_only["id"], both["id"]]

    assert admin.delete(f"/api/admin/tenants/{tid}").status_code == 200
    assert admin.get(f"/api/kiosk/{new}/config").status_code == 404


def test_delete_host_keeps_visits_and_purge_removes_old(admin):
    from datetime import timedelta

    from app.db import SessionLocal
    from app.models import Notification, Tenant, Visit, utcnow
    from app.routes_kiosk import purge_old

    t = admin.post("/api/admin/tenants", json={"name": "Oprydning ApS"}).json()
    tid, token = t["id"], t["kiosk_token"]
    h = admin.post(f"/api/admin/tenants/{tid}/hosts", json={"name": "Søren Ærø", "email": "s@test.dk"}).json()
    for name in ("Åse Øster", "Bo Bø"):
        r = admin.post(f"/api/kiosk/{token}/checkin", json={"host_id": h["id"], "guest_name": name,
                                                             "guest_phone": "12345678"})
        assert r.status_code == 200, r.text

    # Personen kan slettes, selvom der er besøg. Besøgene beholder navnet.
    assert admin.delete(f"/api/admin/hosts/{h['id']}").status_code == 200
    visits = admin.get(f"/api/admin/tenants/{tid}/visits").json()
    assert sorted(v["guest_name"] for v in visits) == ["Bo Bø", "Åse Øster"]
    assert all(v["host_name"] == "Søren Ærø" for v in visits)

    # Besøg ældre end retention_days slettes sammen med deres beskeder.
    with SessionLocal() as db:
        tenant = db.get(Tenant, tid)
        old = db.scalars(select(Visit).where(Visit.tenant_id == tid)).first()
        old.checked_in_at = utcnow() - timedelta(days=tenant.retention_days + 1)
        db.commit()
        assert db.scalar(select(func.count()).select_from(Notification).where(Notification.visit_id == old.id)) > 0
        assert purge_old(db, tenant) == 1
        assert db.scalar(select(func.count()).select_from(Notification).where(Notification.visit_id == old.id)) == 0
        assert db.scalar(select(func.count()).select_from(Visit).where(Visit.tenant_id == tid)) == 1

    assert admin.delete(f"/api/admin/tenants/{tid}").status_code == 200


def test_kiosk_config_is_cached_until_admin_changes_something(admin):
    from app.db import SessionLocal
    from app.models import Tenant

    t = admin.post("/api/admin/tenants", json={"name": "Cache A/S"}).json()
    tid, token = t["id"], t["kiosk_token"]
    assert admin.get(f"/api/kiosk/{token}/config").json()["name"] == "Cache A/S"

    # Ændring direkte i databasen ses ikke: skærmens polling rammer ikke databasen.
    with SessionLocal() as db:
        db.get(Tenant, tid).name = "Direkte"
        db.commit()
    assert admin.get(f"/api/kiosk/{token}/config").json()["name"] == "Cache A/S"

    # En ændring via admin slår igennem med det samme.
    admin.patch(f"/api/admin/tenants/{tid}", json={"welcome_text": "Hej"})
    cfg = admin.get(f"/api/kiosk/{token}/config").json()
    assert cfg["name"] == "Direkte" and cfg["welcome_text"] == "Hej"

    admin.patch(f"/api/admin/tenants/{tid}", json={"active": False})
    assert admin.get(f"/api/kiosk/{token}/config").status_code == 404
    assert admin.delete(f"/api/admin/tenants/{tid}").status_code == 200


def test_svg_with_script_rejected(admin):
    tid = admin.post("/api/admin/tenants", json={"name": "SVG test"}).json()["id"]
    bad = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    r = admin.post(f"/api/admin/tenants/{tid}/image/logo", files={"file": ("x.svg", bad, "image/svg+xml")})
    assert r.status_code == 400
    good = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><rect width="10" height="10"/></svg>'
    r = admin.post(f"/api/admin/tenants/{tid}/image/logo", files={"file": ("x.svg", good, "image/svg+xml")})
    url = r.json()["logo_url"]
    m = admin.get(url)
    assert m.status_code == 200 and "default-src 'none'" in m.headers["content-security-policy"]


def test_render_and_msisdn():
    from app.notify import normalize_msisdn, render
    assert normalize_msisdn("20 30 40 50") == "4520304050"
    assert normalize_msisdn("+46 70 123 45 67") == "46701234567"
    assert normalize_msisdn("0045 20304050") == "4520304050"
    assert render("Hej {vaert} {ukendt}", {"vaert": "Bo"}) == "Hej Bo {ukendt}"
    assert render("Pris {", {"vaert": "Bo"}) == "Pris {"


def test_live_mode_records_failure_when_not_configured(monkeypatch):
    from app import notify
    from app.models import Notification, Tenant
    monkeypatch.setattr(notify.settings, "notify_mode", "live")
    monkeypatch.setattr(notify.settings, "gatewayapi_token", "")
    n = Notification(channel="sms", recipient="20304050", body="x")
    notify.deliver(n, Tenant(name="X", sms_sender="X"))
    assert n.status == "fejl" and "GATEWAYAPI_TOKEN" in n.error
