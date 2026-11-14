"""Databehandleraftale: accept pr. firma og hus.

Revision ID: 0013
Revises: 0012
"""
import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("tenants", "partners"):
        op.add_column(table, sa.Column("dpa_version", sa.Unicode(40), nullable=False, server_default=sa.text("''")))
        op.add_column(table, sa.Column("dpa_accepted_at", sa.DateTime(), nullable=True))
        op.add_column(table, sa.Column("dpa_accepted_by", sa.Unicode(200), nullable=False, server_default=sa.text("''")))


def downgrade() -> None:
    for table in ("tenants", "partners"):
        for col in ("dpa_accepted_by", "dpa_accepted_at", "dpa_version"):
            op.drop_column(table, col)
