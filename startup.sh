#!/bin/sh
# Startkommando til Azure App Service (Linux, Python).
# Én worker, fordi SQLite og baggrundsopgaver (SMS/mail) kører i samme proces.
exec python -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips="*"
