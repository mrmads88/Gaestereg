"""Fase 8: infoskærme.

Revision ID: 0010
Revises: 0009
"""
import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "signage_screens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True),
        sa.Column("partner_id", sa.Integer(), sa.ForeignKey("partners.id"), nullable=True),
        sa.Column("name", sa.Unicode(120), nullable=False),
        sa.Column("token", sa.Unicode(40), nullable=False),
        sa.Column("layout", sa.Unicode(10), nullable=False),
        sa.Column("theme", sa.Unicode(10), nullable=False),
        sa.Column("content", sa.UnicodeText(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_signage_screens_tenant_id", "signage_screens", ["tenant_id"])
    op.create_index("ix_signage_screens_partner_id", "signage_screens", ["partner_id"])
    op.create_index("ix_signage_screens_token", "signage_screens", ["token"], unique=True)
    # Prislisten fra 0009 sagde "kommer snart". Ret kun teksten, hvis leverandøren ikke selv har ændret den.
    op.execute("UPDATE products SET description = 'Infoskærme med velkomst, nyheder, billeder, dagens gæster, mødelokaler "
               "og menu, som I selv sætter sammen.' WHERE code = 'signage' AND description LIKE '%kommer snart%'")


def downgrade() -> None:
    op.drop_table("signage_screens")
