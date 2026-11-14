"""Drift: fejlmails med begrænsning, oppetidstjek med database og "klar til prod"-listen."""
import logging

from fastapi.testclient import TestClient

from app import ops
from app.config import settings
from app.main import app


def test_error_mails_are_throttled(monkeypatch):
    sent = []
    monkeypatch.setattr(ops, "_send", lambda subject, body: sent.append((subject, body)))
    monkeypatch.setattr(ops.threading, "Thread", lambda target, args, daemon: type("T", (), {"start": lambda self: target(*args)})())
    monkeypatch.setattr(settings, "ops_email", "drift@example.com")
    monkeypatch.setattr(settings, "notify_mode", "live")
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_from", "noreply@example.com")
    h = ops.OpsMailHandler()
    log = logging.getLogger("test.ops")
    log.propagate = False  # kun testens egen handler (appen har sin egen på rodloggeren)
    log.addHandler(h)
    try:
        for _ in range(5):
            try:
                raise ValueError("databasen er væk")
            except ValueError:
                log.exception("Uventet fejl i /api/x")
        log.error("En anden fejl")
        log.warning("Kun en advarsel")  # sendes ikke
    finally:
        log.removeHandler(h)
    assert len(sent) == 2  # samme fejl kun én gang pr. 15 minutter
    assert "databasen er væk" in sent[0][0] and "Traceback" in sent[0][1] and "ValueError" in sent[0][1]
    assert sent[1][0].endswith("En anden fejl")


def test_no_error_mails_in_test_mode(monkeypatch):
    sent = []
    monkeypatch.setattr(ops, "_send", lambda s, b: sent.append(s))
    monkeypatch.setattr(settings, "ops_email", "drift@example.com")
    h = ops.OpsMailHandler()
    h.emit(logging.LogRecord("x", logging.ERROR, __file__, 1, "fejl", None, None))
    assert sent == []  # NOTIFY_MODE=test i tests


def test_health_with_and_without_database(client):
    c = TestClient(app)
    assert c.get("/healthz").json() == {"ok": True, "env": "local"}
    assert c.get("/healthz?db=1").json()["db"] == "ok"


def test_readiness_only_for_platform(client):
    c = TestClient(app)
    c.post("/api/admin/login", json={"password": "hemmelig"})
    r = c.get("/api/admin/me").json()["readiness"]
    keys = {x["key"]: x for x in r}
    assert set(keys) >= {"live", "sms", "smtp", "blob", "url", "ops", "operator", "dpa", "password"}
    assert not keys["live"]["ok"] and keys["password"]["ok"] and not keys["live"]["required"]  # lokalt, ikke prod
