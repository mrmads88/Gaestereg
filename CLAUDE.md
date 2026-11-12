# CLAUDE.md

White-label gæsteregistrering til receptioner. Mads sælger løsningen til kunder og partnere, der får deres eget logo, farver og personer. Første del af en større platform (POS, booking, kantine).

## Kommandoer

- Installer: `pip install -r requirements-dev.txt`
- Kør: `python -m uvicorn app.main:app --reload --port 8000`
- Test: `python -m pytest -q` (skal være grøn før commit)
- Syntakstjek af frontend: `node --check app/static/kiosk.js && node --check app/static/admin.js`

## Branches og miljøer

- `main` udrulles til Azure **dev** (NOTIFY_MODE=test).
- `production` udrulles til Azure **prod** (NOTIFY_MODE=live). Kun via PR fra `main`.
- Lav feature-branches fra `main`. Commit eller push aldrig direkte til `production`.
- Workflow: `.github/workflows/deploy.yml`. Azure-opsætning: `docs/azure.md`.

## Arkitektur

- FastAPI + SQLAlchemy 2 + SQLite (`DATA_DIR/app.db`). Tabeller oprettes med `create_all` ved start. Tilføjes kolonner til en eksisterende tabel, skal der en migration til (indfør Alembic, før første ændring af et eksisterende skema i prod).
- Multi-tenant: alt hænger på `Tenant`. Skærmen identificeres kun via `Tenant.kiosk_token` i URL'en `/k/<token>`.
- Admin er én superbruger (`ADMIN_PASSWORD`) med signeret cookie. Pr.-kunde-login er ikke bygget endnu.
- Beskeder sendes som FastAPI BackgroundTasks i `notify.py`. Alle forsøg gemmes i `Notification` med status `test`/`sendt`/`fejl`.
- Frontend er vanilla JS uden build-step i `app/static/`. Kiosk og admin deler fonte (Bricolage Grotesque, Hanken Grotesk, IBM Plex Mono).

## Regler

- Personers e-mail og mobil må aldrig med i kiosk-API'et (`schemas.host_public`). Der er en test for det.
- Al brugervendt tekst er på dansk (kiosken har også engelsk i `kiosk.js` → `T.en`).
- Billeder valideres og skaleres i `media.py`. SVG med scripts afvises, og `/media` sendes med streng CSP.
- Kør tests og klik flowet igennem i browseren efter ændringer i kiosk eller admin.
