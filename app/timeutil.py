from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .config import settings

TZ = ZoneInfo(settings.timezone)


def to_local(dt: datetime | None) -> datetime | None:
    """DB stores naive UTC. Convert to the configured local zone."""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).astimezone(TZ)


def local_hhmm(dt: datetime | None) -> str:
    d = to_local(dt)
    return d.strftime("%H:%M") if d else ""


def local_iso(dt: datetime | None) -> str | None:
    d = to_local(dt)
    return d.isoformat(timespec="minutes") if d else None


def start_of_local_day_utc(now: datetime | None = None) -> datetime:
    """Midnight today (local) expressed as naive UTC, for 'today' queries."""
    now_local = (now or datetime.now(timezone.utc)).astimezone(TZ)
    midnight = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.astimezone(timezone.utc).replace(tzinfo=None)


def days_ago_utc(days: int) -> datetime:
    return (datetime.now(timezone.utc) - timedelta(days=days)).replace(tzinfo=None)


def from_local(value: str) -> datetime:
    """'2026-11-14T10:30' i lokal tid -> naiv UTC, som databasen gemmer."""
    d = datetime.fromisoformat(value)
    if d.tzinfo is None:
        d = d.replace(tzinfo=TZ)
    return d.astimezone(timezone.utc).replace(tzinfo=None)


def local_day_label(dt: datetime) -> str:
    """Fx 'i dag', 'i morgen' eller 'fredag 14. november'."""
    d = to_local(dt)
    today = datetime.now(TZ).date()
    if d.date() == today:
        return "i dag"
    if d.date() == today + timedelta(days=1):
        return "i morgen"
    days = ["mandag", "tirsdag", "onsdag", "torsdag", "fredag", "lørdag", "søndag"]
    months = ["januar", "februar", "marts", "april", "maj", "juni", "juli", "august", "september", "oktober",
              "november", "december"]
    return f"{days[d.weekday()]} {d.day}. {months[d.month - 1]}"
