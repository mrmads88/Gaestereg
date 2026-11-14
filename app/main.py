import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from . import routes_access, routes_admin, routes_house, routes_import, routes_invite, routes_kiosk, routes_reply, routes_rooms, rooms
from . import alerts, modules, reports, routes_alerts, routes_billing, routes_catering, routes_reports, routes_signage
from .config import settings
from .db import SessionLocal, init_db
from .media import storage
from .models import Tenant
from .routes_kiosk import purge_old
from .seed import seed_if_empty

logging.basicConfig(level=logging.INFO)
STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    with SessionLocal() as db:
        seed_if_empty(db)
        for t in db.scalars(select(Tenant)).all():
            purge_old(db, t)
    reports.start_scheduler(SessionLocal)  # månedsrapporter den 1. kl. 07
    if not settings.admin_password_effective:
        logging.warning("ADMIN_PASSWORD er ikke sat. Admin er lukket indtil den sættes.")
    yield


app = FastAPI(title="Nodd", lifespan=lifespan, docs_url="/api/docs" if settings.env != "prod" else None,
              redoc_url=None)


@app.middleware("http")
async def _refresh_kiosk_config(request: Request, call_next):
    response = await call_next(request)
    # Alt, admin ændrer (kunde, personer, billeder, nyt link), skal straks kunne ses på skærmen.
    if request.method != "GET" and request.url.path.startswith("/api/admin/"):
        routes_kiosk.clear_config_cache()
        rooms.clear_cache()
        modules.clear_cache()
        alerts.clear_token_cache()  # et nyt skærmlink skal slås op igen
    return response


app.include_router(routes_kiosk.router)
app.include_router(routes_access.public)
app.include_router(routes_access.router)
app.include_router(routes_admin.router)
app.include_router(routes_import.router)
app.include_router(routes_reply.page)
app.include_router(routes_reply.api)
app.include_router(routes_invite.admin)
app.include_router(routes_invite.public)
app.include_router(routes_invite.pages)
app.include_router(routes_house.admin)
app.include_router(routes_house.public)
app.include_router(routes_house.pages)
app.include_router(routes_rooms.admin)
app.include_router(routes_rooms.public)
app.include_router(routes_rooms.pages)
app.include_router(routes_catering.admin)
app.include_router(routes_catering.public)
app.include_router(routes_catering.pages)
app.include_router(routes_billing.router)
app.include_router(routes_reports.admin)
app.include_router(routes_reports.pages)
app.include_router(routes_signage.admin)
app.include_router(routes_signage.public)
app.include_router(routes_signage.pages)
app.include_router(routes_alerts.admin)
app.include_router(routes_alerts.public)
app.mount("/static", StaticFiles(directory=STATIC), name="static")

_MEDIA_NAME = re.compile(r"^[0-9a-f]{32}\.(png|jpg|svg)$")


@app.get("/media/{name}", include_in_schema=False)
def media(name: str):
    if not _MEDIA_NAME.match(name):
        raise HTTPException(404)
    if not storage.exists(name):
        raise HTTPException(404)
    return FileResponse(storage.path(name), headers={
        "Cache-Control": "public, max-age=31536000, immutable",
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:",
        "X-Content-Type-Options": "nosniff",
    })


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/admin")


@app.get("/admin", include_in_schema=False)
def admin_page():
    return FileResponse(STATIC / "admin.html", headers={"Cache-Control": "no-cache"})


@app.get("/k/{token}", include_in_schema=False)
def kiosk_page(token: str):
    return FileResponse(STATIC / "kiosk.html", headers={"Cache-Control": "no-cache"})


@app.get("/healthz", include_in_schema=False)
def health():
    return {"ok": True, "env": settings.env}
