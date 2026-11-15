"""Demo-kunder til salgsmøder og "Kom i gang"-tjeklisten.

Revision ID: 0018
Revises: 0017
"""
import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.text("0")))
    op.add_column("tenants", sa.Column("checklist_hidden", sa.Boolean(), nullable=False, server_default=sa.text("0")))
    op.add_column("partners", sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.text("0")))


def downgrade() -> None:
    op.drop_column("partners", "is_demo")
    op.drop_column("tenants", "checklist_hidden")
    op.drop_column("tenants", "is_demo")
