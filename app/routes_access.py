"""Login, admin-brugere, partnere og invitationslinks."""
import html
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import (COOKIE, MAX_AGE, Principal, access_problem, check_master_password, check_user_password,
                   current, hash_password, invite_token, require_platform, session_platform, session_user,
                   slow_down, user_from_invite)
from . import catering, ratelimit, signage
from .config import settings
from .db import get_db
from .media import delete_media
from .models import BillingAccount, EmergencyAlert, Kitchen, Partner, Room, SignageScreen, Tenant, User, utcnow
from .notify import send_email
from .routes_admin import get_tenant_for
from .schemas import (AcceptIn, ForgotIn, LoginIn, PartnerIn, PartnerUpdate, UserIn, partner_out, user_out)

log = logging.getLogger("gaestereg.access")

public = APIRouter(prefix="/api/admin", tags=["adgang"])
router = APIRouter(prefix="/api/admin", tags=["adgang"], dependencies=[Depends(current)])

PRODUCT = "Nodd"


def _set_cookie(response: Response, value: str) -> None:
    response.set_cookie(COOKIE, value, max_age=MAX_AGE, httponly=True, samesite="lax",
                        secure=settings.env in ("dev", "prod"))


def can_email() -> bool:
    return settings.notify_mode == "live" and settings.smtp_configured


# ---------- session ----------

# Højst 10 forkerte logins pr. IP og 5 pr. e-mail på 15 minutter.
LOGIN_IP_LIMIT, LOGIN_EMAIL_LIMIT, LOGIN_WINDOW = 10, 5, 15 * 60


def _ip(request: Request) -> str:
    return request.client.host if request.client else "?"


@public.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    ip_key, email_key = "login-ip:" + _ip(request), "login-mail:" + (email or "platform")
    ratelimit.check(ip_key, LOGIN_IP_LIMIT, LOGIN_WINDOW)
    ratelimit.check(email_key, LOGIN_EMAIL_LIMIT, LOGIN_WINDOW)

    def failed(msg: str):
        ratelimit.hit(ip_key)
        ratelimit.hit(email_key)
        slow_down()
        raise HTTPException(401, msg)

    if not email:
        if not settings.admin_password_effective:
            raise HTTPException(503, "ADMIN_PASSWORD er ikke sat på serveren")
        if not check_master_password(body.password):
            failed("Forkert adgangskode")
        ratelimit.clear(email_key)
        _set_cookie(response, session_platform())
        return {"ok": True}

    u = db.scalar(select(User).where(func.lower(User.email) == email))
    if not check_user_password(u, body.password):
        failed("Forkert e-mail eller adgangskode")
    ratelimit.clear(email_key)
    problem = access_problem(db, u)
    if problem:
        raise HTTPException(403, problem)
    u.last_login_at = utcnow()
    db.commit()
    _set_cookie(response, session_user(u))
    return {"ok": True}


@public.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE)
    return {"ok": True}


@router.get("/status")
def status():
    return {
        "env": settings.env,
        "notify_mode": settings.notify_mode,
        "sms_configured": settings.sms_configured,
        "smtp_configured": settings.smtp_configured,
        "default_password": not settings.admin_password,
    }


@router.get("/me")
def me(db: Session = Depends(get_db), p: Principal = Depends(current)):
    partner = db.get(Partner, p.partner_id) if p.partner_id else None
    return {
        "role": p.role,
        "name": p.user.name if p.user else "Platform-admin",
        "email": p.user.email if p.user else "",
        "partner": {"id": partner.id, "name": partner.name} if partner else None,
        "tenant_id": p.tenant_id,
        "can": {
            "create_tenant": p.role in ("platform", "partner"),
            "delete_tenant": p.is_platform,
            "subscription": p.is_platform,
            "partners": p.is_platform,
            "toggle_active": p.role in ("platform", "partner"),
            "import_companies": p.role in ("platform", "partner"),
        },
    }


# ---------- invitations ----------

def _invite_url(request: Request, u: User) -> str:
    # Token i #-delen, så den ikke havner i serverlogs.
    return f"{str(request.base_url).rstrip('/')}/admin#invite={invite_token(u)}"


def link_email(u: User, url: str, kind: str) -> tuple[str, str, str]:
    """Emne, tekst og HTML til en invitation eller et link til ny adgangskode."""
    hello = f"Hej {u.name}" if u.name else "Hej"
    if kind == "invite":
        subject = f"Du er inviteret til {PRODUCT}"
        lead = f"Du er inviteret som administrator i {PRODUCT}. Vælg din adgangskode for at komme i gang."
        button = "Vælg adgangskode"
        after = "Linket virker i 7 dage og kun én gang. Bagefter logger du ind med din e-mail og adgangskoden."
    else:
        subject = f"Ny adgangskode til {PRODUCT}"
        lead = "Du har bedt om en ny adgangskode. Vælg den her."
        button = "Vælg ny adgangskode"
        after = "Linket virker i 7 dage og kun én gang. Har du ikke bedt om det, kan du se bort fra denne e-mail."
    text = f"{hello}\n\n{lead}\n\n{url}\n\n{after}\n\n{PRODUCT}"
    base = url.split("/admin", 1)[0]
    e = html.escape
    page = f"""<!doctype html><html lang="da"><body style="margin:0;padding:24px 12px;background:#f4f2ea;font-family:Helvetica,Arial,sans-serif;color:#16191d">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:520px;background:#ffffff;border-radius:16px">
<tr><td style="padding:28px 28px 8px"><img src="{e(base)}/static/brand/nodd-lockup.png" width="160" height="45" alt="{PRODUCT}" style="display:block;border:0"></td></tr>
<tr><td style="padding:12px 28px 0;font-size:16px;line-height:1.55"><p style="margin:0 0 12px">{e(hello)}</p><p style="margin:0 0 22px">{e(lead)}</p>
<a href="{e(url)}" style="display:inline-block;background:#12352e;color:#ffffff;text-decoration:none;font-weight:700;padding:12px 22px;border-radius:999px">{e(button)}</a>
<p style="margin:22px 0 0;font-size:13px;color:#5b616b">{e(after)}</p>
<p style="margin:14px 0 0;font-size:12px;color:#5b616b;word-break:break-all">Virker knappen ikke, så kopiér linket: {e(url)}</p></td></tr>
<tr><td style="padding:24px 28px 28px;font-size:12px;color:#5b616b">{PRODUCT}</td></tr>
</table></td></tr></table></body></html>"""
    return subject, text, page


def _send_link(u: User, url: str, kind: str) -> None:
    subject, text, page = link_email(u, url, kind)
    try:
        send_email(u.email, subject, text, PRODUCT, html=page)
    except Exception as e:  # noqa: BLE001
        log.warning("Kunne ikke sende %s til %s: %s", kind, u.email, e)


def _new_link(request: Request, bg: BackgroundTasks, db: Session, u: User, kind: str = "invite") -> dict:
    """Gør gamle links og sessioner ugyldige og laver et nyt link. Sendes på e-mail, hvis det er sat op."""
    u.token_version += 1
    db.commit()
    url = _invite_url(request, u)
    emailed = can_email()
    if emailed:
        bg.add_task(_send_link, u, url, kind)
    return {"user": user_out(u), "invite_url": url, "emailed": emailed}


@public.get("/invite/{token}")
def invite_info(token: str, db: Session = Depends(get_db)):
    u = user_from_invite(db, token)
    return {"email": u.email, "name": u.name, "new": not u.password_hash}


@public.post("/invite/accept")
def accept_invite(body: AcceptIn, response: Response, db: Session = Depends(get_db)):
    u = user_from_invite(db, body.token)
    u.password_hash = hash_password(body.password)
    u.token_version += 1  # linket kan kun bruges én gang
    u.last_login_at = utcnow()
    db.commit()
    problem = access_problem(db, u)
    if problem:
        # Adgangskoden er gemt, men brugeren kan ikke logge ind endnu (fx selvbetjening ikke slået til).
        raise HTTPException(403, "Din adgangskode er gemt. " + problem)
    _set_cookie(response, session_user(u))
    return {"ok": True}


@public.post("/forgot")
def forgot(body: ForgotIn, request: Request, bg: BackgroundTasks, db: Session = Depends(get_db)):
    # Højst 5 pr. time pr. IP, så ingen kan bruge formularen til at sende mange mails.
    ratelimit.check("forgot:" + _ip(request), 5, 3600)
    ratelimit.hit("forgot:" + _ip(request))
    email = body.email.strip().lower()
    u = db.scalar(select(User).where(func.lower(User.email) == email)) if email else None
    if u is not None and u.active and can_email():
        _new_link(request, bg, db, u, kind="reset")
    # Samme svar uanset hvad, så man ikke kan teste, hvilke e-mails der findes.
    return {"ok": True, "message": "Hvis e-mailen har en bruger, er der sendt et link til at vælge en ny "
                                   "adgangskode. Får du ikke noget, så bed din administrator om et nyt link."}


# ---------- users ----------

def _create_user(db: Session, body: UserIn, role: str, partner_id=None, tenant_id=None) -> User:
    if db.scalar(select(User).where(func.lower(User.email) == body.email)) is not None:
        raise HTTPException(409, "Der findes allerede en bruger med den e-mail")
    u = User(email=body.email, name=body.name.strip(), role=role, partner_id=partner_id, tenant_id=tenant_id)
    db.add(u)
    db.flush()
    return u


def _user_for(db: Session, uid: int, p: Principal) -> User:
    u = db.get(User, uid)
    ok = u is not None and (
        p.is_platform
        or (u.role == "partner" and p.can_manage_partner(u.partner_id))
        or (u.role == "tenant" and p.can_see(db.get(Tenant, u.tenant_id)))
    )
    if not ok:
        raise HTTPException(404, "Brugeren findes ikke")
    return u


@router.get("/tenants/{tid}/users")
def tenant_users(tid: int, db: Session = Depends(get_db), p: Principal = Depends(current)):
    get_tenant_for(db, tid, p)
    users = db.scalars(select(User).where(User.tenant_id == tid).order_by(func.lower(User.email)))
    return [user_out(u) for u in users]


@router.post("/tenants/{tid}/users")
def add_tenant_user(tid: int, body: UserIn, request: Request, bg: BackgroundTasks,
                    db: Session = Depends(get_db), p: Principal = Depends(current)):
    t = get_tenant_for(db, tid, p)
    u = _create_user(db, body, "tenant", tenant_id=t.id)
    return _new_link(request, bg, db, u)


@router.post("/users/{uid}/link")
def new_user_link(uid: int, request: Request, bg: BackgroundTasks, db: Session = Depends(get_db),
                  p: Principal = Depends(current)):
    u = _user_for(db, uid, p)
    return _new_link(request, bg, db, u, kind="invite" if not u.password_hash else "reset")


@router.delete("/users/{uid}")
def delete_user(uid: int, db: Session = Depends(get_db), p: Principal = Depends(current)):
    u = _user_for(db, uid, p)
    if p.user is not None and p.user.id == u.id:
        raise HTTPException(400, "Du kan ikke fjerne dig selv")
    db.delete(u)
    db.commit()
    return {"ok": True}


# ---------- partners ----------

def _partner_for(db: Session, pid: int, p: Principal) -> Partner:
    partner = db.get(Partner, pid)
    if partner is None or not p.can_manage_partner(pid):
        raise HTTPException(404, "Partneren findes ikke")
    return partner


def _counts(db: Session, partner_ids=None) -> tuple[dict, dict]:
    """Antal firmaer og administratorer pr. partner, med to forespørgsler i alt."""
    tq = select(Tenant.partner_id, func.count()).where(Tenant.partner_id.is_not(None)).group_by(Tenant.partner_id)
    uq = select(User.partner_id, func.count()).where(User.partner_id.is_not(None)).group_by(User.partner_id)
    if partner_ids is not None:
        tq, uq = tq.where(Tenant.partner_id.in_(partner_ids)), uq.where(User.partner_id.in_(partner_ids))
    return dict(db.execute(tq).all()), dict(db.execute(uq).all())


def _partner_out(db: Session, partner: Partner) -> dict:
    tc, uc = _counts(db, [partner.id])
    return partner_out(partner, tc.get(partner.id, 0), uc.get(partner.id, 0))


@router.get("/partners")
def list_partners(db: Session = Depends(get_db), p: Principal = Depends(current)):
    q = select(Partner).order_by(func.lower(Partner.name))
    if not p.is_platform:
        if p.role != "partner":
            return []
        q = q.where(Partner.id == p.partner_id)
    partners = list(db.scalars(q))
    tc, uc = _counts(db, None if p.is_platform else [p.partner_id])
    return [partner_out(x, tc.get(x.id, 0), uc.get(x.id, 0)) for x in partners]


@router.post("/partners")
def create_partner(body: PartnerIn, db: Session = Depends(get_db), p: Principal = Depends(require_platform)):
    partner = Partner(name=body.name.strip())
    db.add(partner)
    db.commit()
    return _partner_out(db, partner)


@router.patch("/partners/{pid}")
def update_partner(pid: int, body: PartnerUpdate, db: Session = Depends(get_db),
                   p: Principal = Depends(current)):
    partner = _partner_for(db, pid, p)
    data = body.model_dump(exclude_unset=True)
    # Partneren må selv bestemme, hvad husets lokaleskærme viser, og hvem der får månedsrapporten.
    # Navn og aktiv er leverandørens.
    if not p.is_platform and set(data) - {"meeting_privacy", "report_email"}:
        raise HTTPException(403, "Det kan kun din leverandør gøre")
    for k, v in data.items():
        setattr(partner, k, v.strip() if isinstance(v, str) else v)
    db.commit()
    return _partner_out(db, partner)


@router.delete("/partners/{pid}")
def delete_partner(pid: int, db: Session = Depends(get_db), p: Principal = Depends(require_platform)):
    partner = _partner_for(db, pid, p)
    if db.scalar(select(func.count()).select_from(Tenant).where(Tenant.partner_id == pid)):
        raise HTTPException(409, "Partneren har stadig firmaer. Flyt eller slet dem først.")
    catering.delete_kitchens(db, db.scalars(select(Kitchen).where(Kitchen.partner_id == pid)).all())
    for room in db.scalars(select(Room).where(Room.partner_id == pid)).all():
        delete_media(room.photo_path)
        db.delete(room)  # bookinger slettes af databasen (ON DELETE CASCADE)
    db.flush()  # lokalerne først: der er ingen relationship, så SQLAlchemy kender ikke rækkefølgen
    db.query(User).filter(User.partner_id == pid).delete()
    db.query(BillingAccount).filter(BillingAccount.partner_id == pid).delete()  # pakker og fakturaer følger med
    db.query(EmergencyAlert).filter(EmergencyAlert.partner_id == pid).delete()
    for s in db.scalars(select(SignageScreen).where(SignageScreen.partner_id == pid)).all():
        for f in signage.images_of(signage.load_content(s)):
            delete_media(f)
        db.delete(s)
    db.flush()
    db.delete(partner)
    db.commit()
    return {"ok": True}


@router.get("/partners/{pid}/users")
def partner_users(pid: int, db: Session = Depends(get_db), p: Principal = Depends(current)):
    _partner_for(db, pid, p)
    users = db.scalars(select(User).where(User.partner_id == pid).order_by(func.lower(User.email)))
    return [user_out(u) for u in users]


@router.post("/partners/{pid}/users")
def add_partner_user(pid: int, body: UserIn, request: Request, bg: BackgroundTasks,
                     db: Session = Depends(get_db), p: Principal = Depends(current)):
    partner = _partner_for(db, pid, p)
    u = _create_user(db, body, "partner", partner_id=partner.id)
    return _new_link(request, bg, db, u)
