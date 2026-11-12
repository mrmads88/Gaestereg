import secrets
import time

from fastapi import HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner

from .config import settings

COOKIE = "gr_admin"
MAX_AGE = 7 * 24 * 3600
_signer = TimestampSigner(settings.secret_key, salt="admin-session")


def check_password(pw: str) -> bool:
    expected = settings.admin_password_effective
    if not expected:
        return False
    ok = secrets.compare_digest(pw.encode(), expected.encode())
    if not ok:
        time.sleep(0.6)  # slow down guessing
    return ok


def make_session() -> str:
    return _signer.sign(b"admin").decode()


def require_admin(request: Request) -> None:
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, "Log ind")
    try:
        _signer.unsign(token, max_age=MAX_AGE)
    except (BadSignature, SignatureExpired):
        raise HTTPException(401, "Log ind igen")
