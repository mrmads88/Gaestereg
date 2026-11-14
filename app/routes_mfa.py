"""To-trins-login: opsætning, engangskoder og nulstilling. Se mfa.py."""
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from . import mfa
from .auth import Principal, current, session_platform, session_user
from .db import get_db
from .routes_access import _set_cookie, _user_for
from .schemas import MfaCodeIn, user_out

router = APIRouter(prefix="/api/admin", tags=["adgang"], dependencies=[Depends(current)])

WRONG = "Koden passer ikke. Tjek, at telefonens ur går rigtigt, og prøv den næste kode."


def _renew_cookie(response: Response, holder, p: Principal) -> None:
    """Efter til/fra er de andre sessioner logget ud. Denne fortsætter med en ny cookie."""
    _set_cookie(response, session_user(holder) if p.user is not None else session_platform(holder.token_version))


def _state(holder, p: Principal) -> dict:
    return {"enabled": mfa.enabled(holder), "required": mfa.required_for(p.role),
            "recovery_left": mfa.recovery_left(holder) if mfa.enabled(holder) else 0}


@router.get("/mfa")
def state(db: Session = Depends(get_db), p: Principal = Depends(current)):
    holder = mfa.holder_of(db, p)
    db.commit()
    return _state(holder, p)


@router.post("/mfa/setup")
def setup(db: Session = Depends(get_db), p: Principal = Depends(current)):
    """Ny hemmelighed og QR-kode. Bliver først aktiv, når en kode fra appen er godkendt."""
    holder = mfa.holder_of(db, p)
    if mfa.enabled(holder):
        raise HTTPException(409, "To-trins-login er allerede slået til")
    holder.mfa_secret = mfa.new_secret()
    db.commit()
    uri = mfa.otpauth_uri(holder.mfa_secret, p.user.email if p.user else "Leverandør")
    return {"secret": " ".join(holder.mfa_secret[i:i + 4] for i in range(0, len(holder.mfa_secret), 4)),
            "uri": uri, "qr": mfa.qr_svg(uri)}


@router.post("/mfa/enable")
def enable(body: MfaCodeIn, response: Response, db: Session = Depends(get_db), p: Principal = Depends(current)):
    holder = mfa.holder_of(db, p)
    if mfa.enabled(holder):
        raise HTTPException(409, "To-trins-login er allerede slået til")
    if not holder.mfa_secret:
        raise HTTPException(400, "Start opsætningen forfra")
    codes = mfa.enable(holder, body.code)
    if codes is None:
        raise HTTPException(400, WRONG)
    db.commit()
    _renew_cookie(response, holder, p)
    return {**_state(holder, p), "recovery_codes": codes}


@router.post("/mfa/disable")
def disable(body: MfaCodeIn, response: Response, db: Session = Depends(get_db), p: Principal = Depends(current)):
    holder = mfa.holder_of(db, p)
    if mfa.required_for(p.role):
        raise HTTPException(422, "To-trins-login er påkrævet for din konto og kan ikke slås fra")
    if not mfa.enabled(holder):
        return _state(holder, p)
    if not mfa.verify(holder, body.code):
        raise HTTPException(400, WRONG)
    mfa.disable(holder)
    db.commit()
    _renew_cookie(response, holder, p)
    return _state(holder, p)


@router.post("/mfa/recovery")
def new_recovery(body: MfaCodeIn, db: Session = Depends(get_db), p: Principal = Depends(current)):
    """Nye engangskoder (de gamle holder op med at virke)."""
    holder = mfa.holder_of(db, p)
    if not mfa.enabled(holder):
        raise HTTPException(400, "To-trins-login er ikke slået til")
    if not mfa.verify(holder, body.code):
        raise HTTPException(400, WRONG)
    codes = mfa.new_recovery_codes(holder)
    db.commit()
    return {**_state(holder, p), "recovery_codes": codes}


@router.post("/users/{uid}/mfa-reset")
def reset_user(uid: int, db: Session = Depends(get_db), p: Principal = Depends(current)):
    """En administrator nulstiller en anden brugers to-trins-login (mistet telefon). Brugeren logges ud og sætter
    det op igen ved næste login, hvis det er påkrævet."""
    u = _user_for(db, uid, p)
    if p.user is not None and p.user.id == u.id:
        raise HTTPException(400, "Din egen konto styrer du under Sikkerhed")
    mfa.disable(u)
    db.commit()
    return user_out(u)
