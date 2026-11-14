"""To-trins-login: felter på brugere og leverandørens egen konto.

Revision ID: 0014
Revises: 0013
"""
import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def _mfa_columns() -> list:
    return [
        sa.Column("mfa_secret", sa.Unicode(64), nullable=False, server_default=sa.text("''")),
        sa.Column("mfa_enabled_at", sa.DateTime(), nullable=True),
        sa.Column("mfa_recovery", sa.UnicodeText(), nullable=False, server_default=sa.text("''")),
        sa.Column("mfa_last_step", sa.Integer(), nullable=False, server_default=sa.text("0")),
    ]


def upgrade() -> None:
    for col in _mfa_columns():
        op.add_column("users", col)
    op.create_table(
        "platform_account",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token_version", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        *_mfa_columns(),
    )


def downgrade() -> None:
    op.drop_table("platform_account")
    for col in ("mfa_last_step", "mfa_recovery", "mfa_enabled_at", "mfa_secret"):
        op.drop_column("users", col)
