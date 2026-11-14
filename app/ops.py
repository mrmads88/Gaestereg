"""Drift: fejlmails til leverandøren og "klar til prod"-tjekket.

Fejlmails: alle fejl, appen logger (fx en uventet fejl i en side), sendes til OPS_EMAIL. Højst én mail pr. slags fejl
pr. 15 minutter og højst 20 om dagen, så en fejl i en løkke ikke fylder indbakken. Kun i live-tilstand med SMTP.
"""
import logging
import threading
import time
import traceback
from datetime import datetime

from .config import settings

THROTTLE_SECONDS = 15 * 60
MAX_PER_DAY = 20


class OpsMailHandler(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.ERROR)
        self._last: dict[str, float] = {}
        self._day = ""
        self._count = 0
        self._lock = threading.Lock()

    def _allowed(self, key: str) -> bool:
        today = datetime.now().strftime("%Y-%m-%d")
        now = time.monotonic()
        with self._lock:
            if today != self._day:
                self._day, self._count, self._last = today, 0, {}
            if self._count >= MAX_PER_DAY or now - self._last.get(key, -1e9) < THROTTLE_SECONDS:
                return False
            self._last[key] = now
            self._count += 1
            return True

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if not (settings.ops_email and settings.notify_mode == "live" and settings.smtp_configured):
                return
            exc = record.exc_info[1] if record.exc_info else None
            key = f"{record.name}:{type(exc).__name__ if exc else ''}:{record.getMessage()[:120]}"
            if not self._allowed(key):
                return
            body = "\n".join([f"Miljø: {settings.env}", f"Tid: {datetime.now():%d.%m.%Y %H:%M:%S}",
                              f"Hvor: {record.name}", "", record.getMessage(), "",
                              "".join(traceback.format_exception(*record.exc_info)) if record.exc_info else ""])
            subject = f"Fejl i Nodd ({settings.env}): {(str(exc) or type(exc).__name__) if exc else record.getMessage()}"[:150]
            threading.Thread(target=_send, args=(subject, body), daemon=True).start()
        except Exception:  # noqa: BLE001 - logning må aldrig selv give fejl
            pass


def _send(subject: str, body: str) -> None:
    from .notify import send_email
    for addr in [x.strip() for x in settings.ops_email.split(",") if x.strip()]:
        try:
            send_email(addr, subject, body, "Nodd drift")
        except Exception:  # noqa: BLE001
            pass


_handler: OpsMailHandler | None = None


def install() -> None:
    """Sæt fejlmails på rodloggeren og uvicorns fejllog (én gang)."""
    global _handler
    if _handler is not None:
        return
    _handler = OpsMailHandler()
    for name in ("", "uvicorn.error"):
        logging.getLogger(name).addHandler(_handler)


def copy_media_to_blob() -> dict:
    """Kopiér billeder, der kun ligger som filer (fra før Blob), op i Blob Storage. Springer dem over, der findes."""
    from .media import BlobStorage, storage
    if not isinstance(storage, BlobStorage):
        return {"ok": False, "message": "Blob Storage er ikke sat op (AZURE_STORAGE_CONNECTION_STRING)."}
    files = sorted(p for p in settings.media_dir.iterdir() if p.is_file())
    sent = skipped = 0
    for p in files:
        if storage.container.get_blob_client(p.name).exists():
            skipped += 1
            continue
        storage.save(p.name, p.read_bytes())
        sent += 1
    return {"ok": True, "sent": sent, "skipped": skipped,
            "message": f"{sent} billeder kopieret til Blob, {skipped} fandtes allerede."}


def readiness() -> list[dict]:
    """Hvad der mangler, før miljøet kan bruges med rigtige kunder. Vises for leverandøren i admin."""
    from .media import BlobStorage, storage
    live = settings.env == "prod"
    checks = [
        ("live", "Beskeder sendes rigtigt (NOTIFY_MODE=live)", settings.notify_mode == "live"),
        ("sms", "SMS via GatewayAPI (GATEWAYAPI_TOKEN)", settings.sms_configured),
        ("smtp", "Mail via SMTP (SMTP_HOST og SMTP_FROM)", settings.smtp_configured),
        ("blob", "Billeder i Azure Blob Storage (AZURE_STORAGE_CONNECTION_STRING)", isinstance(storage, BlobStorage)),
        ("url", "Eget domæne til links i mails (PUBLIC_URL)", bool(settings.public_url_explicit)),
        ("ops", "Fejlmails til dig (OPS_EMAIL)", bool(settings.ops_email)),
        ("operator", "Dine firmaoplysninger i databehandleraftale og privatlivsside (OPERATOR_NAME, OPERATOR_CVR)",
         bool(settings.operator_name and settings.operator_cvr)),
        ("dpa", "Databehandleraftalen er godkendt af en jurist (DPA_FINAL=1)", settings.dpa_final),
        ("password", "Egen admin-adgangskode (ADMIN_PASSWORD)", bool(settings.admin_password)),
    ]
    return [{"key": k, "label": label, "ok": ok, "required": live} for k, label, ok in checks]
