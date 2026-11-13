"""Hvornår hver skærm sidst har været i kontakt med serveren.

Ligger i hukommelsen, ikke i databasen, så skærmens polling aldrig vækker Azure SQL's gratis-database.
Efter en genstart er status "ukendt", indtil skærmen melder sig igen (inden for et minut).
Kører appen en dag på flere servere, skal dette flyttes til en fælles cache (fx Redis).
"""
import time

ONLINE_SECONDS = 180  # skærmen spørger hvert minut, når den står på startskærmen

_seen: dict[str, float] = {}


def mark(token: str) -> None:
    _seen[token] = time.time()


def last_seen(token: str) -> float | None:
    return _seen.get(token)


def status(token: str) -> dict:
    ts = _seen.get(token)
    return {"seen_at": ts, "online": ts is not None and time.time() - ts < ONLINE_SECONDS}


def reset() -> None:
    _seen.clear()
