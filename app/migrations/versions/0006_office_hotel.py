"""Fase 4, kontorhotel: husets skærm, evakueringslinks, faste gæster og besøgsstatistik.

Revision ID: 0006
Revises: 0005
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("partners", sa.Column("evac_version", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.add_column("tenants", sa.Column("house_screen", sa.Boolean(), nullable=False, server_default=sa.text("0")))
    op.add_column("tenants", sa.Column("evac_version", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.add_column("invitations", sa.Column("recurring", sa.Boolean(), nullable=False, server_default=sa.text("0")))
    op.add_column("invitations", sa.Column("valid_until", sa.DateTime(), nullable=True))
    op.create_table(
        "visit_stats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("month", sa.Unicode(7), nullable=False),
        sa.Column("kind", sa.Unicode(10), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.UniqueConstraint("tenant_id", "month", "kind", name="uq_visit_stats"),
    )
    op.create_index("ix_visit_stats_tenant_id", "visit_stats", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("visit_stats")
    op.drop_column("invitations", "valid_until")
    op.drop_column("invitations", "recurring")
    op.drop_column("tenants", "evac_version")
    op.drop_column("tenants", "house_screen")
    op.drop_column("partners", "evac_version")
