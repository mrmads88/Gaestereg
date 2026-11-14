"""Roller: platform, partner (fx kontorhotel) og kunde-admin. Hver får sin egen klient og cookie."""
import pytest
from fastapi.testclient import TestClient

from app.auth import hash_password, verify_password
from app.main import app


def new_client():
    return TestClient(app)  # uden lifespan. Databasen er allerede sat op af `client`.


def token_of(url: str) -> str:
    assert "#invite=" in url
    return url.split("#invite=", 1)[1]


def accept(token: str, password: str = "en-lang-kode-123"):
    c = new_client()
    r = c.post("/api/admin/invite/accept", json={"token": token, "password": password})
    return c, r


@pytest.fixture(scope="module")
def platform(client):
    c = new_client()
    assert c.post("/api/admin/login", json={"password": "hemmelig"}).status_code == 200
    return c


@pytest.fixture(scope="module")
def setup(platform):
    """Kontorhotel med én partner-admin og ét firma med én kunde-admin."""
    partner = platform.post("/api/admin/partners", json={"name": "Kontorhotellet"}).json()
    inv = platform.post(f"/api/admin/partners/{partner['id']}/users",
                        json={"email": "Hus@Kontorhotel.dk", "name": "Husadministrator"}).json()
    assert inv["user"]["email"] == "hus@kontorhotel.dk" and inv["user"]["pending"]
    assert not inv["emailed"]  # testtilstand: linket vises i stedet for at blive sendt
    pa, r = accept(token_of(inv["invite_url"]))
    assert r.status_code == 200, r.text

    firm = pa.post("/api/admin/tenants", json={"name": "Firma 1 ApS"}).json()
    assert firm["partner_id"] == partner["id"] and firm["partner_name"] == "Kontorhotellet"
    inv2 = pa.post(f"/api/admin/tenants/{firm['id']}/users", json={"email": "anna@firma1.dk", "name": "Anna"}).json()
    return {"partner": partner, "pa": pa, "firm": firm, "tenant_token": token_of(inv2["invite_url"])}


def test_password_hash_roundtrip():
    h = hash_password("korrekt hest batteri")
    assert h.startswith("scrypt$") and verify_password("korrekt hest batteri", h)
    assert not verify_password("forkert", h) and not verify_password("x", "noget-andet")


def test_partner_sees_only_own_firms(setup, platform):
    pa, firm = setup["pa"], setup["firm"]
    names = [t["name"] for t in pa.get("/api/admin/tenants").json()]
    assert names == ["Firma 1 ApS"]
    demo_id = next(t["id"] for t in platform.get("/api/admin/tenants").json() if "demo" in t["name"])
    assert pa.get(f"/api/admin/tenants/{demo_id}").status_code == 404
    assert pa.patch(f"/api/admin/tenants/{demo_id}", json={"name": "Hacket"}).status_code == 404

    me = pa.get("/api/admin/me").json()
    assert me["role"] == "partner" and me["partner"]["name"] == "Kontorhotellet"
    assert me["can"]["create_tenant"] and not me["can"]["delete_tenant"] and not me["can"]["subscription"]

    # Ikke abonnement og sletning, men gerne slå skærmen fra og til.
    assert "subscription" not in pa.get(f"/api/admin/tenants/{firm['id']}").json()
    assert pa.patch(f"/api/admin/tenants/{firm['id']}/subscription", json={"self_service": True}).status_code == 403
    assert pa.delete(f"/api/admin/tenants/{firm['id']}").status_code == 403
    assert pa.patch(f"/api/admin/tenants/{firm['id']}", json={"active": True}).status_code == 200
    assert pa.post("/api/admin/partners", json={"name": "Ny"}).status_code == 403


def test_tenant_admin_needs_self_service(setup, platform):
    firm, token = setup["firm"], setup["tenant_token"]
    _, r = accept(token, "annas-kode-1234")
    assert r.status_code == 403 and "Selvbetjening er ikke slået til" in r.json()["detail"]
    c = new_client()
    r = c.post("/api/admin/login", json={"email": "anna@firma1.dk", "password": "annas-kode-1234"})
    assert r.status_code == 403

    sub = platform.patch(f"/api/admin/tenants/{firm['id']}/subscription",
                         json={"self_service": True, "self_service_monthly_price": 199, "sub_yearly_price": 4800,
                               "sub_paid_until": "2027-11-30"}).json()["subscription"]
    assert sub["self_service"] and sub["sub_paid_until"] == "2027-11-30"
    assert c.post("/api/admin/login", json={"email": "ANNA@firma1.dk", "password": "annas-kode-1234"}).status_code == 200
    me = c.get("/api/admin/me").json()
    assert me["role"] == "tenant" and me["tenant_id"] == firm["id"] and not me["can"]["create_tenant"]

    # Alt undtagen abonnement, sletning og aktiv.
    assert [t["id"] for t in c.get("/api/admin/tenants").json()] == [firm["id"]]
    assert c.patch(f"/api/admin/tenants/{firm['id']}", json={"welcome_text": "Hej"}).status_code == 200
    assert c.patch(f"/api/admin/tenants/{firm['id']}", json={"active": False}).status_code == 403
    assert c.post("/api/admin/tenants", json={"name": "Eget"}).status_code == 403
    assert c.delete(f"/api/admin/tenants/{firm['id']}").status_code == 403
    assert "subscription" not in c.get(f"/api/admin/tenants/{firm['id']}").json()
    h = c.post(f"/api/admin/tenants/{firm['id']}/hosts", json={"name": "Bo Bent", "email": "bo@firma1.dk"})
    assert h.status_code == 200

    # Kan invitere kolleger, men ikke fjerne sig selv.
    inv = c.post(f"/api/admin/tenants/{firm['id']}/users", json={"email": "kollega@firma1.dk"}).json()
    users = c.get(f"/api/admin/tenants/{firm['id']}/users").json()
    assert {u["email"] for u in users} == {"anna@firma1.dk", "kollega@firma1.dk"}
    me_id = next(u["id"] for u in users if u["email"] == "anna@firma1.dk")
    assert c.delete(f"/api/admin/users/{me_id}").status_code == 400
    assert c.delete(f"/api/admin/users/{inv['user']['id']}").status_code == 200

    # Når selvbetjening slås fra, er man ude med det samme.
    platform.patch(f"/api/admin/tenants/{firm['id']}/subscription", json={"self_service": False})
    assert c.get("/api/admin/tenants").status_code == 403
    platform.patch(f"/api/admin/tenants/{firm['id']}/subscription", json={"self_service": True})


def test_tenant_admin_cannot_reach_other_firms(setup, platform):
    other = platform.post("/api/admin/tenants", json={"name": "Andet firma"}).json()
    other_host = platform.post(f"/api/admin/tenants/{other['id']}/hosts", json={"name": "Hemmelig"}).json()
    c = new_client()
    c.post("/api/admin/login", json={"email": "anna@firma1.dk", "password": "annas-kode-1234"})
    assert c.get(f"/api/admin/tenants/{other['id']}").status_code == 404
    assert c.get(f"/api/admin/tenants/{other['id']}/visits").status_code == 404
    assert c.get(f"/api/admin/tenants/{other['id']}/users").status_code == 404
    assert c.patch(f"/api/admin/hosts/{other_host['id']}", json={"name": "x"}).status_code == 404
    assert c.delete(f"/api/admin/hosts/{other_host['id']}").status_code == 404
    assert c.post(f"/api/admin/tenants/{other['id']}/users", json={"email": "ind@brud.dk"}).status_code == 404
    assert c.get("/api/admin/partners").json() == []
    platform.delete(f"/api/admin/tenants/{other['id']}")


def test_links_are_single_use_and_new_link_logs_out(setup, platform):
    firm = setup["firm"]
    inv = platform.post(f"/api/admin/tenants/{firm['id']}/users", json={"email": "engang@firma1.dk"}).json()
    token = token_of(inv["invite_url"])
    info = new_client().get(f"/api/admin/invite/{token}").json()
    assert info == {"email": "engang@firma1.dk", "name": "", "new": True}
    c, r = accept(token)
    assert r.status_code == 200
    assert c.get("/api/admin/me").status_code == 200
    _, again = accept(token)
    assert again.status_code == 400

    # Nyt link (fx glemt adgangskode) gør gamle sessioner ugyldige.
    link = platform.post(f"/api/admin/users/{inv['user']['id']}/link").json()
    assert c.get("/api/admin/me").status_code == 401
    assert not link["user"]["pending"]
    assert accept(token_of(link["invite_url"]), "helt-ny-kode-99")[1].status_code == 200
    assert new_client().post("/api/admin/invite/accept", json={"token": "falsk", "password": "x" * 12}).status_code == 400


def test_login_errors_and_duplicates(setup, platform):
    c = new_client()
    assert c.post("/api/admin/login", json={"email": "anna@firma1.dk", "password": "forkert-kode"}).status_code == 401
    assert c.post("/api/admin/login", json={"email": "findes@ikke.dk", "password": "forkert-kode"}).status_code == 401
    assert c.post("/api/admin/login", json={"password": "forkert"}).status_code == 401
    r = platform.post(f"/api/admin/tenants/{setup['firm']['id']}/users", json={"email": "anna@firma1.dk"})
    assert r.status_code == 409
    assert platform.post(f"/api/admin/tenants/{setup['firm']['id']}/users", json={"email": "ikke-en-mail"}).status_code == 422
    short = platform.post(f"/api/admin/tenants/{setup['firm']['id']}/users", json={"email": "kort@firma1.dk"}).json()
    assert accept(token_of(short["invite_url"]), "kort")[1].status_code == 422
    r = new_client().post("/api/admin/forgot", json={"email": "anna@firma1.dk"})
    assert r.status_code == 200 and "Hvis e-mailen" in r.json()["message"]


def test_partner_cannot_be_deleted_with_firms_and_inactive_partner_is_locked_out(setup, platform):
    pid = setup["partner"]["id"]
    assert platform.delete(f"/api/admin/partners/{pid}").status_code == 409
    platform.patch(f"/api/admin/partners/{pid}", json={"active": False})
    assert setup["pa"].get("/api/admin/tenants").status_code == 403
    platform.patch(f"/api/admin/partners/{pid}", json={"active": True})
    assert setup["pa"].get("/api/admin/tenants").status_code == 200
    partners = platform.get("/api/admin/partners").json()
    p = next(x for x in partners if x["id"] == pid)
    assert p["tenant_count"] == 1 and p["user_count"] == 1


def test_invite_email_has_logo_button_and_plain_text():
    from app.models import User
    from app.routes_access import link_email
    u = User(email="ny@firma.dk", name="Ny <Kollega>")
    subject, text, page = link_email(u, "https://nodd.example/admin#invite=abc", "invite")
    assert subject == "Du er inviteret til Nodd"
    assert "https://nodd.example/admin#invite=abc" in text and "Hej Ny <Kollega>" in text
    assert 'src="https://nodd.example/static/brand/nodd-lockup.png"' in page
    assert "Ny &lt;Kollega&gt;" in page and "<Kollega>" not in page


def test_rooms_of_other_firms_and_houses_are_hidden(setup, platform):
    other = platform.post("/api/admin/tenants", json={"name": "Fremmed firma"}).json()
    platform.post(f"/api/admin/billing/account/subscriptions?tenant_id={other['id']}", json={"product": "rooms"})
    room = platform.post("/api/admin/rooms", json={"tenant_id": other["id"], "name": "Fremmed lokale"}).json()
    pa = setup["pa"]  # partner-admin for et andet hus
    assert pa.get(f"/api/admin/rooms?tenant_id={other['id']}").status_code == 404
    assert pa.get(f"/api/admin/bookings?tenant_id={other['id']}").status_code == 404
    assert pa.patch(f"/api/admin/rooms/{room['id']}", json={"name": "x"}).status_code == 404
    assert pa.delete(f"/api/admin/rooms/{room['id']}").status_code == 404
    assert pa.post(f"/api/admin/rooms/{room['id']}/screen-link").status_code == 404
    assert pa.post("/api/admin/bookings", json={"room_id": room["id"], "tenant_id": other["id"],
                                                "start": "2030-01-01T10:00", "end": "2030-01-01T11:00"}).status_code == 404
    assert new_client().get(f"/api/admin/rooms?tenant_id={other['id']}").status_code == 401
    platform.delete(f"/api/admin/tenants/{other['id']}")


def test_kitchens_of_other_firms_are_hidden(setup, platform):
    other = platform.post("/api/admin/tenants", json={"name": "Fremmed køkkenfirma"}).json()
    platform.post(f"/api/admin/billing/account/subscriptions?tenant_id={other['id']}", json={"product": "catering"})
    k = platform.post("/api/admin/kitchens", json={"tenant_id": other["id"], "name": "Fremmed køkken"}).json()
    item = platform.post(f"/api/admin/kitchens/{k['id']}/items", json={"name": "Kage", "price": 10}).json()
    pa = setup["pa"]  # partner-admin for et andet hus
    assert pa.get(f"/api/admin/kitchens?tenant_id={other['id']}").status_code == 404
    assert pa.patch(f"/api/admin/kitchens/{k['id']}", json={"name": "x"}).status_code == 404
    assert pa.delete(f"/api/admin/kitchens/{k['id']}").status_code == 404
    assert pa.post(f"/api/admin/kitchens/{k['id']}/sample-menu").status_code == 404
    assert pa.patch(f"/api/admin/menu-items/{item['id']}", json={"price": 1}).status_code == 404
    assert pa.get(f"/api/admin/catering-orders?tenant_id={other['id']}").status_code == 404
    assert pa.put("/api/admin/bookings/999999/catering", json={"kitchen_id": k["id"], "items": []}).status_code == 404
    assert new_client().get(f"/api/admin/kitchens?tenant_id={other['id']}").status_code == 401
    platform.delete(f"/api/admin/tenants/{other['id']}")


def test_billing_is_platform_only(setup, platform):
    pa = setup["pa"]
    pid = setup["partner"]["id"]
    for method, url in [("GET", "/api/admin/billing/products"), ("GET", f"/api/admin/billing/account?partner_id={pid}"),
                        ("POST", "/api/admin/billing/run"), ("GET", "/api/admin/billing/invoices"),
                        ("GET", "/api/admin/billing/invoices.csv")]:
        assert pa.request(method, url, json={"period_start": "2030-01-01"}).status_code == 403, url
    assert new_client().get("/api/admin/billing/invoices").status_code == 401
