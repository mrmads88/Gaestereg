"""To-trins-login (TOTP) med engangskoder, krav for leverandør og huse og nulstilling."""
import pytest
from fastapi.testclient import TestClient

from app import mfa, ratelimit
from app.config import settings
from app.db import SessionLocal
from app.main import app
from app.models import PlatformAccount


@pytest.fixture(scope="module")
def plat(client):
    c = TestClient(app)
    assert c.post("/api/admin/login", json={"password": "hemmelig"}).status_code == 200
    return c


@pytest.fixture(autouse=True)
def _clean_limits():
    ratelimit.reset()
    yield
    ratelimit.reset()


def now_code(secret: str, offset: int = 0) -> str:
    return mfa.code_at(secret, mfa.current_step() + offset)


def make_user(plat, email: str, partner: bool = False):
    if partner:
        org = plat.post("/api/admin/partners", json={"name": "Hus " + email}).json()
        link = plat.post(f"/api/admin/partners/{org['id']}/users", json={"email": email}).json()["invite_url"]
    else:
        org = plat.post("/api/admin/tenants", json={"name": "Firma " + email}).json()
        plat.patch(f"/api/admin/tenants/{org['id']}/subscription", json={"self_service": True})
        link = plat.post(f"/api/admin/tenants/{org['id']}/users", json={"email": email}).json()["invite_url"]
    c = TestClient(app)
    assert c.post("/api/admin/invite/accept", json={"token": link.split("#invite=")[1],
                                                     "password": "lang-kode-1234"}).status_code == 200
    return c, org


def turn_on(c) -> tuple[str, list[str]]:
    s = c.post("/api/admin/mfa/setup").json()
    secret = s["secret"].replace(" ", "")
    assert s["uri"].startswith("otpauth://totp/Nodd:") and "<svg" in s["qr"]
    assert c.post("/api/admin/mfa/enable", json={"code": "000000" if now_code(secret) != "000000" else "111111"}).status_code == 400
    r = c.post("/api/admin/mfa/enable", json={"code": now_code(secret)})
    assert r.status_code == 200, r.text
    codes = r.json()["recovery_codes"]
    assert len(codes) == 10 and r.json()["enabled"]
    return secret, codes


def test_totp_matches_rfc_6238():
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # "12345678901234567890"
    assert mfa.code_at(secret, 59 // 30) == "287082"
    assert mfa.code_at(secret, 1111111109 // 30) == "081804"
    assert mfa.check_totp(secret, "287 082", 0, now=59) == 1
    assert mfa.check_totp(secret, "287082", 1, now=59) is None  # samme kode to gange
    assert mfa.check_totp(secret, "287082", 0, now=59 + 90) is None  # for gammel


def test_user_turns_on_and_logs_in_with_code(plat):
    c, org = make_user(plat, "to-trin@firma.dk")
    other = TestClient(app)
    other.post("/api/admin/login", json={"email": "to-trin@firma.dk", "password": "lang-kode-1234"})
    assert c.get("/api/admin/me").json()["mfa"] == {"enabled": False, "required": False}
    secret, codes = turn_on(c)
    assert c.get("/api/admin/me").status_code == 200  # denne session fortsætter
    assert other.get("/api/admin/me").status_code == 401  # andre sessioner er logget ud

    fresh = TestClient(app)
    r = fresh.post("/api/admin/login", json={"email": "to-trin@firma.dk", "password": "lang-kode-1234"}).json()
    assert r["mfa"] and r["ticket"]
    assert fresh.get("/api/admin/me").status_code == 401  # adgangskoden alene giver ikke adgang
    assert fresh.post("/api/admin/login/mfa", json={"ticket": r["ticket"], "code": "12"}).status_code == 401
    assert fresh.post("/api/admin/login/mfa", json={"ticket": "falsk", "code": now_code(secret)}).status_code == 401
    code = now_code(secret, 1)
    ok = fresh.post("/api/admin/login/mfa", json={"ticket": r["ticket"], "code": code})
    assert ok.status_code == 200 and ok.json()["recovery_left"] == 10
    assert fresh.get("/api/admin/me").json()["mfa"]["enabled"]

    # Samme kode kan ikke bruges igen; en engangskode virker én gang.
    again = TestClient(app)
    t = again.post("/api/admin/login", json={"email": "to-trin@firma.dk", "password": "lang-kode-1234"}).json()["ticket"]
    assert again.post("/api/admin/login/mfa", json={"ticket": t, "code": code}).status_code == 401
    assert again.post("/api/admin/login/mfa", json={"ticket": t, "code": codes[0].upper()}).json()["recovery_left"] == 9
    t2 = TestClient(app).post("/api/admin/login", json={"email": "to-trin@firma.dk", "password": "lang-kode-1234"}).json()["ticket"]
    assert TestClient(app).post("/api/admin/login/mfa", json={"ticket": t2, "code": codes[0]}).status_code == 401

    # Nye engangskoder og slå fra kræver en kode.
    assert again.post("/api/admin/mfa/recovery", json={"code": "nej"}).status_code == 400
    new = again.post("/api/admin/mfa/recovery", json={"code": codes[1]}).json()["recovery_codes"]
    assert len(new) == 10 and new[0] != codes[2]
    assert again.post("/api/admin/mfa/disable", json={"code": codes[2]}).status_code == 400  # gamle koder er væk
    assert again.post("/api/admin/mfa/disable", json={"code": now_code(secret, -1)}).status_code == 400  # ældre end sidst brugte
    off = again.post("/api/admin/mfa/disable", json={"code": new[0]})
    assert off.status_code == 200 and not off.json()["enabled"]
    assert "ticket" not in TestClient(app).post("/api/admin/login", json={"email": "to-trin@firma.dk",
                                                                           "password": "lang-kode-1234"}).json()
    plat.delete(f"/api/admin/tenants/{org['id']}")


def test_too_many_wrong_codes_are_blocked(plat):
    c, org = make_user(plat, "gaet@firma.dk")
    secret, _ = turn_on(c)
    x = TestClient(app)
    t = x.post("/api/admin/login", json={"email": "gaet@firma.dk", "password": "lang-kode-1234"}).json()["ticket"]
    wrong = "000000" if now_code(secret) != "000000" else "111111"
    for _ in range(5):
        assert x.post("/api/admin/login/mfa", json={"ticket": t, "code": wrong}).status_code == 401
    assert x.post("/api/admin/login/mfa", json={"ticket": t, "code": now_code(secret)}).status_code == 429
    plat.delete(f"/api/admin/tenants/{org['id']}")


def test_reset_link_does_not_skip_second_step(plat):
    c, org = make_user(plat, "glemt@firma.dk")
    turn_on(c)
    uid = next(u["id"] for u in plat.get(f"/api/admin/tenants/{org['id']}/users").json() if u["email"] == "glemt@firma.dk")
    link = plat.post(f"/api/admin/users/{uid}/link").json()["invite_url"]
    x = TestClient(app)
    r = x.post("/api/admin/invite/accept", json={"token": link.split("#invite=")[1], "password": "ny-lang-kode-99"}).json()
    assert r["mfa"] and r["ticket"] and x.get("/api/admin/me").status_code == 401
    plat.delete(f"/api/admin/tenants/{org['id']}")


def test_admin_can_reset_someone_elses(plat):
    c, org = make_user(plat, "mistet@firma.dk")
    turn_on(c)
    users = plat.get(f"/api/admin/tenants/{org['id']}/users").json()
    u = next(x for x in users if x["email"] == "mistet@firma.dk")
    assert u["mfa"]
    assert c.post(f"/api/admin/users/{u['id']}/mfa-reset").status_code == 400  # ikke sig selv her
    r = plat.post(f"/api/admin/users/{u['id']}/mfa-reset")
    assert r.status_code == 200 and not r.json()["mfa"]
    assert c.get("/api/admin/me").status_code == 401  # logget ud
    stranger, org2 = make_user(plat, "fremmed@firma.dk")
    assert stranger.post(f"/api/admin/users/{u['id']}/mfa-reset").status_code == 404
    plat.delete(f"/api/admin/tenants/{org['id']}")
    plat.delete(f"/api/admin/tenants/{org2['id']}")


def test_required_for_houses_blocks_until_set_up(plat, monkeypatch):
    c, org = make_user(plat, "hus@huset.dk", partner=True)
    tc, torg = make_user(plat, "kunde@kravfirma.dk")
    monkeypatch.setattr(settings, "mfa_required", True)
    assert c.get("/api/admin/me").json()["mfa"] == {"enabled": False, "required": True}
    r = c.get("/api/admin/tenants")
    assert r.status_code == 403 and "to-trins-login" in r.json()["detail"]
    assert tc.get("/api/admin/tenants").status_code == 200  # frivilligt for kunde-admins
    secret, _ = turn_on(c)
    assert c.get("/api/admin/tenants").status_code == 200
    assert c.post("/api/admin/mfa/disable", json={"code": now_code(secret, 1)}).status_code == 422
    plat.delete(f"/api/admin/tenants/{torg['id']}")
    plat.delete(f"/api/admin/partners/{org['id']}")


def test_platform_login_with_second_step(plat):
    with SessionLocal() as db:
        acc = mfa.platform_account(db)
        db.commit()
        old_version = acc.token_version
    c = TestClient(app)
    c.post("/api/admin/login", json={"password": "hemmelig"})
    try:
        secret, codes = turn_on(c)
        assert plat.get("/api/admin/me").status_code == 401  # andre leverandør-sessioner er logget ud
        x = TestClient(app)
        r = x.post("/api/admin/login", json={"password": "hemmelig"}).json()
        assert r["mfa"] and x.get("/api/admin/me").status_code == 401
        assert x.post("/api/admin/login/mfa", json={"ticket": r["ticket"], "code": codes[3]}).status_code == 200
        me = x.get("/api/admin/me").json()
        assert me["role"] == "platform" and me["mfa"]["enabled"]
        assert {"mfa", "mfa_required"} <= {k["key"] for k in me["readiness"]}
        assert next(k for k in me["readiness"] if k["key"] == "mfa")["ok"]
        # Nødknappen: ADMIN_MFA_RESET=1 slår det fra ved opstart.
        settings.admin_mfa_reset = True
        try:
            mfa.reset_platform_on_start()
        finally:
            settings.admin_mfa_reset = False
        assert "ticket" not in TestClient(app).post("/api/admin/login", json={"password": "hemmelig"}).json()
    finally:
        with SessionLocal() as db:  # de andre tests' leverandør-sessioner skal virke igen
            acc = db.get(PlatformAccount, acc.id)
            mfa.disable(acc)
            acc.token_version = old_version
            db.commit()
    assert plat.get("/api/admin/me").status_code == 200
