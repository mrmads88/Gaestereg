"""Baseline: skemaet som det så ud, før Alembic blev indført.

Databaser, der blev oprettet med create_all (dev og prod i november 2026), markeres som værende
på denne revision uden at køre den (se app.db.init_db). Nye databaser oprettes herfra.

Revision ID: 0001
Revises:
"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.Unicode(120), nullable=False),
        sa.Column("kiosk_token", sa.Unicode(40), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("logo_path", sa.Unicode(200), nullable=False),
        sa.Column("color", sa.Unicode(7), nullable=False),
        sa.Column("background_path", sa.Unicode(200), nullable=False),
        sa.Column("background_scope", sa.Unicode(10), nullable=False),
        sa.Column("background_dim", sa.Integer(), nullable=False),
        sa.Column("welcome_text", sa.Unicode(200), nullable=False),
        sa.Column("show_photos", sa.Boolean(), nullable=False),
        sa.Column("name_required", sa.Boolean(), nullable=False),
        sa.Column("ask_phone", sa.Boolean(), nullable=False),
        sa.Column("phone_required", sa.Boolean(), nullable=False),
        sa.Column("ask_company", sa.Boolean(), nullable=False),
        sa.Column("allow_unknown_host", sa.Boolean(), nullable=False),
        sa.Column("reception_email", sa.Unicode(200), nullable=False),
        sa.Column("reception_phone", sa.Unicode(40), nullable=False),
        sa.Column("print_badge", sa.Boolean(), nullable=False),
        sa.Column("badge_size", sa.Unicode(10), nullable=False),
        sa.Column("idle_seconds", sa.Integer(), nullable=False),
        sa.Column("retention_days", sa.Integer(), nullable=False),
        sa.Column("sms_sender", sa.Unicode(15), nullable=False),
        sa.Column("sms_template", sa.UnicodeText(), nullable=False),
        sa.Column("email_subject", sa.Unicode(200), nullable=False),
        sa.Column("email_template", sa.UnicodeText(), nullable=False),
    )
    op.create_index("ix_tenants_kiosk_token", "tenants", ["kiosk_token"], unique=True)

    op.create_table(
        "hosts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Unicode(120), nullable=False),
        sa.Column("title", sa.Unicode(120), nullable=False),
        sa.Column("email", sa.Unicode(200), nullable=False),
        sa.Column("phone", sa.Unicode(40), nullable=False),
        sa.Column("photo_path", sa.Unicode(200), nullable=False),
        sa.Column("notify_sms", sa.Boolean(), nullable=False),
        sa.Column("notify_email", sa.Boolean(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
    )
    op.create_index("ix_hosts_tenant_id", "hosts", ["tenant_id"])

    op.create_table(
        "visits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("host_id", sa.Integer(), sa.ForeignKey("hosts.id"), nullable=True),
        sa.Column("host_name", sa.Unicode(120), nullable=False),
        sa.Column("guest_name", sa.Unicode(120), nullable=False),
        sa.Column("guest_phone", sa.Unicode(40), nullable=False),
        sa.Column("guest_company", sa.Unicode(120), nullable=False),
        sa.Column("checked_in_at", sa.DateTime(), nullable=False),
        sa.Column("checked_out_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_visits_tenant_id", "visits", ["tenant_id"])
    op.create_index("ix_visits_checked_in_at", "visits", ["checked_in_at"])

    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("visit_id", sa.Integer(), sa.ForeignKey("visits.id"), nullable=True),
        sa.Column("channel", sa.Unicode(10), nullable=False),
        sa.Column("recipient", sa.Unicode(200), nullable=False),
        sa.Column("subject", sa.Unicode(200), nullable=False),
        sa.Column("body", sa.UnicodeText(), nullable=False),
        sa.Column("status", sa.Unicode(10), nullable=False),
        sa.Column("error", sa.UnicodeText(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_notifications_tenant_id", "notifications", ["tenant_id"])
    op.create_index("ix_notifications_created_at", "notifications", ["created_at"])


def downgrade() -> None:
    for t in ("notifications", "visits", "hosts", "tenants"):
        op.drop_table(t)
