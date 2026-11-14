"""Settings read from environment variables (see .env.example)."""
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader for local development. Real environment variables win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


if os.getenv("APP_ENV", "local") == "local":
    _load_dotenv(BASE_DIR / ".env")


def _bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None or v == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "ja", "on")


@dataclass
class Settings:
    env: str = field(default_factory=lambda: os.getenv("APP_ENV", "local"))  # local | dev | prod
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("DATA_DIR", str(BASE_DIR / "data"))))
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", ""))
    admin_password: str = field(default_factory=lambda: os.getenv("ADMIN_PASSWORD", ""))
    secret_key: str = field(default_factory=lambda: os.getenv("SECRET_KEY", ""))
    timezone: str = field(default_factory=lambda: os.getenv("TIMEZONE", "Europe/Copenhagen"))
    seed_demo: bool = field(default_factory=lambda: _bool("SEED_DEMO", True))
    # Hvor længe skærmens opsætning må genbruges uden at spørge databasen. Ændringer i admin slår igennem med det samme.
    kiosk_cache_seconds: int = field(default_factory=lambda: int(os.getenv("KIOSK_CACHE_SECONDS", "86400")))

    # Notifications. "test" = log only, never send. "live" = send for real.
    notify_mode: str = field(default_factory=lambda: os.getenv("NOTIFY_MODE", "test").lower())

    smtp_host: str = field(default_factory=lambda: os.getenv("SMTP_HOST", ""))
    smtp_port: int = field(default_factory=lambda: int(os.getenv("SMTP_PORT", "587")))
    smtp_user: str = field(default_factory=lambda: os.getenv("SMTP_USER", ""))
    smtp_password: str = field(default_factory=lambda: os.getenv("SMTP_PASSWORD", ""))
    smtp_from: str = field(default_factory=lambda: os.getenv("SMTP_FROM", ""))
    smtp_starttls: bool = field(default_factory=lambda: _bool("SMTP_STARTTLS", True))

    gatewayapi_token: str = field(default_factory=lambda: os.getenv("GATEWAYAPI_TOKEN", ""))
    gatewayapi_url: str = field(default_factory=lambda: os.getenv("GATEWAYAPI_URL", "https://gatewayapi.com/rest/mtsms"))
    # Billeder i Azure Blob Storage (prod). Tom = lokale filer i DATA_DIR/media.
    azure_storage_connection_string: str = field(default_factory=lambda: os.getenv("AZURE_STORAGE_CONNECTION_STRING", ""))
    azure_storage_container: str = field(default_factory=lambda: os.getenv("AZURE_STORAGE_CONTAINER", "media"))
    # Månedsrapporter sendes automatisk den 1. kl. 07 (slås fra i tests). Links i mails peger på public_url.
    report_scheduler: bool = field(default_factory=lambda: _bool("REPORT_SCHEDULER", True))
    public_url: str = field(default_factory=lambda: os.getenv("PUBLIC_URL", "") or (
        f"https://{os.environ['WEBSITE_HOSTNAME']}" if os.getenv("WEBSITE_HOSTNAME") else "http://localhost:8000"))
    public_url_explicit: str = field(default_factory=lambda: os.getenv("PUBLIC_URL", ""))
    # Fejlmails til leverandøren (komma mellem flere). Tom = ingen fejlmails.
    ops_email: str = field(default_factory=lambda: os.getenv("OPS_EMAIL", ""))
    # Leverandøren (databehandleren) i databehandleraftalen og på gæsternes privatlivsside.
    operator_name: str = field(default_factory=lambda: os.getenv("OPERATOR_NAME", ""))
    operator_cvr: str = field(default_factory=lambda: os.getenv("OPERATOR_CVR", ""))
    operator_address: str = field(default_factory=lambda: os.getenv("OPERATOR_ADDRESS", ""))
    operator_email: str = field(default_factory=lambda: os.getenv("OPERATOR_EMAIL", ""))
    # Sæt DPA_FINAL=1, når en jurist har godkendt teksten i app/texts/. Indtil da står den som udkast.
    dpa_final: bool = field(default_factory=lambda: _bool("DPA_FINAL", False))

    def __post_init__(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.media_dir.mkdir(parents=True, exist_ok=True)
        if not self.database_url:
            self.database_url = f"sqlite:///{self.data_dir / 'app.db'}"
        if not self.secret_key:
            key_file = self.data_dir / "secret.key"
            if key_file.exists():
                self.secret_key = key_file.read_text().strip()
            else:
                self.secret_key = secrets.token_urlsafe(48)
                key_file.write_text(self.secret_key)

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"

    @property
    def admin_password_effective(self) -> str:
        # Locally a default makes first start easy. In dev/prod a real password is required.
        if self.admin_password:
            return self.admin_password
        return "admin" if self.env == "local" else ""

    @property
    def sms_configured(self) -> bool:
        return bool(self.gatewayapi_token)

    @property
    def smtp_configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_from)


settings = Settings()
