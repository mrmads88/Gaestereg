"""Migrationerne skal give præcis det skema, modellerne beskriver."""
import os
import tempfile

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text


def _diff(conn):
    from app import models  # noqa: F401
    from app.db import Base
    mc = MigrationContext.configure(conn, opts={"compare_type": True})
    return compare_metadata(mc, Base.metadata)


def test_migrated_schema_matches_models(client):
    from app.db import engine
    with engine.connect() as conn:
        diff = _diff(conn)
        if conn.dialect.name == "sqlite":
            # SQLite kan ikke tilføje fremmednøgler til en eksisterende tabel. De findes kun i SQL Server.
            diff = [d for d in diff if not (isinstance(d, tuple) and d[0] == "add_fk")]
        assert diff == [], f"Modeller og migrationer er ude af trit. Lav en ny migration: {diff}"


def test_existing_database_without_alembic_is_stamped_and_upgraded():
    """Dev og prod blev lavet med create_all før Alembic. De skal opgraderes uden at miste data."""
    from app.db import _alembic_config, BASELINE
    from alembic import command

    path = os.path.join(tempfile.mkdtemp(), "old.db")
    eng = create_engine(f"sqlite:///{path}")
    with eng.begin() as conn:
        command.upgrade(_alembic_config(conn), BASELINE)
        conn.execute(text("DROP TABLE alembic_version"))  # som en create_all-database
        conn.execute(text(
            "INSERT INTO tenants (id, name, kiosk_token, active, created_at, logo_path, color, background_path,"
            " background_scope, background_dim, welcome_text, show_photos, name_required, ask_phone,"
            " phone_required, ask_company, allow_unknown_host, reception_email, reception_phone, print_badge,"
            " badge_size, idle_seconds, retention_days, sms_sender, sms_template, email_subject, email_template)"
            " VALUES (1, 'Gammel A/S', 'tok', 1, '2026-11-01', '', '#000000', '', 'wall', 50, '', 1, 1, 1, 1, 0,"
            " 1, '', '', 0, '62x100', 60, 30, 'Gammel', 'x', 'y', 'z')"))

    import app.db as appdb
    orig = appdb.engine
    appdb.engine = eng
    try:
        appdb.init_db()
    finally:
        appdb.engine = orig
    with eng.connect() as conn:
        assert "alembic_version" in inspect(conn).get_table_names()
        assert conn.execute(text("SELECT name FROM tenants")).scalar() == "Gammel A/S"
