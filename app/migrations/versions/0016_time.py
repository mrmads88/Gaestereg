"""Tidsregistrering for medarbejdere: indstillinger, felter på personer, tidsposter og tilkøbet i prislisten.

Revision ID: 0016
Revises: 0015
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("time_kiosk", sa.Boolean(), nullable=False, server_default=sa.text("1")))
    op.add_column("tenants", sa.Column("time_break_min", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.add_column("hosts", sa.Column("time_enabled", sa.Boolean(), nullable=False, server_default=sa.text("0")))
    op.add_column("hosts", sa.Column("time_pin", sa.Unicode(200), nullable=False, server_default=sa.text("''")))
    op.add_column("hosts", sa.Column("time_norm_min", sa.Integer(), nullable=False, server_default=sa.text("0")))
    op.create_table(
        "time_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("host_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.Unicode(120), nullable=False),
        sa.Column("start_at", sa.DateTime(), nullable=False),
        sa.Column("end_at", sa.DateTime(), nullable=True),
        sa.Column("break_min", sa.Integer(), nullable=False),
        sa.Column("source", sa.Unicode(10), nullable=False),
        sa.Column("note", sa.Unicode(300), nullable=False),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("approved_by", sa.Unicode(200), nullable=False),
        sa.Column("edit_log", sa.UnicodeText(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_time_entries_tenant_id", "time_entries", ["tenant_id"])
    op.create_index("ix_time_entries_host_id", "time_entries", ["host_id"])
    op.create_index("ix_time_entries_start_at", "time_entries", ["start_at"])

    # Tilkøbet i prislisten (prisen kan rettes under Fakturering).
    conn = op.get_bind()
    if conn.execute(sa.text("SELECT COUNT(*) FROM products WHERE code = 'time'")).scalar() == 0:
        order = conn.execute(sa.text("SELECT COALESCE(MAX(sort_order), 0) + 1 FROM products")).scalar()
        products = sa.table("products", sa.column("code"), sa.column("name"), sa.column("kind"), sa.column("audience"),
                            sa.column("price"), sa.column("unit"), sa.column("modules"), sa.column("included_sms"),
                            sa.column("description"), sa.column("features"), sa.column("active"), sa.column("sort_order"))
        op.bulk_insert(products, [{
            "code": "time", "name": "Tidsregistrering", "kind": "addon", "audience": "all", "price": 24900, "unit": "md.",
            "modules": json.dumps(["time"]), "included_sms": 0,
            "description": "Medarbejdere stempler ind og ud på skærmen eller telefonen. Ugeskema, godkendelse og "
                           "eksport til lønsystemet. Op til 25 medarbejdere.",
            "features": "[]", "active": True, "sort_order": order}])


def downgrade() -> None:
    op.execute("DELETE FROM products WHERE code = 'time'")
    op.drop_table("time_entries")
    for col in ("time_norm_min", "time_pin", "time_enabled"):
        op.drop_column("hosts", col)
    for col in ("time_break_min", "time_kiosk"):
        op.drop_column("tenants", col)
