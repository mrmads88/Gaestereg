"""Flere huse kan have en kundekonto: filtrerede unikke indeks på billing_accounts.

SQL Server tillader kun én NULL i en kolonne med UNIQUE. Alle huse har tenant_id = NULL (og alle firmaer partner_id =
NULL), så konto nummer to fejlede. De unavngivne UNIQUE-krav fra 0009 fjernes på SQL Server og erstattes af unikke indeks,
der kun gælder rækker med en værdi. På SQLite er de gamle krav harmløse (SQLite tillader flere NULL), og tabellen bygges
ikke om (fremmednøglerne er slået til, så en ombygning kunne slette tilmeldingerne).

Revision ID: 0019
Revises: 0018
"""
import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

DROP_UQ = """
DECLARE @n sysname;
SELECT @n = kc.name FROM sys.key_constraints kc
  JOIN sys.index_columns ic ON ic.object_id = kc.parent_object_id AND ic.index_id = kc.unique_index_id
  JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
  WHERE kc.type = 'UQ' AND kc.parent_object_id = OBJECT_ID('billing_accounts') AND c.name = '{col}';
DECLARE @sql nvarchar(400) = N'ALTER TABLE billing_accounts DROP CONSTRAINT ' + QUOTENAME(@n);
IF @n IS NOT NULL EXEC(@sql);
"""


def upgrade() -> None:
    if op.get_bind().dialect.name == "mssql":
        for col in ("tenant_id", "partner_id"):
            op.execute(DROP_UQ.format(col=col))
    for col, name in (("tenant_id", "uq_billing_accounts_tenant"), ("partner_id", "uq_billing_accounts_partner")):
        op.create_index(name, "billing_accounts", [col], unique=True, mssql_where=sa.text(f"{col} IS NOT NULL"),
                        sqlite_where=sa.text(f"{col} IS NOT NULL"))


def downgrade() -> None:
    op.drop_index("uq_billing_accounts_partner", table_name="billing_accounts")
    op.drop_index("uq_billing_accounts_tenant", table_name="billing_accounts")
