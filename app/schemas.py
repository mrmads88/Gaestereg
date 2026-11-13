import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .media import media_url
from .models import Host, Partner, Tenant, User
from .timeutil import local_iso

HEX = r"^#[0-9a-fA-F]{6}$"


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
    preview: bool = False


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


class SubscriptionIn(BaseModel):
    partner_id: int | None = None
    sub_yearly_price: int | None = Field(None, ge=0, le=10_000_000)
    self_service: bool | None = None
    self_service_monthly_price: int | None = Field(None, ge=0, le=1_000_000)
    sub_paid_until: date | None = None
    sub_note: str | None = Field(None, max_length=500)


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
    "sms_sender", "sms_template", "email_subject", "email_template",
]


SUBSCRIPTION_FIELDS = ["sub_yearly_price", "self_service", "self_service_monthly_price", "sub_note"]


def tenant_admin(t: Tenant, with_hosts: bool = True, platform: bool = False) -> dict:
    d = {f: getattr(t, f) for f in TENANT_FIELDS}
    d["partner_id"] = t.partner_id
    d["partner_name"] = t.partner.name if t.partner else ""
    d["self_service"] = t.self_service  # så kunde- og partner-admins kan se, om kunde-login virker
    if platform:
        d["subscription"] = {f: getattr(t, f) for f in SUBSCRIPTION_FIELDS}
        d["subscription"]["sub_paid_until"] = t.sub_paid_until.isoformat() if t.sub_paid_until else None
        d["subscription"]["partner_id"] = t.partner_id
    d["logo_url"] = media_url(t.logo_path)
    d["background_url"] = media_url(t.background_path)
    d["kiosk_url"] = f"/k/{t.kiosk_token}"
    d["created_at"] = local_iso(t.created_at)
    d["host_count"] = len(t.hosts)
    if with_hosts:
        d["hosts"] = [host_admin(h) for h in t.hosts]
    return d


def tenant_public(t: Tenant) -> dict:
    return {
        "name": t.name, "color": t.color, "logo_url": media_url(t.logo_path),
        "background_url": media_url(t.background_path), "background_scope": t.background_scope,
        "background_dim": t.background_dim, "welcome_text": t.welcome_text or f"Velkommen til {t.name}",
        "show_photos": t.show_photos, "name_required": t.name_required, "ask_phone": t.ask_phone,
        "phone_required": t.phone_required, "ask_company": t.ask_company,
        "allow_unknown_host": t.allow_unknown_host, "print_badge": t.print_badge, "badge_size": t.badge_size,
        "idle_seconds": t.idle_seconds, "retention_days": t.retention_days,
        "hosts": [host_public(h, t.show_photos) for h in t.hosts if h.active],
    }


def user_out(u: User) -> dict:
    return {"id": u.id, "email": u.email, "name": u.name, "role": u.role, "active": u.active,
            "partner_id": u.partner_id, "tenant_id": u.tenant_id,
            "pending": not u.password_hash,  # har ikke valgt adgangskode endnu
            "last_login_at": local_iso(u.last_login_at)}


def partner_out(p: Partner, tenant_count: int = 0, user_count: int = 0) -> dict:
    return {"id": p.id, "name": p.name, "active": p.active, "tenant_count": tenant_count,
            "user_count": user_count, "created_at": local_iso(p.created_at)}

