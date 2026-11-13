"""Fase 1: mange kunder, loginbegrænsning, skærmstatus og sletning af en gæsts data."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from app import presence, ratelimit
from app.main import app


@pytest.fixture(scope="module")
def plat(client):
    c = TestClient(app)
    assert c.post("/api/admin/login", json={"password": "hemmelig"}).status_code == 200
    return c


def count_queries(fn):
    from app.db import engine
    n = []
    listener = lambda *a, **k: n.append(1)  # noqa: E731
    event.listen(engine, "before_cursor_execute", listener)
    try:
        fn()
    finally:
        event.remove(engine, "before_cursor_execute", listener)
    return len(n)


def test_customer_list_query_count_does_not_grow(plat):
    partner = plat.post("/api/admin/partners", json={"name": "Skalahuset"}).json()
    made = []
    def add(n):
        for i in range(n):
            t = plat.post("/api/admin/tenants", json={"name": f"Skala {len(made)}", "partner_id": partner["id"]}).json()
            plat.post(f"/api/admin/tenants/{t['id']}/hosts", json={"name": "Person"})
            made.append(t["id"])
    add(2)
    few = count_queries(lambda: plat.get("/api/admin/tenants"))
    few_p = count_queries(lambda: plat.get("/api/admin/partners"))
    add(10)
    many = count_queries(lambda: plat.get("/api/admin/tenants"))
    many_p = count_queries(lambda: plat.get("/api/admin/partners"))
    assert many == few and many_p == few_p, (few, many, few_p, many_p)
    lst = {t["id"]: t for t in plat.get("/api/admin/tenants").json()}
    assert all(lst[i]["host_count"] == 1 and lst[i]["partner_name"] == "Skalahuset" for i in made)
    for i in made:
        plat.delete(f"/api/admin/tenants/{i}")
    plat.delete(f"/api/admin/partners/{partner['id']}")


def test_login_is_rate_limited(monkeypatch):
    from app import routes_access
    monkeypatch.setattr(routes_access, "slow_down", lambda: None)
    monkeypatch.setattr(routes_access, "LOGIN_EMAIL_LIMIT", 3)
    ratelimit.reset()
    c = TestClient(app)
    for _ in range(3):
        assert c.post("/api/admin/login", json={"email": "gaet@test.dk", "password": "forkert"}).status_code == 401
    r = c.post("/api/admin/login", json={"email": "gaet@test.dk", "password": "forkert"})
    assert r.status_code == 429 and "For mange forsøg" in r.json()["detail"]
    # En anden e-mail er ikke ramt, men IP-grænsen tæller videre.
    assert c.post("/api/admin/login", json={"email": "anden@test.dk", "password": "forkert"}).status_code == 401
    ratelimit.reset()


def test_screen_status_is_in_memory_and_ignores_preview(plat):
    t = plat.post("/api/admin/tenants", json={"name": "Skærmstatus"}).json()
    presence.reset()
    assert plat.get(f"/api/admin/tenants/{t['id']}").json()["screen"] == {"online": False, "seen_at": None}
    plat.get(f"/api/kiosk/{t['kiosk_token']}/config?pv=1")
    assert not plat.get(f"/api/admin/tenants/{t['id']}").json()["screen"]["online"]
    plat.get(f"/api/kiosk/{t['kiosk_token']}/config")
    s = plat.get(f"/api/admin/tenants/{t['id']}").json()["screen"]
    assert s["online"] and s["seen_at"]
    lst = next(x for x in plat.get("/api/admin/tenants").json() if x["id"] == t["id"])
    assert lst["screen"]["online"]
    plat.delete(f"/api/admin/tenants/{t['id']}")


def test_delete_one_guests_data(plat):
    t = plat.post("/api/admin/tenants", json={"name": "GDPR ApS"}).json()
    h = plat.post(f"/api/admin/tenants/{t['id']}/hosts", json={"name": "Vært", "email": "v@gdpr.dk"}).json()
    tok = t["kiosk_token"]
    for name, phone in (("Ole Olsen", "+45 11 22 33 44"), ("Ole O", "11223344"), ("Anden Gæst", "55667788")):
        assert plat.post(f"/api/kiosk/{tok}/checkin", json={"host_id": h["id"], "guest_name": name,
                                                              "guest_phone": phone}).status_code == 200
    visits = plat.get(f"/api/admin/tenants/{t['id']}/visits").json()
    ole = next(v for v in visits if v["guest_name"] == "Ole Olsen")
    r = plat.delete(f"/api/admin/tenants/{t['id']}/visits/{ole['id']}?everything=true").json()
    assert r["deleted"] == 2
    left = plat.get(f"/api/admin/tenants/{t['id']}/visits").json()
    assert [v["guest_name"] for v in left] == ["Anden Gæst"]
    assert all("Ole" not in n["body"] for n in plat.get(f"/api/admin/tenants/{t['id']}/notifications").json())
    assert plat.delete(f"/api/admin/tenants/{t['id']}/visits/{left[0]['id']}").json()["deleted"] == 1
    assert plat.delete(f"/api/admin/tenants/{t['id']}/visits/999999").status_code == 404
    plat.delete(f"/api/admin/tenants/{t['id']}")


def test_tenant_admin_cannot_delete_other_firms_visits(plat):
    a = plat.post("/api/admin/tenants", json={"name": "Firma A"}).json()
    b = plat.post("/api/admin/tenants", json={"name": "Firma B"}).json()
    plat.patch(f"/api/admin/tenants/{a['id']}/subscription", json={"self_service": True})
    inv = plat.post(f"/api/admin/tenants/{a['id']}/users", json={"email": "a@firma-a.dk"}).json()
    c = TestClient(app)
    c.post("/api/admin/invite/accept", json={"token": inv["invite_url"].split("#invite=")[1], "password": "firma-a-kode"})
    plat.post(f"/api/kiosk/{b['kiosk_token']}/checkin", json={"host_id": None, "guest_name": "B Gæst",
                                                                "guest_phone": "12345678"})
    vb = plat.get(f"/api/admin/tenants/{b['id']}/visits").json()[0]
    assert c.delete(f"/api/admin/tenants/{b['id']}/visits/{vb['id']}").status_code == 404
    assert c.delete(f"/api/admin/tenants/{a['id']}/visits/{vb['id']}").status_code == 404
    for t in (a, b):
        plat.delete(f"/api/admin/tenants/{t['id']}")
