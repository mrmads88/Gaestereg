"""Fase 5a: mødelokaler, bookinger og diskretion om mødetitler.

Revision ID: 0007
Revises: 0006
"""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("partners", sa.Column("meeting_privacy", sa.Unicode(10), nullable=False, server_default=sa.text("''")))
    op.add_column("tenants", sa.Column("meeting_privacy", sa.Unicode(10), nullable=False, server_default=sa.text("''")))
    op.create_table(
        "rooms",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True),
        sa.Column("partner_id", sa.Integer(), sa.ForeignKey("partners.id"), nullable=True),
        sa.Column("name", sa.Unicode(120), nullable=False),
        sa.Column("location", sa.Unicode(120), nullable=False),
        sa.Column("description", sa.Unicode(500), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("photo_path", sa.Unicode(200), nullable=False),
        sa.Column("setups", sa.UnicodeText(), nullable=False),
        sa.Column("equipment", sa.UnicodeText(), nullable=False),
        sa.Column("privacy", sa.Unicode(10), nullable=False),
        sa.Column("screen_token", sa.Unicode(40), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_rooms_tenant_id", "rooms", ["tenant_id"])
    op.create_index("ix_rooms_partner_id", "rooms", ["partner_id"])
    op.create_index("ix_rooms_screen_token", "rooms", ["screen_token"], unique=True)
    op.create_table(
        "bookings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("room_id", sa.Integer(), sa.ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=True),
        sa.Column("host_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.Unicode(200), nullable=False),
        sa.Column("organizer", sa.Unicode(120), nullable=False),
        sa.Column("start_at", sa.DateTime(), nullable=False),
        sa.Column("end_at", sa.DateTime(), nullable=False),
        sa.Column("attendees", sa.Integer(), nullable=False),
        sa.Column("setup", sa.Unicode(60), nullable=False),
        sa.Column("equipment", sa.UnicodeText(), nullable=False),
        sa.Column("note", sa.Unicode(500), nullable=False),
        sa.Column("status", sa.Unicode(12), nullable=False),
        sa.Column("source", sa.Unicode(10), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_bookings_room_id", "bookings", ["room_id"])
    op.create_index("ix_bookings_tenant_id", "bookings", ["tenant_id"])
    op.create_index("ix_bookings_start_at", "bookings", ["start_at"])


def downgrade() -> None:
    op.drop_table("bookings")
    op.drop_table("rooms")
    op.drop_column("tenants", "meeting_privacy")
    op.drop_column("partners", "meeting_privacy")
