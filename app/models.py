import secrets
from datetime import date, datetime, timezone

# Unicode/UnicodeText bliver NVARCHAR på SQL Server (æøå og emoji) og VARCHAR/TEXT på SQLite.
from sqlalchemy import (Boolean, Date, DateTime, ForeignKey, Integer, Unicode, UnicodeText, UniqueConstraint,
                        text)
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


class Partner(Base):
    """Fx et kontorhotel eller et bureau, der opretter og vedligeholder flere firmaer (tenants)."""
    __tablename__ = "partners"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Unicode(120))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    evac_version: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))  # evakueringslink
    # Hvad lokaleskærme viser om møder: title | organizer | busy. Tom = standard (busy). Se rooms.privacy_for.
    meeting_privacy: Mapped[str] = mapped_column(Unicode(10), default="", server_default=text("''"))
    report_email: Mapped[str] = mapped_column(Unicode(500), default="", server_default=text("''"))
    alert_notify: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))  # hele huset
    # Databehandleraftalen: hvilken version kundens admin har accepteret, hvornår og af hvem. Se legal.py.
    dpa_version: Mapped[str] = mapped_column(Unicode(40), default="", server_default=text("''"))
    dpa_accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    dpa_accepted_by: Mapped[str] = mapped_column(Unicode(200), default="", server_default=text("''"))

    tenants: Mapped[list["Tenant"]] = relationship(back_populates="partner")


class Tenant(Base):
    """One customer, e.g. a company or a building. Each has its own kiosk link and look."""
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Unicode(120))
    # Ingen ondelete: en partner slettes ikke, mens den har firmaer.
    partner_id: Mapped[int | None] = mapped_column(ForeignKey("partners.id"), nullable=True, index=True)
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
    # Sprog på skærmen. languages: kommasepareret, fx "da,en" (se SUPPORTED_LANGS i schemas.py og static/langs.js).
    # lang_mode: toggle = lille sprogknap, first = gæsten vælger sprog først, off = kun standardsproget.
    languages: Mapped[str] = mapped_column(Unicode(60), default="da,en", server_default=text("'da,en'"))
    lang_default: Mapped[str] = mapped_column(Unicode(5), default="da", server_default=text("'da'"))
    lang_mode: Mapped[str] = mapped_column(Unicode(10), default="toggle", server_default=text("'toggle'"))
    retention_days: Mapped[int] = mapped_column(Integer, default=30)

    # messages
    sms_sender: Mapped[str] = mapped_column(Unicode(15), default="Reception")
    sms_template: Mapped[str] = mapped_column(UnicodeText, default=DEFAULT_SMS)
    email_subject: Mapped[str] = mapped_column(Unicode(200), default=DEFAULT_MAIL_SUBJECT)
    email_template: Mapped[str] = mapped_column(UnicodeText, default=DEFAULT_MAIL_BODY)

    # kontorhotel (fase 4): denne skærm viser alle partnerens firmaer, og gæsten vælger firma først
    house_screen: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    meeting_privacy: Mapped[str] = mapped_column(Unicode(10), default="", server_default=text("''"))  # se Partner
    evac_version: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))  # evakueringslink

    # gæsteoplevelse (fase 2)
    wifi_name: Mapped[str] = mapped_column(Unicode(64), default="", server_default=text("''"))
    wifi_password: Mapped[str] = mapped_column(Unicode(64), default="", server_default=text("''"))
    delivery_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    delivery_email: Mapped[str] = mapped_column(Unicode(200), default="", server_default=text("''"))
    delivery_phone: Mapped[str] = mapped_column(Unicode(40), default="", server_default=text("''"))
    delivery_note: Mapped[str] = mapped_column(Unicode(300), default="", server_default=text("''"))
    # JSON: 7 elementer (mandag først), hvert enten null (lukket) eller ["08:00", "16:00"]. Tom = altid åben.
    opening_hours: Mapped[str] = mapped_column(Unicode(300), default="", server_default=text("''"))
    closed_text: Mapped[str] = mapped_column(Unicode(300), default="", server_default=text("''"))
    group_checkin: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    terms_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    terms_title: Mapped[str] = mapped_column(Unicode(120), default="", server_default=text("''"))
    terms_text: Mapped[str] = mapped_column(UnicodeText, default="", server_default=text("''"))
    host_reply: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("1"))
    escalate_minutes: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    teams_webhook: Mapped[str] = mapped_column(Unicode(1000), default="", server_default=text("''"))

    # subscription (kun platform-admin kan se og rette)
    sub_yearly_price: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))  # kr/år
    self_service: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    self_service_monthly_price: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    sub_paid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    sub_note: Mapped[str] = mapped_column(Unicode(500), default="", server_default=text("''"))
    # Månedsrapport på mail (firmaets egne admins bestemmer). Flere adresser adskilles med komma.
    report_email: Mapped[str] = mapped_column(Unicode(500), default="", server_default=text("''"))
    # Nødbesked sendes også som SMS/mail/Teams til firmaets personer. Slukket som standard (koster SMS).
    alert_notify: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    # Databehandleraftalen: hvilken version kundens admin har accepteret, hvornår og af hvem. Se legal.py.
    dpa_version: Mapped[str] = mapped_column(Unicode(40), default="", server_default=text("''"))
    dpa_accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    dpa_accepted_by: Mapped[str] = mapped_column(Unicode(200), default="", server_default=text("''"))

    hosts: Mapped[list["Host"]] = relationship(
        back_populates="tenant", cascade="all, delete-orphan", order_by="Host.sort_order"
    )
    partner: Mapped[Partner | None] = relationship(back_populates="tenants")


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
    # Tælles op, når værtens personlige invitationslink laves om, så det gamle holder op med at virke.
    link_version: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))

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
    kind: Mapped[str] = mapped_column(Unicode(10), default="guest", server_default=text("'guest'"))  # guest | delivery
    group_ref: Mapped[str] = mapped_column(Unicode(16), default="", server_default=text("''"))  # gæster der kom sammen
    terms_accepted: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    host_reply: Mapped[str] = mapped_column(Unicode(20), default="", server_default=text("''"))  # now | 5 | 10 | reception
    host_reply_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


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


class User(Base):
    """En admin-bruger, der logger ind med e-mail og adgangskode.

    role = "partner": administrerer alle firmaer under partner_id og kan oprette nye.
    role = "tenant":  administrerer ét firma (tenant_id). Kræver Tenant.self_service.
    Platform-admin (dig) logger ind med ADMIN_PASSWORD og er ikke en række her.
    """
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(Unicode(200), unique=True, index=True)
    name: Mapped[str] = mapped_column(Unicode(120), default="")
    role: Mapped[str] = mapped_column(Unicode(10))  # partner | tenant
    partner_id: Mapped[int | None] = mapped_column(ForeignKey("partners.id"), nullable=True, index=True)
    tenant_id: Mapped[int | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True,
                                                  index=True)
    password_hash: Mapped[str] = mapped_column(Unicode(300), default="")  # tom indtil invitationen er brugt
    # Tælles op ved ny adgangskode eller nyt invitationslink. Gør gamle links og logins ugyldige.
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Invitation(Base):
    """En forventet gæst. Gæsten får en kode og en QR-kode og tjekker ind med den på skærmen."""
    __tablename__ = "invitations"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    host_id: Mapped[int | None] = mapped_column(ForeignKey("hosts.id"), nullable=True)  # nulstilles af delete_host
    host_name: Mapped[str] = mapped_column(Unicode(120), default="")
    guest_name: Mapped[str] = mapped_column(Unicode(120), default="")
    guest_phone: Mapped[str] = mapped_column(Unicode(40), default="")
    guest_email: Mapped[str] = mapped_column(Unicode(200), default="")
    guest_company: Mapped[str] = mapped_column(Unicode(120), default="")
    expected_at: Mapped[datetime] = mapped_column(DateTime, index=True)  # UTC
    code: Mapped[str] = mapped_column(Unicode(6), index=True)
    status: Mapped[str] = mapped_column(Unicode(12), default="pending")  # pending | used | cancelled
    # Fast gæst (håndværker, rengøring): koden kan bruges igen og igen indtil valid_until.
    recurring: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    visit_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # ingen FK: undgår ekstra kaskadeveje
    created_by: Mapped[str] = mapped_column(Unicode(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class VisitStat(Base):
    """Antal besøg pr. firma pr. måned. Uden personoplysninger, så tallene kan gemmes efter besøgene er slettet."""
    __tablename__ = "visit_stats"
    __table_args__ = (UniqueConstraint("tenant_id", "month", "kind", name="uq_visit_stats"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    month: Mapped[str] = mapped_column(Unicode(7))  # "2026-11", lokal tid
    kind: Mapped[str] = mapped_column(Unicode(10))  # guest | delivery
    count: Mapped[int] = mapped_column(Integer, default=0)


class Room(Base):
    """Et mødelokale. Hører enten til et firma (tenant_id) eller til huset (partner_id), så alle husets firmaer
    kan booke det. Lokaleskærmen ved døren identificeres af screen_token."""
    __tablename__ = "rooms"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    partner_id: Mapped[int | None] = mapped_column(ForeignKey("partners.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(Unicode(120))
    location: Mapped[str] = mapped_column(Unicode(120), default="")
    description: Mapped[str] = mapped_column(Unicode(500), default="")
    capacity: Mapped[int] = mapped_column(Integer, default=0)
    photo_path: Mapped[str] = mapped_column(Unicode(200), default="")
    setups: Mapped[str] = mapped_column(UnicodeText, default="[]")      # JSON-liste, fx ["U-bord", "Biograf"]
    equipment: Mapped[str] = mapped_column(UnicodeText, default="[]")   # JSON-liste, fx ["Skærm", "Whiteboard"]
    privacy: Mapped[str] = mapped_column(Unicode(10), default="")       # lokaleskærmens egen indstilling, tom = arv
    screen_token: Mapped[str] = mapped_column(Unicode(40), unique=True, index=True, default=new_token)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Booking(Base):
    """En booking af et lokale. tenant_id er det bookende firma (ingen FK: lokalet kan høre til huset, og SQL Server
    tillader kun én kaskadevej). delete_tenant sletter firmaets bookinger i koden."""
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("rooms.id", ondelete="CASCADE"), index=True)
    tenant_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    host_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(Unicode(200), default="")
    organizer: Mapped[str] = mapped_column(Unicode(120), default="")
    start_at: Mapped[datetime] = mapped_column(DateTime, index=True)  # UTC
    end_at: Mapped[datetime] = mapped_column(DateTime)
    attendees: Mapped[int] = mapped_column(Integer, default=0)
    setup: Mapped[str] = mapped_column(Unicode(60), default="")
    equipment: Mapped[str] = mapped_column(UnicodeText, default="[]")
    note: Mapped[str] = mapped_column(Unicode(500), default="")
    status: Mapped[str] = mapped_column(Unicode(12), default="confirmed")  # confirmed | cancelled
    source: Mapped[str] = mapped_column(Unicode(10), default="admin")      # admin | link | screen
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)



class Kitchen(Base):
    """Et køkken eller en leverandør af forplejning (fase 5b). Hører til et firma eller til huset ligesom lokaler.
    kind: internal (husets/firmaets eget køkken) eller external (fx en cateringvirksomhed).
    Køkkenets egen ordreside (/kitchen/<order_token>) virker uden login."""
    __tablename__ = "kitchens"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    partner_id: Mapped[int | None] = mapped_column(ForeignKey("partners.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(Unicode(120))
    kind: Mapped[str] = mapped_column(Unicode(10), default="internal")
    email: Mapped[str] = mapped_column(Unicode(200), default="")
    phone: Mapped[str] = mapped_column(Unicode(40), default="")
    lead_hours: Mapped[int] = mapped_column(Integer, default=3)  # bestil senest så mange timer før levering
    note: Mapped[str] = mapped_column(Unicode(300), default="")  # vises for den, der bestiller
    order_token: Mapped[str] = mapped_column(Unicode(40), unique=True, index=True, default=new_token)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class MenuItem(Base):
    """En vare på køkkenets menu. Pris i øre."""
    __tablename__ = "menu_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    kitchen_id: Mapped[int] = mapped_column(ForeignKey("kitchens.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(Unicode(120))
    description: Mapped[str] = mapped_column(Unicode(300), default="")
    category: Mapped[str] = mapped_column(Unicode(40), default="")
    price: Mapped[int] = mapped_column(Integer, default=0)
    unit: Mapped[str] = mapped_column(Unicode(20), default="pr. person")
    photo_path: Mapped[str] = mapped_column(Unicode(200), default="")
    tags: Mapped[str] = mapped_column(UnicodeText, default="[]")  # JSON-liste, fx ["Vegetar", "Glutenfri"]
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class CateringOrder(Base):
    """Forplejning til en booking (højst én pr. booking). kitchen_id og tenant_id har ingen FK: SQL Server tillader kun
    én kaskadevej (tenants -> rooms -> bookings -> catering_orders). Oprydning sker i koden."""
    __tablename__ = "catering_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id", ondelete="CASCADE"), unique=True, index=True)
    kitchen_id: Mapped[int] = mapped_column(Integer, index=True)
    tenant_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    deliver_at: Mapped[datetime] = mapped_column(DateTime, index=True)  # UTC
    status: Mapped[str] = mapped_column(Unicode(12), default="new")  # new | confirmed | delivered | cancelled
    note: Mapped[str] = mapped_column(Unicode(500), default="")
    cost_center: Mapped[str] = mapped_column(Unicode(60), default="")
    total: Mapped[int] = mapped_column(Integer, default=0)  # øre
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class CateringLine(Base):
    """En linje på en bestilling. Navn og pris kopieres, så bestillingen ikke ændrer sig, hvis menuen gør."""
    __tablename__ = "catering_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("catering_orders.id", ondelete="CASCADE"), index=True)
    menu_item_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    name: Mapped[str] = mapped_column(Unicode(120))
    unit: Mapped[str] = mapped_column(Unicode(20), default="")
    unit_price: Mapped[int] = mapped_column(Integer, default=0)
    qty: Mapped[int] = mapped_column(Integer, default=1)


class ReportRun(Base):
    """En sendt (eller forsøgt) månedsrapport. Den unikke nøgle sikrer, at hver rapport kun sendes én gang,
    også hvis appen genstarter. scope: tenant | partner."""
    __tablename__ = "report_runs"
    __table_args__ = (UniqueConstraint("scope", "scope_id", "month", name="uq_report_run"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    scope: Mapped[str] = mapped_column(Unicode(10))
    scope_id: Mapped[int] = mapped_column(Integer)
    month: Mapped[str] = mapped_column(Unicode(7))  # YYYY-MM
    recipients: Mapped[str] = mapped_column(Unicode(500), default="")
    status: Mapped[str] = mapped_column(Unicode(10), default="venter")  # venter | sendt | test | fejl
    error: Mapped[str] = mapped_column(UnicodeText, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ---------- abonnement og fakturering ----------

class Product(Base):
    """Prislisten: pakker, tilkøb, forbrug og engangsposter. Priser i øre ekskl. moms.
    kind: package (månedspris, højst én pr. kunde) | addon (månedspris) | usage (pr. stk., fx SMS) | once (engangs).
    audience: firm | house | all. modules: JSON-liste med det, produktet låser op (se modules.py)."""
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(Unicode(40), unique=True, index=True)
    name: Mapped[str] = mapped_column(Unicode(120))
    kind: Mapped[str] = mapped_column(Unicode(10))
    audience: Mapped[str] = mapped_column(Unicode(10), default="all")
    price: Mapped[int] = mapped_column(Integer, default=0)
    unit: Mapped[str] = mapped_column(Unicode(20), default="md.")
    modules: Mapped[str] = mapped_column(UnicodeText, default="[]")
    included_sms: Mapped[int] = mapped_column(Integer, default=0)  # pr. måned, for pakker
    description: Mapped[str] = mapped_column(Unicode(500), default="")
    features: Mapped[str] = mapped_column(UnicodeText, default="[]")  # punkter til pakkekortet
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class BillingAccount(Base):
    """Kunden, der betaler: et firma (tenant_id) eller et hus (partner_id). interval: month | quarter | year.
    Fakturaer udstedes forud for perioden. Forbrug (SMS) afregnes bagud."""
    __tablename__ = "billing_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, unique=True)
    partner_id: Mapped[int | None] = mapped_column(ForeignKey("partners.id"), nullable=True, unique=True)
    interval: Mapped[str] = mapped_column(Unicode(10), default="month")
    discount_pct: Mapped[int] = mapped_column(Integer, default=0)  # fast rabat på alt løbende
    cvr: Mapped[str] = mapped_column(Unicode(20), default="")
    invoice_email: Mapped[str] = mapped_column(Unicode(200), default="")
    reference: Mapped[str] = mapped_column(Unicode(120), default="")  # att., EAN eller ordrenr.
    note: Mapped[str] = mapped_column(Unicode(500), default="")
    usage_billed_through: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AccountProduct(Base):
    """Et produkt, kunden er tilmeldt. billed_through: faktureret til (eksklusiv). Slutdato = opsagt fra og med."""
    __tablename__ = "account_products"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("billing_accounts.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    qty: Mapped[int] = mapped_column(Integer, default=1)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    billed_through: Mapped[date | None] = mapped_column(Date, nullable=True)
    price_override: Mapped[int | None] = mapped_column(Integer, nullable=True)  # øre pr. md., tom = prislisten
    discount_pct: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str] = mapped_column(Unicode(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Adjustment(Base):
    """Engangspost på næste faktura: et engangsprodukt (fx opsætning) eller en rabat (negativt beløb).
    invoice_id sættes, når fakturaen godkendes (ingen FK: én kaskadevej)."""
    __tablename__ = "adjustments"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("billing_accounts.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str] = mapped_column(Unicode(200))
    qty: Mapped[int] = mapped_column(Integer, default=1)
    amount: Mapped[int] = mapped_column(Integer)  # øre pr. stk., negativ = rabat
    invoice_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Invoice(Base):
    """Fakturagrundlag for en periode [period_start, period_end). draft kan laves om. final er låst og har nummer."""
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("billing_accounts.id", ondelete="CASCADE"), index=True)
    number: Mapped[int | None] = mapped_column(Integer, nullable=True)  # sættes ved godkendelse (ikke unik pga. NULL)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    usage_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(Unicode(10), default="draft")  # draft | final | paid
    subtotal: Mapped[int] = mapped_column(Integer, default=0)
    vat: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(Unicode(12))  # product | credit | usage | once | discount
    description: Mapped[str] = mapped_column(Unicode(300))
    qty: Mapped[int] = mapped_column(Integer, default=1)
    unit_price: Mapped[int] = mapped_column(Integer, default=0)
    amount: Mapped[int] = mapped_column(Integer, default=0)
    ref_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # account_product eller adjustment
    ref_end: Mapped[date | None] = mapped_column(Date, nullable=True)  # nyt billed_through ved godkendelse
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class SignageScreen(Base):
    """En infoskærm (fase 8). Hører til et firma eller et hus ligesom lokaler. Skærmen findes på /s/<token>.
    content er JSON: {"slides": [...], "side": [...], "ticker": [...]} (valideres i signage.py)."""
    __tablename__ = "signage_screens"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    partner_id: Mapped[int | None] = mapped_column(ForeignKey("partners.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(Unicode(120))
    token: Mapped[str] = mapped_column(Unicode(40), unique=True, index=True, default=new_token)
    layout: Mapped[str] = mapped_column(Unicode(10), default="sidebar")  # sidebar | full
    theme: Mapped[str] = mapped_column(Unicode(10), default="brand")  # brand | light | dark
    content: Mapped[str] = mapped_column(UnicodeText, default="{}")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class EmergencyAlert(Base):
    """En nødbesked på alle skærme for et firma eller et hus. kind: evacuation | warning | info.
    Aktiv, når ended_at er tom og ends_at (automatisk slut) ikke er passeret. Se alerts.py."""
    __tablename__ = "emergency_alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[int | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    partner_id: Mapped[int | None] = mapped_column(ForeignKey("partners.id"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(Unicode(12), default="evacuation")
    title: Mapped[str] = mapped_column(Unicode(120))
    message: Mapped[str] = mapped_column(Unicode(600), default="")
    created_by: Mapped[str] = mapped_column(Unicode(200), default="")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_by: Mapped[str] = mapped_column(Unicode(200), default="")
    notify: Mapped[bool] = mapped_column(Boolean, default=False)  # send også til personerne
    notified_count: Mapped[int] = mapped_column(Integer, default=0)  # beskeder sendt ved start
    cleared_count: Mapped[int] = mapped_column(Integer, default=0)  # "afblæst"-beskeder ved slut
