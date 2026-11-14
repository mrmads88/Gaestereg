# CLAUDE.md

**Nodd**: white-label gæsteregistrering til receptioner. Mads sælger løsningen til kunder og partnere, der får deres eget logo, farver og personer. Første del af en større platform (POS, booking, kantine).

## Kommandoer

- Installer: `pip install -r requirements-dev.txt`
- Kør: `python -m uvicorn app.main:app --reload --port 8000`
- Test: `python -m pytest -q` (skal være grøn før commit)
- Syntakstjek af frontend: `node --check app/static/kiosk.js && node --check app/static/admin.js`

## Branches og miljøer

- `main` udrulles til Azure **dev** (NOTIFY_MODE=test).
- `production` udrulles til Azure **prod** (NOTIFY_MODE=live). Kun via PR fra `main`.
- Lav feature-branches fra `main`. Commit eller push aldrig direkte til `production`.
- **Send altid Mads en mail (til hans egen Gmail via Gmail-værktøjet), når der er udrullet til dev eller prod**: hvad der er nyt, link til miljøet og hvad han skal teste. Send den først, når GitHub Actions-kørslen er grøn.
- Køreplan og Mads' ønsker til kommende faser (bl.a. mødelokaler, lokaleskærm og diskretion om mødetitler): `docs/roadmap.md`. Læs den, før en ny fase startes.
- Workflow: `.github/workflows/deploy.yml`. Azure-opsætning: `docs/azure.md`, `infra/main.bicep` og `infra/opret-miljo.sh` (Sweden Central, gratis F1 + Azure SQL free offer til dev).

## Arkitektur

- FastAPI + SQLAlchemy 2. Lokalt og i tests: SQLite (`DATA_DIR/app.db`). I Azure: Azure SQL via `DATABASE_URL` (`mssql+pyodbc`).
- Skemaet styres af Alembic (`app/migrations/versions`). `init_db()` kører `upgrade head` ved opstart. Databaser fra før Alembic markeres først som `0001`. Ændrer du en model, så skriv en ny migration i hånden. `tests/test_migrations.py` fejler, hvis model og migration ikke passer sammen. Nye NOT NULL-kolonner på eksisterende tabeller skal have `server_default`.
- Koden skal virke på både SQLite og SQL Server. CI kører testene på begge. Kør dem mod SQL Server lokalt med Docker (se README).
- Skærmstatus (`presence.py`) og loginbegrænsning (`ratelimit.py`) ligger i hukommelsen, så de ikke rammer databasen. Det forudsætter én worker. Kører appen på flere servere, skal de flyttes til en fælles cache.
- Værtens svar (`replies.py`, `/r/<token>`) og påmindelser ligger også i hukommelsen: svaret skrives én gang i databasen, men skærmen spørger kun hukommelsen (`/api/kiosk/<token>/reply/<id>`). Påmindelser er tråd-timere og forsvinder ved genstart.
- Besøg har `kind` (`guest` eller `delivery`). Pakker står ikke på tjek-ud-listen. Gæster, der kom sammen, har samme `group_ref` og giver én samlet besked.
- Skærmens offentlige config (`tenant_public`) må kun indeholde det, skærmen viser. Godsmodtagelsens kontakt, Teams-adressen og påmindelser bliver på serveren (der er en test).
- Invitationer (`invitations.py`, `routes_invite.py`): 6-cifret kode pr. kunde, gæstens side `/g/<token>` med QR (segno), værtens link `/i/<token>` (signeret med `Host.link_version`). Koden virker fra 36 timer før til 36 timer efter det forventede tidspunkt. `delete_tenant` skal slette invitationer før personerne.
- Husets skærm (`Tenant.house_screen`, `house.py`): et firma under en partner viser alle partnerens firmaer. Gæsten vælger firma (`firm_id`), og besøget gemmes hos firmaet med firmaets beskeder. Skærmens egne indstillinger (navn, mobil, husregler) gælder. Koder, tjek ud og "i huset" dækker alle partnerens firmaer (`tenant_ids_on_screen`).
- Mødelokaler (`rooms.py`, `routes_rooms.py`): `Room` hører til et firma eller en partner (huset). Et firma kan booke sine egne og husets lokaler. `Booking.tenant_id` har ingen FK (én kaskadevej), så `delete_tenant` sletter bookinger i koden. Værten booker via `/b/<host-token>`, lokaleskærmen er `/room/<screen_token>` og læser `rooms.screen_state` fra hukommelsen (tømmes af `rooms.clear_cache()` ved alle ændringer og af middleware i `main.py`). Diskretion: `privacy_for` (skærm → firma → hus, standard `busy`). Mødetitler må kun ses fuldt af det bookende firma og platform (der er tests).
- Forplejning (`catering.py`, `routes_catering.py`): `Kitchen` hører til et firma eller huset ligesom `Room`. `CateringOrder` (højst én pr. booking) har linjer med kopieret navn og pris (øre). `kitchen_id` og `tenant_id` har ingen FK (én kaskadevej), så `catering.delete_kitchens` rydder op og kaldes fra `delete_tenant` og `delete_partner`. Køkkenet får besked via `notify_kitchen` (BackgroundTask) og ser aldrig mødets titel. Køkkensiden `/kitchen/<order_token>` læser `catering.kitchen_day` fra hukommelsen (tømmes sammen med `rooms.clear_cache()`).
- Pakker og fakturering (`billing.py`, `routes_billing.py`, kun platform): prisliste i `products` (øre ekskl. moms), kunden er en `BillingAccount` på et firma eller et hus, tilmeldinger i `account_products`. Fakturaer forud, tilmelding midt i en periode udregnes pr. dag (`month_fraction`), SMS-forbrug bagud. Kladder laves om; `finalize` flytter `billed_through` og låser engangsposter. Moduler (`modules.py`) følger af aktive produkter (firmaets egne + husets) og caches pr. dag (tømmes af middleware). Brug `modules.tenant_has(t, "rooms")` osv., ikke egne flag.
- Admin-moduler (`admin-rooms.js`, `admin-catering.js`, `admin-billing.js`) laver en ny container ved hver mount, så klik ikke håndteres flere gange.
- Evakueringsliste `/e/<token>` (signeret med `evac_version` på kunde eller partner). Statistik i `visit_stats` (tælles op ved check-ind og pakker).
- Skærmen med `?m=1` er gæstens egen telefon (fra QR-plakaten): telefonens tastatur, intet print, tæller ikke som skærm.
- Billeder gemmes via `media.storage` (lokale filer nu). Brug den, ikke `settings.media_dir` direkte, så Blob Storage senere kun kræver en ny storage-klasse.
- Azure SQL's gratis-database går på pause. `db.py` venter, mens den vågner. Kiosk-config caches i hukommelsen (`routes_kiosk._config_cache`) og tømmes af middleware i `main.py` ved alle admin-ændringer. Ingen polling må ramme databasen.
- Billeder ligger som filer i `DATA_DIR/media` (`/home/data` i Azure).
- Multi-tenant: alt hænger på `Tenant`. Skærmen identificeres kun via `Tenant.kiosk_token` i URL'en `/k/<token>`.
- Roller (`auth.py`): platform (dig, `ADMIN_PASSWORD` uden e-mail), partner (fx kontorhotel, ser alle firmaer med samme `partner_id` og kan oprette nye) og tenant (kunde-admin, ét firma, kun når `Tenant.self_service` er slået til). Brugere logger ind med e-mail og adgangskode (scrypt). Invitation og ny adgangskode sker med et signeret link (`/admin#invite=...`), som kun virker én gang (`User.token_version`).
- Kun platform må se og rette abonnement (`/tenants/{id}/subscription`), slette firmaer og oprette partnere. Kunde-admins må ikke slå skærmen fra (`active`).
- Import (`importer.py`): Excel, CSV eller ZIP med ark og billeder. Kører i én transaktion, og forhåndsvisningen (`dry_run`) rulles tilbage.
- Beskeder sendes som FastAPI BackgroundTasks i `notify.py`. Alle forsøg gemmes i `Notification` med status `test`/`sendt`/`fejl`.
- Frontend er vanilla JS uden build-step i `app/static/`. Nodd-logoet ligger i `app/static/brand` og laves af `tools/brand.py` og `tools/brand_png.js`. Admin bruger Nodd-grøn `#12352e`, indtil en kunde vælges. Skærmen (kiosk) er white-label og viser ikke Nodd. Kiosk og admin deler fonte (Bricolage Grotesque, Hanken Grotesk, IBM Plex Mono).

## Regler

- Alle admin-endpoints skal tage `p: Principal = Depends(current)` og hente kunder med `get_tenant_for(db, tid, p)` (personer med `_host(db, hid, p)`). Det er dem, der sikrer, at man kun ser sine egne firmaer. En kunde, man ikke må se, giver 404. Skriv en test i `tests/test_access.py` for nye endpoints.
- Brug `Unicode`/`UnicodeText` (ikke `String`/`Text`) i modellerne, så det bliver NVARCHAR på SQL Server.
- SQL Server tillader kun én kaskadevej til en tabel. Nye fremmednøgler med `ondelete` skal tjekkes mod de eksisterende (fx har `visits.host_id` og `notifications.visit_id` ingen). Ryd op i koden i stedet.
- Sammenlign booleans med `== true()` (fra sqlalchemy), aldrig `.is_(True)`. SQL Server forstår ikke `IS 1`.
- Brug subqueries frem for lange `IN (...)`-lister. SQL Server tillader højst 2100 parametre.

- Personers e-mail og mobil må aldrig med i kiosk-API'et (`schemas.host_public`). Der er en test for det.
- Al brugervendt tekst er på dansk. Skærmen kan vises på flere sprog: navne og flag i `app/static/langs.js`, tekster i `kiosk.js` (`T.<kode>`) og koden i `SUPPORTED_LANGS` i `schemas.py`. Et nyt sprog skal ind alle tre steder (der er en test for det). Pr. kunde: `languages`, `lang_default` og `lang_mode` (`toggle` = flag i hjørnet, `first` = sprogvalg som første skærm, `off`). Skærmen går tilbage til standardsproget efter hver gæst.
- Billeder valideres og skaleres i `media.py`. SVG med scripts afvises, og `/media` sendes med streng CSP.
- Kør tests og klik flowet igennem i browseren efter ændringer i kiosk eller admin.
