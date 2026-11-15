"""Hjælpecentret og "?"-hjælpen: siden findes, guides findes på dansk og engelsk, og tips peger på rigtige steder."""
import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"


def help_data() -> dict:
    """help-content.js er JavaScript; vi læser den ved at gøre objektet til JSON (nøgler i anførselstegn)."""
    import subprocess
    js = "global.window={};require(process.argv[1]);console.log(JSON.stringify(window.NODD_HELP))"
    out = subprocess.run(["node", "-e", js, str(STATIC / "help-content.js")], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_help_page_is_public():
    for path in ("/hjaelp", "/help"):
        r = TestClient(app).get(path)
        assert r.status_code == 200 and "help-content.js" in r.text


def test_guides_exist_in_both_languages():
    h = help_data()
    ids = [g["id"] for g in h["guides"]]
    assert len(ids) == len(set(ids)) >= 12
    for g in h["guides"]:
        assert g["title"]["da"] and g["title"]["en"] and g["intro"]["da"] and g["intro"]["en"], g["id"]
        assert len(g["steps"]["da"]) == len(g["steps"]["en"]) >= 3, g["id"]
        assert len(g["tips"]["da"]) == len(g["tips"]["en"]), g["id"]
        assert set(g["roles"]) <= set(h["roles"]), g["id"]


def test_tips_point_to_guides_and_real_headings():
    h = help_data()
    ids = {g["id"] for g in h["guides"]}
    admin = (STATIC / "admin.html").read_text(encoding="utf-8") + "".join(
        f.read_text(encoding="utf-8") for f in STATIC.glob("admin-*.js"))
    for key, tip in h["tips"].items():
        assert tip["guide"] in ids, key
        assert tip["da"] and tip["en"], key
        # Overskriften findes i admin, så "?" kan sættes på den.
        assert re.search(r"[>\"]\s*" + re.escape(key) + r"\s*[<\"]", admin), f"Overskriften '{key}' findes ikke i admin"
