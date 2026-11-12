# Opsætning i Azure: dev og prod

Hvert miljø består af en App Service (Linux, Python 3.12) og en Azure SQL Database i **Sweden Central**.
GitHub udruller automatisk:

| Branch       | Miljø i GitHub | Ressourcegruppe    | App Service-plan | Database             | NOTIFY_MODE |
|--------------|----------------|--------------------|------------------|----------------------|-------------|
| `main`       | `dev`          | `rg-gaestereg-dev`  | F1 (gratis)      | Azure SQL, gratis    | `test`      |
| `production` | `production`   | `rg-gaestereg-prod` | B1 (senere)      | se "Prod" herunder   | `live`      |

Lige nu sættes kun **dev** op. Det koster 0 kr.

Infrastrukturen er beskrevet i [`infra/main.bicep`](../infra/main.bicep). Scriptet [`infra/opret-miljo.sh`](../infra/opret-miljo.sh)
opretter det hele, sætter app-indstillingerne og forbinder GitHub.

## Hvad er gratis, og hvor går grænsen

**App Service F1 (Free)**
- 60 CPU-minutter pr. dag, 1 GB disk, 1 GB RAM. Rigeligt til test.
- Ingen "Always On": appen går i dvale efter ca. 20 minutter uden trafik. Første besøg derefter tager 10-30 sekunder.
- Ingen health check og ingen eget domæne med SSL. Det kræver B1.

**Azure SQL Database, free offer**
- 100.000 vCore-sekunder og 32 GB lagerplads pr. måned. Op til 10 gratis databaser pr. abonnement.
- Databasen går på pause efter 60 minutter uden forespørgsler og vågner ved næste forespørgsel (typisk under et minut). Appen venter selv, mens den vågner (`app/db.py`).
- Med 0,5 vCore svarer 100.000 vCore-sekunder til ca. **55 timer, hvor databasen er vågen, pr. måned**.
- Er det gratis forbrug brugt, går databasen på pause til den 1. i næste måned. Den koster aldrig noget, men dev virker ikke, før den nye måned starter.
- Kiosk-skærmens opsætning gemmes i hukommelsen (`KIOSK_CACHE_SECONDS`, standard 24 timer). Derfor holder en skærm, der står tændt, ikke databasen vågen. Kun check-ind, tjek ud og admin rammer databasen.

Billeder (logoer, baggrunde, profilbilleder) ligger stadig som filer i `/home/data/media` på App Service. `/home` overlever genstart og ny udrulning.

## 1. Opret dev (én gang)

Det nemmeste er **Azure Cloud Shell** (ikonet `>_` øverst i portal.azure.com, vælg **Bash**). Her er `az`, `gh` og `git` installeret, og du er logget ind.

```bash
git clone https://github.com/mrmads88/gaestereg.git
cd gaestereg
gh auth login          # vælg GitHub.com > HTTPS > Login with a web browser. Så kan scriptet sætte GitHub op.
./infra/opret-miljo.sh dev
```

Scriptet:

1. Opretter `rg-gaestereg-dev` i Sweden Central med en F1-plan, web-app, SQL-server og en gratis database.
2. Sætter app-indstillingerne (`DATABASE_URL`, `ADMIN_PASSWORD`, `SECRET_KEY` med flere). Adgangskoder genereres.
3. Opretter GitHub-miljøet `dev`, som kun `main` kan udrulle til, med secret `AZURE_WEBAPP_PUBLISH_PROFILE` og variable `AZURE_WEBAPP_NAME`.
4. Skriver adressen og admin-koden ud. **Gem admin-koden.**

Har du flere abonnementer, så vælg først det rigtige: `az account set --subscription "<navn>"`.

Navnene får et fast suffiks ud fra dit abonnement (fx `gaestereg-dev-97d22f`), fordi de skal være unikke i hele Azure.

Scriptet kan køres igen. Data, admin-kode og `SECRET_KEY` bevares, og indstillinger, du selv har tilføjet, bliver stående. SQL-adgangskoden skiftes hver gang.

### Hvis noget driller

- **F1 ikke tilgængelig i regionen**: kør `LOC=northeurope ./infra/opret-miljo.sh dev`.
- **"The free offer is already used"** eller lignende: abonnementet har allerede 10 gratis databaser. Slet en, eller kør med `FREE_SQL=false` (betalt serverless: ca. 2 kr. pr. time, databasen er vågen, plus lagerplads).
- **gh ikke logget ind**: scriptet skriver publish profilen ud. Sæt GitHub op i hånden som beskrevet under trin 3.

## 2. Udrul koden

Push til `main`, eller kør workflowet **Test og udrul** under **Actions** igen (Re-run). Første udrulning tager et par minutter, fordi App Service installerer pakkerne.

Åbn derefter `https://<app>.azurewebsites.net/admin` og `/k/demo`.

Logs: **App Service > Log stream** i portalen eller `az webapp log tail -g rg-gaestereg-dev -n <app>`.

## 3. GitHub i hånden (kun hvis scriptet ikke kunne)

I GitHub-repoet: **Settings → Environments**

- Opret miljøet `dev`:
  - Secret `AZURE_WEBAPP_PUBLISH_PROFILE` = hele XML'en, scriptet skrev ud
  - Variable `AZURE_WEBAPP_NAME` = navnet på web-appen
  - Deployment branches: kun `main`
- Senere `production` på samme måde med branch `production`. Slå gerne **Required reviewers** til, så du selv godkender hver prod-udrulning.

Under **Settings → Branches** kan du beskytte `production`, så der kun kan merges via pull request fra `main`.

## 4. Se data i databasen

Portalen: **SQL databases > gaestereg-dev > Query editor**. Log ind med SQL-login `gaestereg_admin` og adgangskoden fra `DATABASE_URL` (App Service > Environment variables). Tilføj din egen IP, hvis den beder om det.

Hver forespørgsel vækker databasen og bruger af det gratis forbrug.

## 5. Udrulning i hverdagen

```bash
git checkout main && git pull
git checkout -b feature/noget-nyt
# ... ret, test ...
git push -u origin feature/noget-nyt     # opret PR mod main -> tests kører på SQLite og SQL Server
# Merge PR -> main udrulles til DEV automatisk

# Når dev ser rigtigt ud:
# Opret PR fra main til production -> merge -> PROD udrulles
```

## Prod (senere)

```bash
APP_SKU=B1 ./infra/opret-miljo.sh prod
```

Herefter SMS og e-mail i prod (de bliver stående, hvis scriptet køres igen):

```bash
az webapp config appsettings set -g rg-gaestereg-prod -n <prod-app> --settings \
  GATEWAYAPI_TOKEN='<token>' \
  SMTP_HOST=smtp.office365.com SMTP_PORT=587 SMTP_USER='<bruger>' SMTP_PASSWORD='<kode>' SMTP_FROM='reception@ditdomæne.dk'
```

Overvej før prod:

- **Plan**: B1 (ca. 100 kr./md.) giver Always On, health check og eget domæne med SSL.
- **Database**: med rigtige kunder er databasen vågen det meste af arbejdsdagen, og 55 gratis timer om måneden rækker til ca. en uge. Kør prod med `FREE_SQL=false` (betalt serverless: ca. 2 kr. pr. time, den er vågen, så en arbejdsmåned bliver nogle hundrede kroner. Tjek prisen i Azure-prisberegneren), eller ændr `freeLimitExhaustionBehavior` til `BillOverUsage` i `infra/main.bicep`.
- **Skema-ændringer**: tabeller oprettes med `create_all`. Før første ændring af en eksisterende tabel i prod skal Alembic ind.

## Eget domæne pr. kunde (senere, kræver B1)

Én installation kan servere alle kunder. Hver kundes skærm bruger sit eget link `/k/<kode>`.
Vil en partner have sit eget domæne, peg et CNAME på prod-appen og tilføj domænet:
`az webapp config hostname add -g rg-gaestereg-prod --webapp-name <prod-app> --hostname kiosk.partner.dk`

## Slet et miljø

```bash
az group delete -n rg-gaestereg-dev
```

Sletter app, database og billeder. Kan ikke fortrydes.
