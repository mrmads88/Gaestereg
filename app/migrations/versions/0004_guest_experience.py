"""Fase 2, gæsteoplevelse: WiFi, pakker, åbningstider, flere gæster, husregler, værtens svar, påmindelse, Teams.

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("wifi_name", sa.Unicode(64), nullable=False, server_default=sa.text("''")))
    op.add_column("tenants", sa.Column("wifi_password", sa.Unicode(64), nullable=False, server_default=sa.text("''")))
    op.add_column("tenants", sa.Column("delivery_enabled", sa.Boolean(), nullable=False, server_default=sa.text("0")))
    op.add_column("tenants", sa.Column("delivery_email", sa.Unicode(200), nullable=False, server_default=sa.text("''")))
    op.add_column("tenants", sa.Column("delivery_phone", sa.Unicode(40), nullable=False, server_default=sa.text("''")))
    op.add_column("tenants", sa.Column("delivery_note", sa.Unicode(300), nullable=False, server_default=sa.text("''")))
    op.add_column("tenants", sa.Column("opening_hours", sa.Unicode(300), nullable=False, server_default=sa.text("''")))
    op.add_column("tenants", sa.Column("closed_text", sa.Unicode(300), nullable=False, server_default=sa.text("''")))
    op.add_column("tenants", sa.Column("group_checkin", sa.Boolean(), nullable=False, server_default=sa.text("0")))
    op.add_column("tenants", sa.Column("terms_enabled", sa.Boolean(), nullable=False, server_default=sa.text("0")))
    op.add_column("tenants", sa.Column("terms_title", sa.Unicode(120), nullable=False, server_default=sa.text("''")))
    op.add_column("tenants", sa.Column("terms_text", sa.UnicodeText(), nullable=False, server_default=sa.text("''")))
    op.add_column("tenants", sa.Column("host_reply", sa.Boolean(), nullable=False, server_default=sa.text("1")))
    op.add_column("tenants", sa.Column("escalate_minutes", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.add_column("tenants", sa.Column("teams_webhook", sa.Unicode(1000), nullable=False, server_default=sa.text("''")))
    op.add_column("visits", sa.Column("kind", sa.Unicode(10), nullable=False, server_default=sa.text("'guest'")))
    op.add_column("visits", sa.Column("group_ref", sa.Unicode(16), nullable=False, server_default=sa.text("''")))
    op.add_column("visits", sa.Column("terms_accepted", sa.Boolean(), nullable=False, server_default=sa.text("0")))
    op.add_column("visits", sa.Column("host_reply", sa.Unicode(20), nullable=False, server_default=sa.text("''")))
    op.add_column("visits", sa.Column("host_reply_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("visits", "host_reply_at")
    op.drop_column("visits", "host_reply")
    op.drop_column("visits", "terms_accepted")
    op.drop_column("visits", "group_ref")
    op.drop_column("visits", "kind")
    op.drop_column("tenants", "teams_webhook")
    op.drop_column("tenants", "escalate_minutes")
    op.drop_column("tenants", "host_reply")
    op.drop_column("tenants", "terms_text")
    op.drop_column("tenants", "terms_title")
    op.drop_column("tenants", "terms_enabled")
    op.drop_column("tenants", "group_checkin")
    op.drop_column("tenants", "closed_text")
    op.drop_column("tenants", "opening_hours")
    op.drop_column("tenants", "delivery_note")
    op.drop_column("tenants", "delivery_phone")
    op.drop_column("tenants", "delivery_email")
    op.drop_column("tenants", "delivery_enabled")
    op.drop_column("tenants", "wifi_password")
    op.drop_column("tenants", "wifi_name")
