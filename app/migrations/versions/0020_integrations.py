"""Integrationer: webhooks, afsendelseslog og API-nøgler.

Revision ID: 0020
Revises: 0019
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "integrations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scope", sa.Unicode(10), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=True),
        sa.Column("partner_id", sa.Integer(), nullable=True),
        sa.Column("kind", sa.Unicode(20), nullable=False),
        sa.Column("name", sa.Unicode(120), nullable=False),
        sa.Column("config", sa.UnicodeText(), nullable=False),
        sa.Column("secret", sa.UnicodeText(), nullable=False),
        sa.Column("events", sa.UnicodeText(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("last_ok_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Unicode(500), nullable=False),
        sa.Column("last_error_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_integrations_tenant_id", "integrations", ["tenant_id"])
    op.create_index("ix_integrations_partner_id", "integrations", ["partner_id"])
    op.create_table(
        "integration_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("integration_id", sa.Integer(), sa.ForeignKey("integrations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event", sa.Unicode(40), nullable=False),
        sa.Column("payload", sa.UnicodeText(), nullable=False),
        sa.Column("status", sa.Unicode(10), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_at", sa.DateTime(), nullable=True),
        sa.Column("response_code", sa.Integer(), nullable=True),
        sa.Column("error", sa.Unicode(500), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("done_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_integration_deliveries_integration_id", "integration_deliveries", ["integration_id"])
    op.create_index("ix_integration_deliveries_status", "integration_deliveries", ["status"])
    op.create_index("ix_integration_deliveries_created_at", "integration_deliveries", ["created_at"])
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=True),
        sa.Column("partner_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.Unicode(120), nullable=False),
        sa.Column("prefix", sa.Unicode(16), nullable=False),
        sa.Column("key_hash", sa.Unicode(64), nullable=False),
        sa.Column("scopes", sa.Unicode(200), nullable=False),
        sa.Column("created_by", sa.Unicode(200), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_api_keys_tenant_id", "api_keys", ["tenant_id"])
    op.create_index("ix_api_keys_partner_id", "api_keys", ["partner_id"])
    op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"], unique=True)

    # Tilkøbet i prislisten (prisen kan rettes under Fakturering).
    conn = op.get_bind()
    if conn.execute(sa.text("SELECT COUNT(*) FROM products WHERE code = 'integrations'")).scalar() == 0:
        order = conn.execute(sa.text("SELECT COALESCE(MAX(sort_order), 0) + 1 FROM products")).scalar()
        products = sa.table("products", sa.column("code"), sa.column("name"), sa.column("kind"), sa.column("audience"),
                            sa.column("price"), sa.column("unit"), sa.column("modules"), sa.column("included_sms"),
                            sa.column("description"), sa.column("features"), sa.column("active"), sa.column("sort_order"))
        op.bulk_insert(products, [{
            "code": "integrations", "name": "Integrationer og API", "kind": "addon", "audience": "all", "price": 19900,
            "unit": "md.", "modules": json.dumps(["integrations"]), "included_sms": 0,
            "description": "Webhooks og API til jeres egne systemer, fx ServiceNow, Salesforce, Teams, Zapier, Make og "
                           "Power Automate.",
            "features": "[]", "active": True, "sort_order": order}])


def downgrade() -> None:
    op.execute("DELETE FROM products WHERE code = 'integrations'")
    op.drop_table("api_keys")
    op.drop_table("integration_deliveries")
    op.drop_table("integrations")
