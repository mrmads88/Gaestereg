import secrets
from datetime import datetime, timezone

# Unicode/UnicodeText bliver NVARCHAR på SQL Server (æøå og emoji) og VARCHAR/TEXT på SQLite.
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Unicode, UnicodeText
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_token() -> str:
    return secrets.token_urlsafe(9)


DEFAULT_SMS = "Hej {vaert_fornavn}. {gaest} er ankommet og venter i receptionen. Tlf: {telefon}"
DEFAULT_MAIL_SUBJECT = "Din gæst {gaest} er ankommet"
DEFAULT_MAIL_BODY = (
    "Hej {vaert_fornavn}\n\n"
    "{gaest} er ankommet kl. {tid} og venter i receptionen.\n\n"
    "Telefon: {telefon}\n"
    "Firma: {firma}\n\n"
    "Venlig hilsen\n{kunde}"
)


class Tenant(Base):
    """One customer, e.g. a company or a building. Each has its own kiosk link and look."""
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Unicode(120))
    kiosk_token: Mapped[str] = mapped_column(Unicode(40), unique=True, index=True, default=new_token)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    # look
    logo_path: Mapped[str] = mapped_column(Unicode(200), default="")
    color: Mapped[str] = mapped_column(Unicode(7), default="#1f3a5a")
    background_path: Mapped[str] = mapped_column(Unicode(200), default="")
    background_scope: Mapped[str] = mapped_column(Unicode(10), default="wall")  # wall | full
    background_dim: Mapped[int] = mapped_column(Integer, default=55)
    welcome_text: Mapped[str] = mapped_column(Unicode(200), default="")
    show_photos: Mapped[bool] = mapped_column(Boolean, default=True)

    # guest flow
    name_required: Mapped[bool] = mapped_column(Boolean, default=True)
    ask_phone: Mapped[bool] = mapped_column(Boolean, default=True)
    phone_required: Mapped[bool] = mapped_column(Boolean, default=True)
    ask_company: Mapped[bool] = mapped_column(Boolean, default=False)
    allow_unknown_host: Mapped[bool] = mapped_column(Boolean, default=True)
    reception_email: Mapped[str] = mapped_column(Unicode(200), default="")
    reception_phone: Mapped[str] = mapped_column(Unicode(40), default="")
    print_badge: Mapped[bool] = mapped_column(Boolean, default=False)
    badge_size: Mapped[str] = mapped_column(Unicode(10), default="62x100")
    idle_seconds: Mapped[int] = mapped_column(Integer, default=60)
    retention_days: Mapped[int] = mapped_column(Integer, default=30)

    # messages
    sms_sender: Mapped[str] = mapped_column(Unicode(15), default="Reception")
    sms_template: Mapped[str] = mapped_column(UnicodeText, default=DEFAULT_SMS)
    email_subject: Mapped[str] = mapped_column(Unicode(200), default=DEFAULT_MAIL_SUBJECT)
    email_template: Mapped[str] = mapped_column(UnicodeText, default=DEFAULT_MAIL_BODY)

    hosts: Mapped[list["Host"]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan", order_by="Host.sort_order"
    )


class Host(Base):
    """A person guests can choose on the kiosk."""
    __tablename__ = "hosts"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(Unicode(120))
    title: Mapped[str] = mapped_column(Unicode(120), default="")
    email: Mapped[str] = mapped_column(Unicode(200), default="")
    phone: Mapped[str] = mapped_column(Unicode(40), default="")
    photo_path: Mapped[str] = mapped_column(Unicode(200), default="")
    notify_sms: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_email: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    tenant: Mapped[Tenant] = relationship(back_populates="hosts")


class Visit(Base):
    __tablename__ = "visits"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    # Ingen ondelete her og på Notification.visit_id: SQL Server tillader kun én kaskadevej pr. tabel
    # (tenants -> visits). delete_host og purge_old rydder selv op.
    host_id: Mapped[int | None] = mapped_column(ForeignKey("hosts.id"), nullable=True)
    host_name: Mapped[str] = mapped_column(Unicode(120), default="")  # snapshot, survives host deletion
    guest_name: Mapped[str] = mapped_column(Unicode(120), default="")
    guest_phone: Mapped[str] = mapped_column(Unicode(40), default="")
    guest_company: Mapped[str] = mapped_column(Unicode(120), default="")
    checked_in_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    checked_out_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Notification(Base):
    """Every message we sent (or would have sent in test mode)."""
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    visit_id: Mapped[int | None] = mapped_column(ForeignKey("visits.id"), nullable=True)
    channel: Mapped[str] = mapped_column(Unicode(10))  # sms | email
    recipient: Mapped[str] = mapped_column(Unicode(200))
    subject: Mapped[str] = mapped_column(Unicode(200), default="")
    body: Mapped[str] = mapped_column(UnicodeText, default="")
    status: Mapped[str] = mapped_column(Unicode(10), default="venter")  # venter | sendt | test | fejl
    error: Mapped[str] = mapped_column(UnicodeText, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
