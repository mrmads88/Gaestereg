"""Fase 5b: forplejning (køkkener, menu og bestillinger).

Revision ID: 0008
Revises: 0007
"""
import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kitchens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True),
        sa.Column("partner_id", sa.Integer(), sa.ForeignKey("partners.id"), nullable=True),
        sa.Column("name", sa.Unicode(120), nullable=False),
        sa.Column("kind", sa.Unicode(10), nullable=False),
        sa.Column("email", sa.Unicode(200), nullable=False),
        sa.Column("phone", sa.Unicode(40), nullable=False),
        sa.Column("lead_hours", sa.Integer(), nullable=False),
        sa.Column("note", sa.Unicode(300), nullable=False),
        sa.Column("order_token", sa.Unicode(40), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_kitchens_tenant_id", "kitchens", ["tenant_id"])
    op.create_index("ix_kitchens_partner_id", "kitchens", ["partner_id"])
    op.create_index("ix_kitchens_order_token", "kitchens", ["order_token"], unique=True)
    op.create_table(
        "menu_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kitchen_id", sa.Integer(), sa.ForeignKey("kitchens.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Unicode(120), nullable=False),
        sa.Column("description", sa.Unicode(300), nullable=False),
        sa.Column("category", sa.Unicode(40), nullable=False),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.Column("unit", sa.Unicode(20), nullable=False),
        sa.Column("photo_path", sa.Unicode(200), nullable=False),
        sa.Column("tags", sa.UnicodeText(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_menu_items_kitchen_id", "menu_items", ["kitchen_id"])
    op.create_table(
        "catering_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("booking_id", sa.Integer(), sa.ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kitchen_id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=True),
        sa.Column("deliver_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.Unicode(12), nullable=False),
        sa.Column("note", sa.Unicode(500), nullable=False),
        sa.Column("cost_center", sa.Unicode(60), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_catering_orders_booking_id", "catering_orders", ["booking_id"], unique=True)
    op.create_index("ix_catering_orders_kitchen_id", "catering_orders", ["kitchen_id"])
    op.create_index("ix_catering_orders_tenant_id", "catering_orders", ["tenant_id"])
    op.create_index("ix_catering_orders_deliver_at", "catering_orders", ["deliver_at"])
    op.create_table(
        "catering_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("catering_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("menu_item_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.Unicode(120), nullable=False),
        sa.Column("unit", sa.Unicode(20), nullable=False),
        sa.Column("unit_price", sa.Integer(), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
    )
    op.create_index("ix_catering_lines_order_id", "catering_lines", ["order_id"])


def downgrade() -> None:
    op.drop_table("catering_lines")
    op.drop_table("catering_orders")
    op.drop_table("menu_items")
    op.drop_table("kitchens")
