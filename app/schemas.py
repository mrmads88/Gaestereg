import json
import re
from datetime import date, datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from . import modules, presence
from .media import media_url
from .models import Host, Partner, Tenant, User
from .timeutil import local_iso

HEX = r"^#[0-9a-fA-F]{6}$"

# Sprog, skærmen kan vises på. Skal passe med app/static/langs.js (flag og navne) og T i kiosk.js (tekster).
# Nyt sprog: tilføj koden her, en post i langs.js og teksterne i kiosk.js. tests/test_api.py tjekker, at de passer.
SUPPORTED_LANGS = ["da", "en"]


class TenantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    partner_id: int | None = None  # kun platform. Partner-admins får altid deres egen partner.


class TenantUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    active: bool | None = None
    color: str | None = Field(None, pattern=HEX)
    background_scope: Literal["wall", "full"] | None = None
    background_dim: int | None = Field(None, ge=0, le=90)
    welcome_text: str | None = Field(None, max_length=200)
    show_photos: bool | None = None
    name_required: bool | None = None
    ask_phone: bool | None = None
    phone_required: bool | None = None
    ask_company: bool | None = None
    allow_unknown_host: bool | None = None
    reception_email: str | None = Field(None, max_length=200)
    reception_phone: str | None = Field(None, max_length=40)
    print_badge: bool | None = None
    badge_size: Literal["62x100", "54x86", "a6"] | None = None
    idle_seconds: int | None = Field(None, ge=15, le=600)
    wifi_name: str | None = Field(None, max_length=64)
    wifi_password: str | None = Field(None, max_length=64)
    delivery_enabled: bool | None = None
    delivery_email: str | None = Field(None, max_length=200)
    delivery_phone: str | None = Field(None, max_length=40)
    delivery_note: str | None = Field(None, max_length=300)
    opening_hours: list[list[str] | None] | None = None  # 7 dage, mandag først. [] = altid åben
    closed_text: str | None = Field(None, max_length=300)
    group_checkin: bool | None = None
    terms_enabled: bool | None = None
    terms_title: str | None = Field(None, max_length=120)
    terms_text: str | None = Field(None, max_length=8000)
    host_reply: bool | None = None
    escalate_minutes: int | None = Field(None, ge=0, le=120)
    teams_webhook: str | None = Field(None, max_length=1000)
    report_email: str | None = Field(None, max_length=500)
    house_screen: bool | None = None
    meeting_privacy: Literal["", "title", "organizer", "busy"] | None = None
    languages: list[str] | None = Field(None, min_length=1, max_length=len(SUPPORTED_LANGS))
    lang_default: str | None = None
    lang_mode: Literal["toggle", "first", "off"] | None = None

    @field_validator("languages")
    @classmethod
    def _langs(cls, v):
        if v is None:
            return v
        if any(x not in SUPPORTED_LANGS for x in v) or len(set(v)) != len(v):
            raise ValueError("Ukendt eller gentaget sprog")
        return v

    @field_validator("opening_hours")
    @classmethod
    def _hours(cls, v):
        if v is None or v == []:
            return v
        if len(v) != 7:
            raise ValueError("Åbningstider skal have 7 dage")
        for day in v:
            if day is None:
                continue
            if len(day) != 2 or not all(re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", x) for x in day) or day[0] >= day[1]:
                raise ValueError("Skriv åbningstider som 08:00 til 16:00, hvor åbning er før lukning")
        return v

    @field_validator("report_email")
    @classmethod
    def _report(cls, v):
        return clean_emails(v)

    @field_validator("teams_webhook")
    @classmethod
    def _teams(cls, v):
        if v and not v.startswith("https://"):
            raise ValueError("Teams-adressen skal starte med https://")
        return v

    @field_validator("lang_default")
    @classmethod
    def _lang_default(cls, v):
        if v is not None and v not in SUPPORTED_LANGS:
            raise ValueError("Ukendt sprog")
        return v
    retention_days: int | None = Field(None, ge=1, le=365)
    sms_sender: str | None = Field(None, max_length=11)
    sms_template: str | None = Field(None, max_length=640)
    email_subject: str | None = Field(None, max_length=200)
    email_template: str | None = Field(None, max_length=4000)

    @field_validator("sms_sender")
    @classmethod
    def _sender(cls, v):
        if v is not None and v and not all(c.isalnum() or c == " " for c in v):
            raise ValueError("Afsendernavn må kun indeholde bogstaver, tal og mellemrum")
        return v


class HostIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    title: str = Field("", max_length=120)
    email: str = Field("", max_length=200)
    phone: str = Field("", max_length=40)
    notify_sms: bool = True
    notify_email: bool = True
    active: bool = True


class HostUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    title: str | None = Field(None, max_length=120)
    email: str | None = Field(None, max_length=200)
    phone: str | None = Field(None, max_length=40)
    notify_sms: bool | None = None
    notify_email: bool | None = None
    active: bool | None = None


class Reorder(BaseModel):
    ids: list[int]


class CheckinIn(BaseModel):
    host_id: int | None = None
    guest_name: str = Field("", max_length=120)
    guest_phone: str = Field("", max_length=40)
    guest_company: str = Field("", max_length=120)
    extra_guests: list[str] = Field(default_factory=list, max_length=9)  # flere gæster til samme møde
    invitation_code: str = Field("", max_length=20)  # gæsten tjekkede ind med en kode fra en invitation
    firm_id: int | None = None  # husets skærm: det firma, gæsten valgte
    accept_terms: bool = False
    preview: bool = False

    @field_validator("extra_guests")
    @classmethod
    def _extra(cls, v):
        v = [" ".join(x.split()) for x in v]
        if any(len(x) > 120 for x in v):
            raise ValueError("Et navn er for langt")
        return [x for x in v if x]


class DeliveryIn(BaseModel):
    host_id: int | None = None  # None = godsmodtagelsen
    firm_id: int | None = None  # husets skærm: firmaet pakken er til (None = husets godsmodtagelse)
    courier_company: str = Field("", max_length=120)
    courier_name: str = Field("", max_length=120)
    preview: bool = False


class InvitationIn(BaseModel):
    host_id: int | None = None
    guest_name: str = Field(min_length=1, max_length=120)
    guest_phone: str = Field("", max_length=40)
    guest_email: str = Field("", max_length=200)
    guest_company: str = Field("", max_length=120)
    expected_at: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")  # lokal tid, fx 2026-11-14T10:30
    send: bool = True
    recurring: bool = False  # fast gæst: koden kan bruges igen indtil valid_until
    valid_until: str = Field("", pattern=r"^(\d{4}-\d{2}-\d{2})?$")  # lokal dato, fx 2027-03-31

    @field_validator("guest_email")
    @classmethod
    def _mail(cls, v):
        return _email(v) if v.strip() else ""


class CodeIn(BaseModel):
    code: str = Field(max_length=20)


class ReplyIn(BaseModel):
    answer: Literal["now", "5", "10", "reception"]


class LoginIn(BaseModel):
    email: str = Field("", max_length=200)  # tom = platform-admin med ADMIN_PASSWORD
    password: str = Field(max_length=200)


def _email(v: str) -> str:
    v = (v or "").strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", v):
        raise ValueError("Skriv en gyldig e-mailadresse")
    return v


class UserIn(BaseModel):
    email: str = Field(max_length=200)
    name: str = Field("", max_length=120)

    @field_validator("email")
    @classmethod
    def _e(cls, v):
        return _email(v)


class AcceptIn(BaseModel):
    token: str = Field(max_length=500)
    password: str = Field(max_length=200)

    @field_validator("password")
    @classmethod
    def _pw(cls, v):
        if len(v) < 10:
            raise ValueError("Adgangskoden skal være mindst 10 tegn")
        return v


class ForgotIn(BaseModel):
    email: str = Field(max_length=200)


class PartnerIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class PartnerUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    active: bool | None = None
    meeting_privacy: Literal["", "title", "organizer", "busy"] | None = None
    report_email: str | None = Field(None, max_length=500)

    @field_validator("report_email")
    @classmethod
    def _report(cls, v):
        return clean_emails(v)


class RoomIn(BaseModel):
    tenant_id: int | None = None   # lokalet hører til et firma
    partner_id: int | None = None  # ... eller til huset
    name: str = Field(min_length=1, max_length=120)
    location: str = Field("", max_length=120)
    description: str = Field("", max_length=500)
    capacity: int = Field(0, ge=0, le=1000)
    setups: list[str] = Field(default_factory=list, max_length=20)
    equipment: list[str] = Field(default_factory=list, max_length=30)
    privacy: Literal["", "title", "organizer", "busy"] = ""


class RoomUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    location: str | None = Field(None, max_length=120)
    description: str | None = Field(None, max_length=500)
    capacity: int | None = Field(None, ge=0, le=1000)
    setups: list[str] | None = Field(None, max_length=20)
    equipment: list[str] | None = Field(None, max_length=30)
    privacy: Literal["", "title", "organizer", "busy"] | None = None
    active: bool | None = None


class CateringItemIn(BaseModel):
    item_id: int
    qty: int = Field(ge=1, le=1000)


class CateringIn(BaseModel):
    """Forplejning til en booking. Tom liste = ingen forplejning (en eksisterende bestilling annulleres)."""
    kitchen_id: int
    items: list[CateringItemIn] = Field(default_factory=list, max_length=60)
    deliver_at: str = Field("", pattern=r"^(\d{2}:\d{2})?$")  # lokal tid samme dag som mødet, tom = mødets start
    note: str = Field("", max_length=500)
    cost_center: str = Field("", max_length=60)


class BookingIn(BaseModel):
    room_id: int
    tenant_id: int | None = None  # det bookende firma (admin). Via værtens link er det værtens firma.
    title: str = Field("", max_length=200)
    organizer: str = Field("", max_length=120)
    start: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")  # lokal tid
    end: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")
    attendees: int = Field(0, ge=0, le=1000)
    setup: str = Field("", max_length=60)
    equipment: list[str] = Field(default_factory=list, max_length=30)
    note: str = Field("", max_length=500)
    catering: CateringIn | None = None


class QuickBookIn(BaseModel):
    minutes: Literal[15, 30, 60]


class SubscriptionIn(BaseModel):
    partner_id: int | None = None
    sub_yearly_price: int | None = Field(None, ge=0, le=10_000_000)
    self_service: bool | None = None
    self_service_monthly_price: int | None = Field(None, ge=0, le=1_000_000)
    sub_paid_until: date | None = None
    sub_note: str | None = Field(None, max_length=500)


def clean_emails(v: str | None) -> str | None:
    """'a@x.dk; b@y.dk' -> 'a@x.dk, b@y.dk'. Fejl, hvis en adresse ikke ligner en e-mail."""
    if v is None:
        return v
    parts = [x.strip() for x in v.replace(";", ",").split(",") if x.strip()]
    bad = [x for x in parts if "@" not in x or "." not in x.split("@")[-1] or " " in x]
    if bad:
        raise ValueError("Ugyldig e-mailadresse: " + bad[0])
    if len(parts) > 10:
        raise ValueError("Højst 10 modtagere")
    return ", ".join(parts)


# ---------- serializers ----------

def host_admin(h: Host) -> dict:
    return {
        "id": h.id, "name": h.name, "title": h.title, "email": h.email, "phone": h.phone,
        "photo_url": media_url(h.photo_path), "notify_sms": h.notify_sms, "notify_email": h.notify_email,
        "active": h.active, "sort_order": h.sort_order,
    }


def host_public(h: Host, show_photo: bool) -> dict:
    # Never expose e-mail or phone on the public kiosk.
    return {"id": h.id, "name": h.name, "title": h.title,
            "photo_url": media_url(h.photo_path) if show_photo else ""}


TENANT_FIELDS = [
    "id", "name", "kiosk_token", "active", "color", "background_scope", "background_dim", "welcome_text",
    "show_photos", "name_required", "ask_phone", "phone_required", "ask_company", "allow_unknown_host",
    "reception_email", "reception_phone", "print_badge", "badge_size", "idle_seconds", "retention_days",
    "lang_default", "lang_mode", "wifi_name", "wifi_password", "delivery_enabled", "delivery_email", "delivery_phone",
    "delivery_note", "closed_text", "group_checkin", "terms_enabled", "terms_title", "terms_text", "host_reply",
    "escalate_minutes", "teams_webhook", "house_screen", "meeting_privacy", "report_email",
    "sms_sender", "sms_template", "email_subject", "email_template",
]


def opening_hours(t: Tenant) -> list:
    try:
        v = json.loads(t.opening_hours) if t.opening_hours else []
        return v if isinstance(v, list) and len(v) in (0, 7) else []
    except ValueError:
        return []


def tenant_languages(t: Tenant) -> list[str]:
    langs = [x for x in (t.languages or "").split(",") if x in SUPPORTED_LANGS]
    return langs or [SUPPORTED_LANGS[0]]


SUBSCRIPTION_FIELDS = ["sub_yearly_price", "self_service", "self_service_monthly_price", "sub_note"]


def tenant_admin(t: Tenant, with_hosts: bool = True, platform: bool = False, host_count: int | None = None) -> dict:
    d = {f: getattr(t, f) for f in TENANT_FIELDS}
    d["languages"] = tenant_languages(t)
    d["opening_hours"] = opening_hours(t)
    d["partner_id"] = t.partner_id
    d["partner_name"] = t.partner.name if t.partner else ""
    d["self_service"] = modules.tenant_has(t, "self_service")  # så admins kan se, om kunde-login virker
    d["modules"] = modules.of_tenant(t)
    if platform:
        d["subscription"] = {f: getattr(t, f) for f in SUBSCRIPTION_FIELDS}
        d["subscription"]["sub_paid_until"] = t.sub_paid_until.isoformat() if t.sub_paid_until else None
        d["subscription"]["partner_id"] = t.partner_id
    d["logo_url"] = media_url(t.logo_path)
    d["background_url"] = media_url(t.background_path)
    d["kiosk_url"] = f"/k/{t.kiosk_token}"
    d["created_at"] = local_iso(t.created_at)
    d["host_count"] = len(t.hosts) if host_count is None else host_count
    st = presence.status(t.kiosk_token)
    d["screen"] = {"online": st["online"],
                   "seen_at": local_iso(datetime.fromtimestamp(st["seen_at"], timezone.utc).replace(tzinfo=None))
                   if st["seen_at"] else None}
    if with_hosts:
        d["hosts"] = [host_admin(h) for h in t.hosts]
    return d


def tenant_public(t: Tenant, firms: list[Tenant] | None = None) -> dict:
    """Det, skærmen viser. firms: husets skærm viser alle partnerens firmaer (se house.firms_of)."""
    d = {
        "name": t.name, "color": t.color, "logo_url": media_url(t.logo_path),
        "background_url": media_url(t.background_path), "background_scope": t.background_scope,
        "background_dim": t.background_dim, "welcome_text": t.welcome_text or f"Velkommen til {t.name}",
        "show_photos": t.show_photos, "name_required": t.name_required, "ask_phone": t.ask_phone,
        "phone_required": t.phone_required, "ask_company": t.ask_company,
        "allow_unknown_host": t.allow_unknown_host, "print_badge": t.print_badge, "badge_size": t.badge_size,
        "idle_seconds": t.idle_seconds, "retention_days": t.retention_days,
        "languages": tenant_languages(t), "lang_default": t.lang_default, "lang_mode": t.lang_mode,
        # Kun det, skærmen skal vise. Godsmodtagelsens kontakt og Teams-adressen bliver på serveren.
        "wifi_name": t.wifi_name, "wifi_password": t.wifi_password, "delivery_enabled": t.delivery_enabled,
        "delivery_note": t.delivery_note, "opening_hours": opening_hours(t), "closed_text": t.closed_text,
        "group_checkin": t.group_checkin, "terms_enabled": t.terms_enabled, "terms_title": t.terms_title,
        "terms_text": t.terms_text, "host_reply": t.host_reply,
        "hosts": [host_public(h, t.show_photos) for h in t.hosts if h.active],
    }
    d["house"] = bool(t.house_screen and firms)
    if d["house"]:
        d["firms"] = [{"id": f.id, "name": f.name, "logo_url": media_url(f.logo_path), "color": f.color,
                       "allow_unknown_host": f.allow_unknown_host,
                       "hosts": [host_public(h, t.show_photos) for h in f.hosts if h.active]} for f in firms]
    return d


def user_out(u: User) -> dict:
    return {"id": u.id, "email": u.email, "name": u.name, "role": u.role, "active": u.active,
            "partner_id": u.partner_id, "tenant_id": u.tenant_id,
            "pending": not u.password_hash,  # har ikke valgt adgangskode endnu
            "last_login_at": local_iso(u.last_login_at)}


def partner_out(p: Partner, tenant_count: int = 0, user_count: int = 0) -> dict:
    return {"id": p.id, "name": p.name, "active": p.active, "tenant_count": tenant_count,
            "meeting_privacy": p.meeting_privacy, "report_email": p.report_email, "modules": modules.of_partner(p),
            "user_count": user_count, "created_at": local_iso(p.created_at)}



UNITS = ("pr. person", "stk.", "portion", "kande", "flaske", "fad", "kurv")
TAGS = ("Vegetar", "Vegansk", "Glutenfri", "Laktosefri", "Økologisk", "Indeholder nødder")


class KitchenIn(BaseModel):
    tenant_id: int | None = None
    partner_id: int | None = None
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["internal", "external"] = "internal"
    email: str = Field("", max_length=200)
    phone: str = Field("", max_length=40)
    lead_hours: int = Field(3, ge=0, le=168)
    note: str = Field("", max_length=300)


class KitchenUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    kind: Literal["internal", "external"] | None = None
    email: str | None = Field(None, max_length=200)
    phone: str | None = Field(None, max_length=40)
    lead_hours: int | None = Field(None, ge=0, le=168)
    note: str | None = Field(None, max_length=300)
    active: bool | None = None


class MenuItemIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field("", max_length=300)
    category: str = Field("", max_length=40)
    price: float = Field(0, ge=0, le=100000)  # kroner
    unit: Literal[UNITS] = "pr. person"  # type: ignore[valid-type]
    tags: list[Literal[TAGS]] = Field(default_factory=list, max_length=10)  # type: ignore[valid-type]
    active: bool = True


class MenuItemUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    description: str | None = Field(None, max_length=300)
    category: str | None = Field(None, max_length=40)
    price: float | None = Field(None, ge=0, le=100000)
    unit: Literal[UNITS] | None = None  # type: ignore[valid-type]
    tags: list[Literal[TAGS]] | None = Field(None, max_length=10)  # type: ignore[valid-type]
    active: bool | None = None
    sort_order: int | None = Field(None, ge=0, le=10000)


class OrderStatusIn(BaseModel):
    status: Literal["new", "confirmed", "delivered"]
