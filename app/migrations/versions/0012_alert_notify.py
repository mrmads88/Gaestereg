"""Nødbesked også som SMS, mail og Teams til personerne (slukket som standard).

Revision ID: 0012
Revises: 0011
"""
import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("tenants", "partners"):
        op.add_column(table, sa.Column("alert_notify", sa.Boolean(), nullable=False, server_default=sa.text("0")))
    op.add_column("emergency_alerts", sa.Column("notify", sa.Boolean(), nullable=False, server_default=sa.text("0")))
    op.add_column("emergency_alerts", sa.Column("notified_count", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.add_column("emergency_alerts", sa.Column("cleared_count", sa.Integer(), nullable=False, server_default=sa.text("0")))


def downgrade() -> None:
    for col in ("cleared_count", "notified_count", "notify"):
        op.drop_column("emergency_alerts", col)
    for table in ("tenants", "partners"):
        op.drop_column(table, "alert_notify")
