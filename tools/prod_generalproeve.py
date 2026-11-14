"""Generalprøve på prod-opgraderingen.

Prod kører den første version (fra før Alembic, tabeller lavet med create_all). Ved første udrulning af den nye kode
markeres databasen som revision 0001 og opgraderes til den nyeste. Dette script prøver præcis det:

  1. (valgfrit) Den gamle kode laver en database med data, som prod har i dag (--old-code <mappe med gammel checkout>).
  2. Den nye kode opgraderer databasen (init_db) og tjekker, at
     - skemaet bagefter passer præcis til modellerne,
     - ingen rækker er forsvundet,
     - appen svarer: login, kundeliste, skærmenes config, overblik og prislisten.

Brug (fra repoets rod, med en TOM database eller en KOPI af prod, aldrig selve prod):
  git worktree add /tmp/prodold origin/production
  python tools/prod_generalproeve.py --url "sqlite:////tmp/proeve.db" --old-code /tmp/prodold
  python tools/prod_generalproeve.py --url "mssql+pyodbc://...kopi-af-prod..."      # kun trin 2
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

TABLES = ["tenants", "hosts", "visits", "notifications"]

OLD = r'''
import json, os, sys
sys.path.insert(0, os.environ["OLD_CODE"])
from fastapi.testclient import TestClient
from app.main import app
from app.db import SessionLocal
from app.models import Tenant
with TestClient(app) as c:  # lifespan: create_all + demodata, som prod
    with SessionLocal() as db:
        t = db.query(Tenant).first()
        token, hid = t.kiosk_token, t.hosts[0].id
    for i in range(3):
        r = c.post(f"/api/kiosk/{token}/checkin", json={"host_id": hid, "guest_name": f"Gæst {i}", "guest_phone": "12345678",
                                                         "guest_company": "Prøve A/S"})
        assert r.status_code == 200, r.text
print("OK")
'''

NEW = r'''
import json, os, sys
sys.path.insert(0, os.getcwd())
from sqlalchemy import inspect, text
from app.db import engine, init_db
tables = json.loads(os.environ["COUNT_TABLES"])

def counts():
    with engine.connect() as conn:
        have = set(inspect(conn).get_table_names())
        return {t: conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar() for t in tables if t in have}

before = counts()
init_db()
after = counts()
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from app.db import Base
from app import models  # noqa
with engine.connect() as conn:
    diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata)
    if conn.dialect.name == "sqlite":
        diff = [d for d in diff if not (isinstance(d, tuple) and d[0] == "add_fk")]
    version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()

from fastapi.testclient import TestClient
from app.main import app
smoke = {}
with TestClient(app) as c:
    smoke["login"] = c.post("/api/admin/login", json={"password": os.environ["ADMIN_PASSWORD"]}).status_code
    ts = c.get("/api/admin/tenants").json()
    smoke["tenants"] = len(ts)
    smoke["kiosk"] = [c.get(f"/api/kiosk/{t['kiosk_token']}/config").status_code for t in ts]
    if ts:
        smoke["visits"] = c.get(f"/api/admin/tenants/{ts[0]['id']}/visits").status_code
        smoke["report"] = c.get(f"/api/admin/report?tenant_id={ts[0]['id']}").status_code
    smoke["products"] = len(c.get("/api/admin/billing/products").json())
print(json.dumps({"before": before, "after": after, "diff": [str(d) for d in diff], "version": version, "smoke": smoke}))
'''


def run(code: str, env: dict, cwd: str) -> str:
    r = subprocess.run([sys.executable, "-c", code], env=env, cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[-3000:])
        raise SystemExit("FEJL: " + ("den gamle kode" if "OLD_CODE" in env else "opgraderingen") + " fejlede")
    return r.stdout.strip().splitlines()[-1]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", required=True, help="DATABASE_URL til en tom database eller en kopi af prod")
    ap.add_argument("--old-code", help="mappe med den gamle prod-kode (git worktree af origin/production)")
    a = ap.parse_args()
    env = dict(os.environ, DATABASE_URL=a.url, DATA_DIR=tempfile.mkdtemp(), ADMIN_PASSWORD="generalproeve",
               SECRET_KEY="generalproeve", NOTIFY_MODE="test", REPORT_SCHEDULER="0", SEED_DEMO="1",
               COUNT_TABLES=json.dumps(TABLES))
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if a.old_code:
        print("1. Den gamle prod-kode laver databasen med demodata og 3 besøg ...")
        run(OLD, dict(env, OLD_CODE=os.path.abspath(a.old_code)), cwd=tempfile.mkdtemp())
    print("2. Den nye kode opgraderer databasen ...")
    res = json.loads(run(NEW, dict(env, SEED_DEMO="0"), cwd=root))
    ok = True
    print(f"   Revision nu: {res['version']}")
    for t, n in res["before"].items():
        m = res["after"].get(t)
        flag = "ok" if m is not None and m >= n else "FEJL"
        ok &= flag == "ok"
        print(f"   {t}: {n} før, {m} efter  {flag}")
    if res["diff"]:
        ok = False
        print("   FEJL: skemaet passer ikke til modellerne:", *res["diff"], sep="\n     ")
    else:
        print("   Skemaet passer præcis til modellerne")
    s = res["smoke"]
    smoke_ok = s["login"] == 200 and all(x == 200 for x in s["kiosk"]) and s.get("visits", 200) == 200 \
        and s.get("report", 200) == 200 and s["products"] > 0
    ok &= smoke_ok
    print(f"   Appen svarer: login {s['login']}, {s['tenants']} kunder, skærme {s['kiosk']}, besøg {s.get('visits')}, "
          f"overblik {s.get('report')}, prisliste {s['products']} produkter  {'ok' if smoke_ok else 'FEJL'}")
    print("GENERALPRØVEN BESTÅET" if ok else "GENERALPRØVEN FEJLEDE")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
