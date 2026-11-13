"""Login og adgang.

Tre roller:
- platform: dig. Logger ind med ADMIN_PASSWORD (uden e-mail). Ser og må alt.
- partner:  fx et kontorhotel. Ser og vedligeholder alle firmaer under sin partner og kan oprette nye.
- tenant:   kunde-admin. Ser og retter sit eget firma, når selvbetjening er slået til.

Sessionen er en signeret cookie. For brugere indeholder den token_version, så en ny adgangskode
eller et nyt invitationslink logger alle andre sessioner ud.
"""
import base64
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import Partner, Tenant, User

COOKIE = "gr_admin"
MAX_AGE = 7 * 24 * 3600
INVITE_MAX_AGE = 7 * 24 * 3600
MIN_PASSWORD = 10

_session = TimestampSigner(settings.secret_key, salt="admin-session")
_invite = TimestampSigner(settings.secret_key, salt="admin-invite")


# ---------- passwords ----------

_N, _R, _P = 2 ** 14, 8, 1


def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return f"scrypt${_N}${_R}${_P}${b64(salt)}${b64(h)}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, h = stored.split("$")
        if algo != "scrypt":
            return False
        got = hashlib.scrypt(pw.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                             dklen=len(base64.b64decode(h)))
        return hmac.compare_digest(got, base64.b64decode(h))
    except (ValueError, TypeError):
        return False


_DUMMY = hash_password(secrets.token_hex(8))


def slow_down() -> None:
    time.sleep(0.6)  # gør gætteri langsomt


def check_master_password(pw: str) -> bool:
    expected = settings.admin_password_effective
    if not expected:
        return False
    return secrets.compare_digest(pw.encode(), expected.encode())


def check_user_password(user: User | None, pw: str) -> bool:
    if user is None or not user.password_hash:
        verify_password(pw, _DUMMY)  # samme svartid, uanset om e-mailen findes
        return False
    return verify_password(pw, user.password_hash)


# ---------- who is logged in ----------

@dataclass
class Principal:
    role: str  # platform | partner | tenant
    user: User | None = None
    partner_id: int | None = None
    tenant_id: int | None = None

    @property
    def is_platform(self) -> bool:
        return self.role == "platform"

    def can_see(self, t: Tenant) -> bool:
        if self.role == "platform":
            return True
        if self.role == "partner":
            return t.partner_id is not None and t.partner_id == self.partner_id
        return t.id == self.tenant_id

    def can_manage_partner(self, partner_id: int | None) -> bool:
        return self.is_platform or (self.role == "partner" and partner_id == self.partner_id)


def access_problem(db: Session, u: User) -> str | None:
    """Hvorfor brugeren ikke må logge ind lige nu, eller None."""
    if not u.active:
        return "Din bruger er slået fra. Kontakt den, der har inviteret dig."
    if u.role == "tenant":
        t = db.get(Tenant, u.tenant_id) if u.tenant_id else None
        if t is None:
            return "Firmaet findes ikke længere."
        if not t.self_service:
            return f"Selvbetjening er ikke slået til for {t.name}. Kontakt din leverandør."
    elif u.role == "partner":
        p = db.get(Partner, u.partner_id) if u.partner_id else None
        if p is None or not p.active:
            return "Jeres partneraftale er ikke aktiv. Kontakt din leverandør."
    else:
        return "Ukendt rolle"
    return None


def session_platform() -> str:
    return _session.sign(b"p").decode()


def session_user(u: User) -> str:
    return _session.sign(f"u:{u.id}:{u.token_version}".encode()).decode()


def current(request: Request, db: Session = Depends(get_db)) -> Principal:
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, "Log ind")
    try:
        value = _session.unsign(token, max_age=MAX_AGE).decode()
    except (BadSignature, SignatureExpired):
        raise HTTPException(401, "Log ind igen")
    if value in ("p", "admin"):  # "admin" = cookies fra før brugerne blev indført
        return Principal("platform")
    try:
        _, uid, version = value.split(":")
        u = db.get(User, int(uid))
    except ValueError:
        raise HTTPException(401, "Log ind igen")
    if u is None or u.token_version != int(version):
        raise HTTPException(401, "Log ind igen")
    problem = access_problem(db, u)
    if problem:
        raise HTTPException(403, problem)
    return Principal(u.role, u, u.partner_id, u.tenant_id)


def require_platform(p: Principal = Depends(current)) -> Principal:
    if not p.is_platform:
        raise HTTPException(403, "Det kan kun din leverandør gøre")
    return p


# ---------- invitation and reset links ----------

def invite_token(u: User) -> str:
    return _invite.sign(f"{u.id}:{u.token_version}".encode()).decode()


def user_from_invite(db: Session, token: str) -> User:
    try:
        uid, version = _invite.unsign(token, max_age=INVITE_MAX_AGE).decode().split(":")
        u = db.get(User, int(uid))
    except (BadSignature, SignatureExpired, ValueError):
        u = None
    else:
        if u is not None and u.token_version != int(version):
            u = None
    if u is None or not u.active:
        raise HTTPException(400, "Linket er udløbet eller allerede brugt. Bed om et nyt.")
    return u
