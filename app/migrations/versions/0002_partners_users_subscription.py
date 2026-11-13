"""Partnere, admin-brugere og abonnement på kunderne.

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    sqlite = op.get_bind().dialect.name == "sqlite"

    op.create_table(
        "partners",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.Unicode(120), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    # Nye kolonner på en tabel med data: NOT NULL kræver en standardværdi i databasen.
    op.add_column("tenants", sa.Column("partner_id", sa.Integer(), nullable=True))
    if not sqlite:
        # SQLite kan ikke tilføje en fremmednøgle uden at genopbygge tabellen. Med foreign_keys=ON ville
        # det slette personer og besøg via ON DELETE CASCADE. SQLite bruges kun lokalt og i tests.
        op.create_foreign_key("fk_tenants_partner_id", "tenants", "partners", ["partner_id"], ["id"])
    op.create_index("ix_tenants_partner_id", "tenants", ["partner_id"])
    op.add_column("tenants", sa.Column("sub_yearly_price", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.add_column("tenants", sa.Column("self_service", sa.Boolean(), nullable=False, server_default=sa.text("0")))
    op.add_column("tenants", sa.Column("self_service_monthly_price", sa.Integer(), nullable=False,
                                       server_default=sa.text("0")))
    op.add_column("tenants", sa.Column("sub_paid_until", sa.Date(), nullable=True))
    op.add_column("tenants", sa.Column("sub_note", sa.Unicode(500), nullable=False, server_default=sa.text("''")))

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.Unicode(200), nullable=False),
        sa.Column("name", sa.Unicode(120), nullable=False),
        sa.Column("role", sa.Unicode(10), nullable=False),
        sa.Column("partner_id", sa.Integer(), sa.ForeignKey("partners.id"), nullable=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True),
        sa.Column("password_hash", sa.Unicode(300), nullable=False),
        sa.Column("token_version", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_partner_id", "users", ["partner_id"])
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("users")
    for col in ("sub_note", "sub_paid_until", "self_service_monthly_price", "self_service", "sub_yearly_price"):
        op.drop_column("tenants", col)
    op.drop_index("ix_tenants_partner_id", "tenants")
    if op.get_bind().dialect.name != "sqlite":
        op.drop_constraint("fk_tenants_partner_id", "tenants", type_="foreignkey")
    op.drop_column("tenants", "partner_id")
    op.drop_table("partners")
