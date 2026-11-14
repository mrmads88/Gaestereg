"""Nødbesked på alle skærme.

Revision ID: 0011
Revises: 0010
"""
import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "emergency_alerts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True),
        sa.Column("partner_id", sa.Integer(), sa.ForeignKey("partners.id"), nullable=True),
        sa.Column("kind", sa.Unicode(12), nullable=False),
        sa.Column("title", sa.Unicode(120), nullable=False),
        sa.Column("message", sa.Unicode(600), nullable=False),
        sa.Column("created_by", sa.Unicode(200), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("ends_at", sa.DateTime(), nullable=True),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("ended_by", sa.Unicode(200), nullable=False),
    )
    op.create_index("ix_emergency_alerts_tenant_id", "emergency_alerts", ["tenant_id"])
    op.create_index("ix_emergency_alerts_partner_id", "emergency_alerts", ["partner_id"])


def downgrade() -> None:
    op.drop_table("emergency_alerts")
