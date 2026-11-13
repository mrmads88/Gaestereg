"""Værtens svarside: linket i SMS'en/mailen ("Jeg kommer om 5 min")."""
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from . import replies
from .db import get_db
from .media import media_url
from .models import Tenant, Visit, utcnow
from .notify import _group, escalate, join_names
from .schemas import ReplyIn
from .timeutil import local_hhmm

STATIC = Path(__file__).parent / "static"
page = APIRouter(include_in_schema=False)
api = APIRouter(prefix="/api/reply", tags=["svar"])


@page.get("/r/{token}")
def reply_page(token: str):
    return FileResponse(STATIC / "reply.html", headers={"Cache-Control": "no-cache"})


def _visit(db: Session, token: str) -> Visit:
    vid = replies.visit_from_token(token)
    v = db.get(Visit, vid) if vid else None
    if v is None:
        raise HTTPException(404, "Linket er udløbet. Gæsten er måske allerede gået.")
    return v


def _info(db: Session, v: Visit) -> dict:
    t = db.get(Tenant, v.tenant_id)
    return {"tenant": t.name, "color": t.color, "logo_url": media_url(t.logo_path),
            "guests": join_names([x.guest_name for x in _group(db, v)]) or "En gæst",
            "company": v.guest_company, "host": v.host_name.split(" ")[0], "time": local_hhmm(v.checked_in_at),
            "answer": v.host_reply or None, "answer_text": replies.ANSWERS.get(v.host_reply),
            "checked_out": v.checked_out_at is not None, "answers": replies.ANSWERS}


@api.get("/{token}")
def reply_info(token: str, db: Session = Depends(get_db)):
    return _info(db, _visit(db, token))


@api.post("/{token}")
def reply(token: str, body: ReplyIn, bg: BackgroundTasks, db: Session = Depends(get_db)):
    v = _visit(db, token)
    v.host_reply = body.answer
    v.host_reply_at = utcnow()
    db.commit()
    replies.record(v.id, body.answer)
    if body.answer == "reception":
        bg.add_task(escalate, v.id, True)
    return _info(db, v)
