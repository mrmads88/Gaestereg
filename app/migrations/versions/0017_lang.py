"""Sprog i admin pr. bruger (da | en).

Revision ID: 0017
Revises: 0016
"""
import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("users", "platform_account"):
        op.add_column(table, sa.Column("lang", sa.Unicode(5), nullable=False, server_default=sa.text("'da'")))


def downgrade() -> None:
    for table in ("users", "platform_account"):
        op.drop_column(table, "lang")
