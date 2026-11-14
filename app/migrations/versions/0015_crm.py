"""CRM for leverandøren: firmaer, kontakter, salgsmuligheder og aktiviteter.

Revision ID: 0015
Revises: 0014
"""
import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crm_companies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.Unicode(160), nullable=False),
        sa.Column("status", sa.Unicode(12), nullable=False),
        sa.Column("segment", sa.Unicode(20), nullable=False),
        sa.Column("cvr", sa.Unicode(20), nullable=False),
        sa.Column("website", sa.Unicode(200), nullable=False),
        sa.Column("phone", sa.Unicode(40), nullable=False),
        sa.Column("email", sa.Unicode(200), nullable=False),
        sa.Column("address", sa.Unicode(300), nullable=False),
        sa.Column("source", sa.Unicode(80), nullable=False),
        sa.Column("notes", sa.UnicodeText(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=True),
        sa.Column("partner_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_crm_companies_tenant_id", "crm_companies", ["tenant_id"])
    op.create_index("ix_crm_companies_partner_id", "crm_companies", ["partner_id"])
    op.create_table(
        "crm_contacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("crm_companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Unicode(120), nullable=False),
        sa.Column("title", sa.Unicode(120), nullable=False),
        sa.Column("email", sa.Unicode(200), nullable=False),
        sa.Column("phone", sa.Unicode(40), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Unicode(500), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_crm_contacts_company_id", "crm_contacts", ["company_id"])
    op.create_table(
        "crm_deals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("crm_companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.Unicode(160), nullable=False),
        sa.Column("stage", sa.Unicode(12), nullable=False),
        sa.Column("monthly", sa.Integer(), nullable=False),
        sa.Column("once", sa.Integer(), nullable=False),
        sa.Column("expected_close", sa.Date(), nullable=True),
        sa.Column("lost_reason", sa.Unicode(300), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_crm_deals_company_id", "crm_deals", ["company_id"])
    op.create_index("ix_crm_deals_stage", "crm_deals", ["stage"])
    op.create_table(
        "crm_activities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("crm_companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("deal_id", sa.Integer(), nullable=True),
        sa.Column("contact_id", sa.Integer(), nullable=True),
        sa.Column("kind", sa.Unicode(12), nullable=False),
        sa.Column("text", sa.UnicodeText(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("done_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_crm_activities_company_id", "crm_activities", ["company_id"])
    op.create_index("ix_crm_activities_deal_id", "crm_activities", ["deal_id"])
    op.create_index("ix_crm_activities_due_date", "crm_activities", ["due_date"])
    op.create_index("ix_crm_activities_created_at", "crm_activities", ["created_at"])


def downgrade() -> None:
    for t in ("crm_activities", "crm_deals", "crm_contacts", "crm_companies"):
        op.drop_table(t)
