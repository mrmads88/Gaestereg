"""Fase 3: forventede gæster (invitationer) og værtens personlige invitationslink.

Revision ID: 0005
Revises: 0004
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("hosts", sa.Column("link_version", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.create_table(
        "invitations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("host_id", sa.Integer(), sa.ForeignKey("hosts.id"), nullable=True),
        sa.Column("host_name", sa.Unicode(120), nullable=False),
        sa.Column("guest_name", sa.Unicode(120), nullable=False),
        sa.Column("guest_phone", sa.Unicode(40), nullable=False),
        sa.Column("guest_email", sa.Unicode(200), nullable=False),
        sa.Column("guest_company", sa.Unicode(120), nullable=False),
        sa.Column("expected_at", sa.DateTime(), nullable=False),
        sa.Column("code", sa.Unicode(6), nullable=False),
        sa.Column("status", sa.Unicode(12), nullable=False),
        sa.Column("visit_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Unicode(200), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_invitations_tenant_id", "invitations", ["tenant_id"])
    op.create_index("ix_invitations_expected_at", "invitations", ["expected_at"])
    op.create_index("ix_invitations_code", "invitations", ["code"])


def downgrade() -> None:
    op.drop_table("invitations")
    op.drop_column("hosts", "link_version")
