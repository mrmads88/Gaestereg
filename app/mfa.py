"""To-trins-login med en kodeapp (TOTP, RFC 6238), fx Microsoft Authenticator eller Google Authenticator.

- Påkrævet for leverandøren og husene (partnere), når MFA_REQUIRED er slået til (standard i prod). Frivilligt for
  kunde-admins.
- Efter adgangskoden får browseren en kortlivet "billet" (signeret, 5 minutter) og skal sende en kode fra appen
  eller en engangskode. Først derefter sættes login-cookien.
- Mister man telefonen, bruger man en engangskode, eller en administrator nulstiller to-trins-login. Leverandøren
  kan i nødstilfælde sætte ADMIN_MFA_RESET=1 og genstarte appen (se docs/azure.md).
"""
import base64
import hashlib
import hmac
import json
import secrets
import struct
import time

import segno
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner
from sqlalchemy import select

from .config import settings
from .models import PlatformAccount, User, utcnow

ISSUER = "Nodd"
STEP = 30
DIGITS = 6
TICKET_MAX_AGE = 5 * 60
RECOVERY_COUNT = 10

_ticket = TimestampSigner(settings.secret_key, salt="admin-mfa-ticket")


# ---------- TOTP ----------

def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _key(secret: str) -> bytes:
    return base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)


def code_at(secret: str, step: int) -> str:
    digest = hmac.new(_key(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    o = digest[-1] & 0x0F
    n = (struct.unpack(">I", digest[o:o + 4])[0] & 0x7FFFFFFF) % 10 ** DIGITS
    return str(n).zfill(DIGITS)


def current_step(now: float | None = None) -> int:
    return int((time.time() if now is None else now) // STEP)


def check_totp(secret: str, code: str, last_step: int = 0, now: float | None = None) -> int | None:
    """Gyldig kode (±30 sekunder for ure, der går lidt forkert) giver tidstrinnet, ellers None.
    En kode, der allerede er brugt (trin <= last_step), afvises."""
    code = "".join(ch for ch in code if ch.isdigit())
    if not secret or len(code) != DIGITS:
        return None
    step = current_step(now)
    for s in (step - 1, step, step + 1):
        if s > last_step and hmac.compare_digest(code_at(secret, s), code):
            return s
    return None


def otpauth_uri(secret: str, account: str) -> str:
    from urllib.parse import quote
    return (f"otpauth://totp/{quote(ISSUER)}:{quote(account)}?secret={secret}&issuer={quote(ISSUER)}"
            f"&algorithm=SHA1&digits={DIGITS}&period={STEP}")


def qr_svg(uri: str) -> str:
    return segno.make(uri, error="m").svg_inline(scale=5, dark="#14171d", light="#ffffff")


# ---------- engangskoder ----------

_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # ingen l/1/o/0, så de er nemme at skrive af


def _norm(code: str) -> str:
    return "".join(ch for ch in code.lower() if ch.isalnum())


def _hash(code: str) -> str:
    return hashlib.sha256(_norm(code).encode()).hexdigest()


def new_recovery_codes(holder) -> list[str]:
    codes = ["".join(secrets.choice(_ALPHABET) for _ in range(4)) + "-" + "".join(secrets.choice(_ALPHABET) for _ in range(4))
             for _ in range(RECOVERY_COUNT)]
    holder.mfa_recovery = json.dumps([_hash(c) for c in codes])
    return codes


def recovery_left(holder) -> int:
    try:
        return len(json.loads(holder.mfa_recovery or "[]"))
    except ValueError:
        return 0


def use_recovery(holder, code: str) -> bool:
    if len(_norm(code)) != 8:
        return False
    try:
        hashes = json.loads(holder.mfa_recovery or "[]")
    except ValueError:
        return False
    h = _hash(code)
    for x in hashes:
        if hmac.compare_digest(x, h):
            hashes.remove(x)
            holder.mfa_recovery = json.dumps(hashes)
            return True
    return False


def verify(holder, code: str) -> bool:
    """Kode fra appen eller en engangskode. Opdaterer holder (sidste trin / brugte koder); kalderen committer."""
    step = check_totp(holder.mfa_secret, code, holder.mfa_last_step or 0)
    if step is not None:
        holder.mfa_last_step = step
        return True
    return use_recovery(holder, code)


# ---------- hvem og hvornår ----------

def enabled(holder) -> bool:
    return holder is not None and holder.mfa_enabled_at is not None and bool(holder.mfa_secret)


def required_for(role: str) -> bool:
    return settings.mfa_required and role in ("platform", "partner")


def platform_account(db) -> PlatformAccount:
    acc = db.scalar(select(PlatformAccount).order_by(PlatformAccount.id))
    if acc is None:
        acc = PlatformAccount()
        db.add(acc)
        db.flush()
    return acc


def holder_of(db, p):
    """Kontoen, der har to-trins-login for den indloggede (bruger eller leverandørens konto)."""
    return p.user if p.user is not None else platform_account(db)


def enable(holder, code: str) -> list[str] | None:
    step = check_totp(holder.mfa_secret, code, 0)
    if step is None:
        return None
    holder.mfa_last_step = step
    holder.mfa_enabled_at = utcnow()
    holder.token_version += 1  # andre sessioner logges ud
    return new_recovery_codes(holder)


def disable(holder) -> None:
    holder.mfa_secret, holder.mfa_enabled_at, holder.mfa_recovery, holder.mfa_last_step = "", None, "", 0
    holder.token_version += 1


def reset_platform_on_start() -> None:
    """ADMIN_MFA_RESET=1: leverandøren har mistet telefon og engangskoder. Slår to-trins-login fra ved opstart."""
    if not settings.admin_mfa_reset:
        return
    import logging
    from .db import SessionLocal
    with SessionLocal() as db:
        acc = platform_account(db)
        if enabled(acc):
            disable(acc)
            logging.getLogger("gaestereg.mfa").warning(
                "ADMIN_MFA_RESET: leverandørens to-trins-login er slået fra. Fjern indstillingen igen.")
        db.commit()


# ---------- billet mellem adgangskode og kode ----------

def ticket_for(holder) -> str:
    kind = "u" if isinstance(holder, User) else "p"
    return _ticket.sign(f"{kind}:{holder.id}:{holder.token_version}".encode()).decode()


def holder_from_ticket(db, ticket: str):
    try:
        kind, hid, version = _ticket.unsign(ticket, max_age=TICKET_MAX_AGE).decode().split(":")
        holder = db.get(User if kind == "u" else PlatformAccount, int(hid))
    except (BadSignature, SignatureExpired, ValueError):
        return None
    if holder is None or holder.token_version != int(version) or not enabled(holder):
        return None
    return holder
