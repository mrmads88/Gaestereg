"""Sprog på skærmen: hvilke sprog, standardsprog og hvordan gæsten vælger sprog.

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("languages", sa.Unicode(60), nullable=False, server_default=sa.text("'da,en'")))
    op.add_column("tenants", sa.Column("lang_default", sa.Unicode(5), nullable=False, server_default=sa.text("'da'")))
    op.add_column("tenants", sa.Column("lang_mode", sa.Unicode(10), nullable=False,
                                       server_default=sa.text("'toggle'")))


def downgrade() -> None:
    op.drop_column("tenants", "lang_mode")
    op.drop_column("tenants", "lang_default")
    op.drop_column("tenants", "languages")
