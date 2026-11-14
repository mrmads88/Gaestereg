"""Pakker, tilkøb og fakturering (moduler følger af det, kunden har købt) samt månedsrapporter.

Prislisten oprettes med et forslag, som leverandøren kan rette i admin. Firmaer og huse, der allerede har lokaler
eller køkkener, tilmeldes de tilsvarende tilkøb, så intet forsvinder.

Revision ID: 0009
Revises: 0008
"""
import json
from datetime import date

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

# (code, name, kind, audience, price i øre, unit, modules, included_sms, description, features)
CATALOG = [
    ("start", "Start", "package", "firm", 34900, "md.", [], 100,
     "Digital gæsteregistrering til receptionen.",
     ["Gæsteskærm med jeres logo og farver", "Besked til værten på SMS, mail og Teams", "Invitationer med kode og QR",
      "Pakkemodtagelse og evakueringsliste", "100 SMS om måneden"]),
    ("plus", "Plus", "package", "firm", 64900, "md.", ["self_service", "reports"], 300,
     "Til firmaer, der selv vil styre skærm og personer.",
     ["Alt i Start", "Egne administratorer (selvbetjening)", "Overblik og månedsrapport", "300 SMS om måneden"]),
    ("komplet", "Komplet", "package", "firm", 119500, "md.", ["self_service", "reports", "rooms", "catering", "signage"], 500,
     "Gæster, mødelokaler, forplejning og infoskærm i én pakke.",
     ["Alt i Plus", "Mødelokaler med lokaleskærme (op til 5)", "Forplejning med menu og køkkenside", "Infoskærm",
      "500 SMS om måneden"]),
    ("hus", "Hus", "package", "house", 249500, "md.", ["self_service", "reports", "rooms", "catering", "signage"], 1000,
     "Til kontorhoteller og huse med flere firmaer.",
     ["Husets fælles skærm for alle firmaer", "Op til 10 firmaer med egne personer", "Mødelokaler og forplejning for alle",
      "Evakueringsliste og statistik for hele huset", "1.000 SMS om måneden"]),
    ("rooms", "Mødelokaler", "addon", "all", 34900, "md.", ["rooms"], 0,
     "Booking, lokaleskærme ved døren og diskretion om mødetitler. Op til 5 lokaler.", []),
    ("catering", "Forplejning", "addon", "all", 24900, "md.", ["catering"], 0,
     "Menu med billeder og priser, bestilling sammen med lokalet og køkkenets side.", []),
    ("self_service", "Selvbetjening", "addon", "firm", 14900, "md.", ["self_service"], 0,
     "Kundens egne administratorer kan rette skærm, personer og beskeder.", []),
    ("reports", "Overblik og månedsrapport", "addon", "all", 9900, "md.", ["reports"], 0,
     "Dashboard til ledelsen og månedsrapport på mail med CSV.", []),
    ("signage", "Infoskærm", "addon", "all", 19900, "md.", ["signage"], 0,
     "Infoskærme med velkomst, mødelokaler, menu og nyheder (kommer snart).", []),
    ("extra_screen", "Ekstra skærm", "addon", "all", 9900, "md.", [], 0, "Pr. ekstra gæste- eller infoskærm.", []),
    ("extra_room", "Ekstra mødelokale", "addon", "all", 4900, "md.", [], 0, "Pr. lokale ud over de 5 inkluderede.", []),
    ("extra_firm", "Ekstra firma i huset", "addon", "house", 9900, "md.", [], 0, "Pr. firma ud over de 10 i Hus.", []),
    ("sms", "SMS ud over pakken", "usage", "all", 39, "stk.", [], 0, "Afregnes bagud efter forbrug.", []),
    ("setup", "Opsætning og oplæring", "once", "all", 149500, "stk.", [], 0,
     "Vi sætter skærmen op med logo, personer og beskeder og viser jer, hvordan den bruges.", []),
    ("tablet", "Tablet med gulvstander", "once", "all", 449500, "stk.", [], 0, "Klar til brug, med lås og strøm.", []),
]


def upgrade() -> None:
    for table in ("tenants", "partners"):
        op.add_column(table, sa.Column("report_email", sa.Unicode(500), nullable=False, server_default=sa.text("''")))
    op.create_table(
        "report_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scope", sa.Unicode(10), nullable=False),
        sa.Column("scope_id", sa.Integer(), nullable=False),
        sa.Column("month", sa.Unicode(7), nullable=False),
        sa.Column("recipients", sa.Unicode(500), nullable=False),
        sa.Column("status", sa.Unicode(10), nullable=False),
        sa.Column("error", sa.UnicodeText(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("scope", "scope_id", "month", name="uq_report_run"),
    )
    products = op.create_table(
        "products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.Unicode(40), nullable=False),
        sa.Column("name", sa.Unicode(120), nullable=False),
        sa.Column("kind", sa.Unicode(10), nullable=False),
        sa.Column("audience", sa.Unicode(10), nullable=False),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.Column("unit", sa.Unicode(20), nullable=False),
        sa.Column("modules", sa.UnicodeText(), nullable=False),
        sa.Column("included_sms", sa.Integer(), nullable=False),
        sa.Column("description", sa.Unicode(500), nullable=False),
        sa.Column("features", sa.UnicodeText(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
    )
    op.create_index("ix_products_code", "products", ["code"], unique=True)
    op.create_table(
        "billing_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, unique=True),
        sa.Column("partner_id", sa.Integer(), sa.ForeignKey("partners.id"), nullable=True, unique=True),
        sa.Column("interval", sa.Unicode(10), nullable=False),
        sa.Column("discount_pct", sa.Integer(), nullable=False),
        sa.Column("cvr", sa.Unicode(20), nullable=False),
        sa.Column("invoice_email", sa.Unicode(200), nullable=False),
        sa.Column("reference", sa.Unicode(120), nullable=False),
        sa.Column("note", sa.Unicode(500), nullable=False),
        sa.Column("usage_billed_through", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "account_products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("billing_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("billed_through", sa.Date(), nullable=True),
        sa.Column("price_override", sa.Integer(), nullable=True),
        sa.Column("discount_pct", sa.Integer(), nullable=False),
        sa.Column("note", sa.Unicode(200), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_account_products_account_id", "account_products", ["account_id"])
    op.create_index("ix_account_products_product_id", "account_products", ["product_id"])
    op.create_table(
        "adjustments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("billing_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("description", sa.Unicode(200), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("invoice_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_adjustments_account_id", "adjustments", ["account_id"])
    op.create_index("ix_adjustments_invoice_id", "adjustments", ["invoice_id"])
    op.create_table(
        "invoices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("billing_accounts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("number", sa.Integer(), nullable=True),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("usage_until", sa.Date(), nullable=True),
        sa.Column("status", sa.Unicode(10), nullable=False),
        sa.Column("subtotal", sa.Integer(), nullable=False),
        sa.Column("vat", sa.Integer(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("finalized_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_invoices_account_id", "invoices", ["account_id"])
    op.create_table(
        "invoice_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("invoice_id", sa.Integer(), sa.ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.Unicode(12), nullable=False),
        sa.Column("description", sa.Unicode(300), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("ref_id", sa.Integer(), nullable=True),
        sa.Column("ref_end", sa.Date(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
    )
    op.create_index("ix_invoice_lines_invoice_id", "invoice_lines", ["invoice_id"])

    op.bulk_insert(products, [
        {"code": c, "name": n, "kind": k, "audience": a, "price": p, "unit": u, "modules": json.dumps(m),
         "included_sms": sms, "description": d, "features": json.dumps(f, ensure_ascii=False), "active": True,
         "sort_order": i} for i, (c, n, k, a, p, u, m, sms, d, f) in enumerate(CATALOG)])

    # Bevar det, der allerede er sat op: ejere af lokaler/køkkener tilmeldes tilkøbet fra i dag.
    conn = op.get_bind()
    today = date.today()
    pid = {r.code: r.id for r in conn.execute(sa.text("SELECT id, code FROM products"))}
    for code, table in (("rooms", "rooms"), ("catering", "kitchens")):
        for col in ("tenant_id", "partner_id"):
            owners = [r[0] for r in conn.execute(sa.text(f"SELECT DISTINCT {col} FROM {table} WHERE {col} IS NOT NULL"))]
            for owner in owners:
                acc = conn.execute(sa.text(f"SELECT id FROM billing_accounts WHERE {col} = :o"), {"o": owner}).scalar()
                if acc is None:
                    conn.execute(sa.text(
                        f"INSERT INTO billing_accounts ({col}, interval, discount_pct, cvr, invoice_email, reference, note,"
                        " created_at) VALUES (:o, 'month', 0, '', '', '', '', CURRENT_TIMESTAMP)"), {"o": owner})
                    acc = conn.execute(sa.text(f"SELECT id FROM billing_accounts WHERE {col} = :o"), {"o": owner}).scalar()
                conn.execute(sa.text(
                    "INSERT INTO account_products (account_id, product_id, qty, start_date, discount_pct, note, created_at)"
                    " VALUES (:a, :p, 1, :d, 0, 'Overført ved opgradering', CURRENT_TIMESTAMP)"),
                    {"a": acc, "p": pid[code], "d": today})


def downgrade() -> None:
    for t in ("invoice_lines", "invoices", "adjustments", "account_products", "billing_accounts", "products",
              "report_runs"):
        op.drop_table(t)
    for table in ("tenants", "partners"):
        op.drop_column(table, "report_email")
