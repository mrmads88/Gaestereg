"""Værtens svar ("kommer om 5 min") og påmindelser, når værten ikke reagerer.

Svarlinket i SMS/mail er et signeret token med besøgets id, så det ikke kan gættes.
Svaret gemmes i databasen (én skrivning, når værten trykker) og i hukommelsen, så skærmen kan spørge
efter det hvert par sekunder uden at vække databasen.
Påmindelser er timere i hukommelsen. De forsvinder ved genstart, hvilket er acceptabelt: værten har stadig
fået den første besked. Kører appen en dag på flere servere, skal dette flyttes til en fælles kø.
"""
import threading
import time

from itsdangerous import BadSignature, SignatureExpired, TimestampSigner

from .config import settings

TOKEN_MAX_AGE = 24 * 3600
ANSWERS = {"now": "Jeg kommer nu", "5": "Jeg kommer om 5 minutter", "10": "Jeg kommer om 10 minutter",
           "reception": "Jeg kan ikke. Receptionen tager imod"}

_signer = TimestampSigner(settings.secret_key, salt="host-reply")
_answers: dict[int, tuple[str, float]] = {}   # visit_id -> (svar, tidspunkt)
_kiosk: dict[int, str] = {}                   # visit_id -> skærmens token, så skærmen kun ser egne besøg
_timers: dict[int, threading.Timer] = {}


def token_for(visit_id: int) -> str:
    return _signer.sign(str(visit_id).encode()).decode()


def visit_from_token(token: str) -> int | None:
    try:
        return int(_signer.unsign(token, max_age=TOKEN_MAX_AGE).decode())
    except (BadSignature, SignatureExpired, ValueError):
        return None


def link(base_url: str, visit_id: int) -> str:
    return f"{base_url.rstrip('/')}/r/{token_for(visit_id)}" if base_url else ""


def register(visit_id: int, kiosk_token: str) -> None:
    _kiosk[visit_id] = kiosk_token
    _cleanup()


def record(visit_id: int, answer: str) -> None:
    _answers[visit_id] = (answer, time.time())
    cancel(visit_id)


def answer_for_kiosk(kiosk_token: str, visit_id: int) -> str | None:
    if _kiosk.get(visit_id) != kiosk_token:
        return None
    a = _answers.get(visit_id)
    return a[0] if a else None


def answered(visit_id: int) -> bool:
    return visit_id in _answers


def schedule(visit_id: int, minutes: int, fn) -> None:
    if minutes <= 0:
        return
    cancel(visit_id)
    t = threading.Timer(minutes * 60, _run, args=(visit_id, fn))
    t.daemon = True
    _timers[visit_id] = t
    t.start()


def _run(visit_id: int, fn) -> None:
    _timers.pop(visit_id, None)
    if not answered(visit_id):
        fn(visit_id)


def cancel(visit_id: int) -> None:
    t = _timers.pop(visit_id, None)
    if t:
        t.cancel()


def _cleanup() -> None:
    """Glem svar og skærm-koblinger, der er over et døgn gamle."""
    cutoff = time.time() - TOKEN_MAX_AGE
    for vid in [v for v, (_, ts) in _answers.items() if ts < cutoff]:
        _answers.pop(vid, None)
    if len(_kiosk) > 5000:
        for vid in sorted(_kiosk)[:2500]:
            _kiosk.pop(vid, None)


def reset() -> None:
    for t in list(_timers.values()):
        t.cancel()
    _timers.clear()
    _answers.clear()
    _kiosk.clear()
