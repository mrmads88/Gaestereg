"""Alembic-miljø. Køres fra app.db.init_db() med en åben forbindelse (se `connection` nedenfor)."""
from alembic import context

from app.db import Base
from app import models  # noqa: F401  (registrerer tabellerne)

config = context.config
target_metadata = Base.metadata


def run_migrations_online() -> None:
    connection = config.attributes["connection"]
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # SQLite kan ikke ændre kolonner på stedet. render_as_batch kopierer tabellen i stedet.
        render_as_batch=connection.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


run_migrations_online()
