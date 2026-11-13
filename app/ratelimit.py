"""Begrænsning af forsøg (login, glemt adgangskode) i hukommelsen.

Gætter nogen på adgangskoder, bliver de bremset efter et antal fejl inden for et tidsrum.
Ligger i hukommelsen, ligesom presence.py. Én worker (startup.sh) betyder én fælles tæller.
"""
import time
from collections import deque

from fastapi import HTTPException

_hits: dict[str, deque] = {}


def _window(key: str, seconds: int) -> deque:
    q = _hits.setdefault(key, deque())
    now = time.time()
    while q and now - q[0] > seconds:
        q.popleft()
    return q


def check(key: str, limit: int, seconds: int) -> None:
    """Afvis, hvis der allerede er `limit` forsøg inden for `seconds`."""
    q = _window(key, seconds)
    if len(q) >= limit:
        wait = int(seconds - (time.time() - q[0])) // 60 + 1
        raise HTTPException(429, f"For mange forsøg. Prøv igen om {wait} minut{'ter' if wait != 1 else ''}.")


def hit(key: str) -> None:
    _hits.setdefault(key, deque()).append(time.time())


def clear(key: str) -> None:
    _hits.pop(key, None)


def reset() -> None:
    _hits.clear()
