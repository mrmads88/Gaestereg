"""Admin på engelsk: ordbogen dækker alle danske tekster, siderne har sprogfilerne, og sproget gemmes på brugeren."""
import importlib.util
import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.models import User
from app.routes_access import link_email

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "app" / "static"
spec = importlib.util.spec_from_file_location("i18n_extract", ROOT / "tools" / "i18n_extract.py")
extract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extract)


def test_every_danish_text_has_an_english_translation():
    missing = extract.missing()
    assert not missing, ("Disse tekster mangler i app/static/i18n-en.js (kør python tools/i18n_extract.py --json):\n"
                         + "\n".join(missing[:40]))
    words = extract.catalog()
    assert all(isinstance(v, str) and v.strip() for v in words.values())
    assert words["Gem"] == "Save" and words["Log ud"] == "Log out"


def test_patterns_are_valid():
    src = (STATIC / "i18n-en.js").read_text(encoding="utf-8")
    patterns = json.loads(src.split("window.NODD_EN_PATTERNS = ", 1)[1].rsplit(";", 1)[0])
    for p, rep in patterns:
        re.compile("^" + p + "$")
        assert isinstance(rep, str) and rep


def test_pages_load_the_translator_and_format_dates_by_language():
    for f in extract.HTML_FILES:
        html = f.read_text(encoding="utf-8")
        assert html.index("/static/i18n-en.js") < html.index("/static/i18n.js"), f.name
    for f in list(extract.JS_FILES) + list(extract.HTML_FILES):
        assert '"da-DK"' not in f.read_text(encoding="utf-8"), f"{f.name}: brug NODD_LOC() i stedet for \"da-DK\""


def test_language_is_saved_on_the_user_and_inherited(client):
    plat = TestClient(app)
    plat.post("/api/admin/login", json={"password": "hemmelig"})
    assert plat.get("/api/admin/me").json()["lang"] == "da"
    assert plat.patch("/api/admin/me/lang", json={"lang": "de"}).status_code == 422
    assert plat.patch("/api/admin/me/lang", json={"lang": "en"}).json()["lang"] == "en"
    try:
        assert plat.get("/api/admin/me").json()["lang"] == "en"
        t = plat.post("/api/admin/tenants", json={"name": "Sprogfirma"}).json()
        plat.patch(f"/api/admin/tenants/{t['id']}/subscription", json={"self_service": True})
        link = plat.post(f"/api/admin/tenants/{t['id']}/users", json={"email": "en@sprog.dk"}).json()["invite_url"]
        c = TestClient(app)
        c.post("/api/admin/invite/accept", json={"token": link.split("#invite=")[1], "password": "lang-kode-1234"})
        assert c.get("/api/admin/me").json()["lang"] == "en"  # samme sprog som den, der inviterede
        assert c.patch("/api/admin/me/lang", json={"lang": "da"}).json()["lang"] == "da"
        plat.delete(f"/api/admin/tenants/{t['id']}")
    finally:
        plat.patch("/api/admin/me/lang", json={"lang": "da"})
    assert TestClient(app).patch("/api/admin/me/lang", json={"lang": "en"}).status_code == 401


def test_invitation_mail_follows_the_users_language():
    subject, text, html = link_email(User(email="a@b.dk", name="Anna", lang="en"), "https://x/admin#invite=1", "invite")
    assert subject == "You have been invited to Nodd" and "Choose password" in html and 'lang="en"' in html
    subject, _, html = link_email(User(email="a@b.dk", name="Anna", lang="da"), "https://x/admin#invite=1", "reset")
    assert subject == "Ny adgangskode til Nodd" and "Vælg ny adgangskode" in html and 'lang="da"' in html
