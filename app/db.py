import logging
import time

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings

log = logging.getLogger(__name__)

_is_sqlite = settings.database_url.startswith("sqlite")
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
    pool_pre_ping=True,
    # Azure lukker forbindelser, der har ligget stille i 30 min. Forny dem før.
    pool_recycle=-1 if _is_sqlite else 1200,
)

if _is_sqlite:
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()

# Fejl, Azure SQL giver, mens en serverless-database vågner fra pause eller flyttes.
# 40613: databasen er ikke tilgængelig lige nu. HYT00/08001/08S01: timeout eller mistet forbindelse.
_TRANSIENT = ("40613", "40197", "40501", "49918", "49919", "49920", "HYT00", "08001", "08S01")
CONNECT_ATTEMPTS = 8
CONNECT_WAIT_SECONDS = 10

if engine.dialect.name == "mssql":
    @event.listens_for(engine, "do_connect")
    def _connect_with_retry(dialect, _conn_rec, cargs, cparams):
        # Gratis-databasen i Azure går på pause, når den ikke bruges. Første forbindelse
        # vækker den, og det tager typisk under et minut. Vent i stedet for at fejle.
        for attempt in range(1, CONNECT_ATTEMPTS + 1):
            try:
                return dialect.loaded_dbapi.connect(*cargs, **cparams)
            except dialect.loaded_dbapi.Error as e:
                if attempt == CONNECT_ATTEMPTS or not any(code in str(e) for code in _TRANSIENT):
                    raise
                log.warning("Databasen svarer ikke endnu (forsøg %d af %d). Prøver igen om %d sek.",
                            attempt, CONNECT_ATTEMPTS, CONNECT_WAIT_SECONDS)
                time.sleep(CONNECT_WAIT_SECONDS)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from . import models  # noqa: F401  (registers tables)
    Base.metadata.create_all(engine)
