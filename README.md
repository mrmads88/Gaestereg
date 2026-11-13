# Gæsteregistrering

Touch-skærm til receptionen, som du kan sætte op og brande pr. kunde.

- **Skærmen** (`/k/<kode>`): kundens logo og farver, personer med billede, navn og titel. Gæsten trykker på den, de skal besøge, skriver navn og mobilnummer og tjekker ind. Værten får besked på SMS, e-mail eller begge.
- **Admin** (`/admin`): opret kunder, upload logo og baggrund, tilføj personer med e-mail, mobil og flueben for SMS/e-mail, ret beskedteksterne og se besøg og sendte beskeder. Med live forhåndsvisning af skærmen.

## Kør lokalt

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env
python -m uvicorn app.main:app --reload --port 8000
```

- Admin: http://localhost:8000/admin (adgangskode `admin` lokalt)
- Demo-skærm: http://localhost:8000/k/demo
- API-dokumentation: http://localhost:8000/api/docs

Skærmtastaturet vises automatisk på touch-skærme. På en pc med mus kan du tvinge det frem med `?osk=1`.

Tests: `python -m pytest -q`

Testene bruger SQLite. I Azure kører appen på Azure SQL, og CI tester begge. Mod SQL Server lokalt (kræver Docker og [ODBC Driver 18](https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server)):

```bash
docker run -d --name mssql -e ACCEPT_EULA=Y -e 'MSSQL_SA_PASSWORD=Test_Passw0rd!' -p 1433:1433 mcr.microsoft.com/mssql/server:2022-latest
# opret databasen gaestereg_test (fx i VS Code's SQL-udvidelse), og kør så:
DATABASE_URL='mssql+pyodbc://sa:Test_Passw0rd%21@localhost:1433/gaestereg_test?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes' python -m pytest -q
```

## Roller og selvbetjening

| Rolle | Logger ind med | Kan |
|---|---|---|
| Leverandør (dig) | "Leverandør-login" og `ADMIN_PASSWORD` | Alt: kunder, partnere, abonnement, sletning |
| Partner, fx et kontorhotel | E-mail og adgangskode | Oprette og rette alle firmaer under partneren og invitere administratorer. Ikke se priser eller slette |
| Kunde-admin | E-mail og adgangskode | Rette eget firma: personer, udseende, gæsteflow, beskeder, besøg og invitere kolleger. Kræver at **Selvbetjening** er slået til under Abonnement |

Invitationer sendes på e-mail, når SMTP er sat op og `NOTIFY_MODE=live`. Ellers viser admin linket, så du kan sende det selv. Linket virker i 7 dage og kun én gang.

Under **Abonnement** (kun leverandøren) står årspris, pris for selvbetjening pr. måned, betalt-til-dato og partner. Systemet fakturerer ikke selv. Det holder styr på aftalen og markerer kunder, hvor betalingen er udløbet.

## Import fra Excel

Partnere og leverandøren kan importere mange firmaer og personer på én gang. Kunde-admins kan importere personer til deres eget firma. Hent skabelonen i admin, udfyld én række pr. person og upload. Billeder kan sættes ind i arket ud for personen eller lægges i en ZIP-fil sammen med arket. Du ser altid en forhåndsvisning, før noget gemmes. Personer findes igen på e-mail, så arket kan rettes og importeres igen.

## Sådan virker beskederne

Når en gæst tjekker ind, sendes beskeder til værten efter fluebenene:

- **SMS** via [GatewayAPI](https://gatewayapi.com) (dansk udbyder, ca. 0,25 kr pr. SMS). Afsendernavnet sættes pr. kunde (maks 11 tegn).
- **E-mail** via SMTP, fx Microsoft 365.
- Vælger gæsten "Ved ikke hvem", går beskeden til receptionens mobil og e-mail.

`NOTIFY_MODE=test` (standard) sender intet. Beskederne gemmes og kan ses under **Besøg** i admin. Sæt `NOTIFY_MODE=live` og nøglerne i `.env` for at sende rigtigt. Knappen **Send test** ved hver person sender en testbesked, så du kan vise kunden præcis hvad der ankommer.

Beskedteksterne kan rettes pr. kunde med flettefelter: `{vaert_fornavn}`, `{vaert}`, `{gaest}`, `{telefon}`, `{firma}`, `{tid}`, `{kunde}`.

## Data og privatliv

- E-mail og mobil på personerne sendes aldrig til skærmen. De bruges kun på serveren.
- Tjek ud-listen på skærmen viser kun fornavn og første bogstav i efternavnet.
- Besøg slettes automatisk efter det antal dage, der er sat pr. kunde (standard 30).
- Skærmlinket er en hemmelig kode. Lav et nyt link i admin, hvis det er kommet i forkerte hænder.

## Struktur

```
app/
  main.py           FastAPI-app, sider og billeder
  config.py         indstillinger fra miljøvariabler
  models.py         Tenant (kunde), Host (person), Visit, Notification
  routes_kiosk.py   offentligt API til skærmen
  auth.py           login, roller og invitationslinks
  routes_access.py  login, brugere og partnere
  routes_admin.py   admin-API for kunder og personer (kræver login)
  importer.py       import fra Excel, CSV og ZIP
  migrations/       Alembic-migrationer
  notify.py         SMS og e-mail
  media.py          upload og skalering af billeder
  static/           kiosk.html/.css/.js og admin.html/.css/.js
  db.py             databaseforbindelse (SQLite lokalt, Azure SQL i Azure)
tests/              pytest
infra/              Bicep og script, der opretter et miljø i Azure
docs/azure.md       opsætning af dev og prod i Azure
```

## Branches og udrulning

- `main` → udrulles automatisk til **dev** (Sweden Central, gratis App Service F1 + gratis Azure SQL)
- `production` → udrulles automatisk til **prod** (sættes op senere)

Se [docs/azure.md](docs/azure.md) for opsætning af Azure og GitHub.
