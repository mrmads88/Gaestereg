# Opsætning i Azure: dev og prod

Hvert miljø består af en App Service (Linux, Python 3.12) og en Azure SQL Database i **Sweden Central**.
GitHub udruller automatisk:

| Branch       | Miljø i GitHub | Ressourcegruppe    | App Service-plan | Database             | NOTIFY_MODE |
|--------------|----------------|--------------------|------------------|----------------------|-------------|
| `main`       | `dev`          | `rg_gaestereg_app_dev`  | F1 (gratis)      | Azure SQL, gratis    | `test`      |
| `production` | `production`   | `rg_gaestereg_app_prod` | B1               | se "Go-live" herunder | `live`      |

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
RG=rg_gaestereg_app_dev ./infra/opret-miljo.sh dev
RG=rg_gaestereg_app_prod ./infra/opret-miljo.sh prod
```

Ressourcegrupperne er oprettet i portalen (Denmark East). Gruppens region er kun metadata, så ressourcerne lægges stadig i Sweden Central. Uden `RG=` opretter scriptet selv `rg-gaestereg-<miljø>`.

Scriptet:

1. Bruger (eller opretter) ressourcegruppen og lægger i Sweden Central en F1-plan, web-app, SQL-server og en gratis database.
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

Logs: **App Service > Log stream** i portalen eller `az webapp log tail -g rg_gaestereg_app_dev -n <app>`.

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

## Go-live af prod

Prod kører i dag den første version. Første udrulning af den nye kode opgraderer databasen automatisk (den markeres som
revision `0001` og opgraderes til den nyeste). Følg trinene i rækkefølge.

### 0. Det skal du have klar

- Domænet (fx `getnodd.dk`) med adgang til DNS.
- En konto hos GatewayAPI og en API-nøgle (SMS).
- En mailafsender, fx en Microsoft 365-postkasse `noreply@getnodd.dk`, med SPF og DKIM på domænet (ellers lander mails i spam).
- Databehandleraftalen (`app/texts/databehandleraftale.html`) gennemgået af en jurist.
- Dine firmaoplysninger: navn, CVR, adresse og kontaktmail.

### 1. Generalprøve på en kopi af prod-databasen

Portalen: **SQL databases > gaestereg-prod > Copy**. Kør så opgraderingen mod kopien (aldrig mod selve prod):

```bash
python tools/prod_generalproeve.py --url "mssql+pyodbc://<bruger>:<kode>@<server>:1433/<kopi>?driver=ODBC+Driver+18+for+SQL+Server&Encrypt=yes"
```

Den skal slutte med `GENERALPRØVEN BESTÅET`. Slet kopien bagefter. (Den er også kørt på en database lavet af den gamle
prod-kode, både SQLite og SQL Server, med `--old-code`.)

### 2. Opgradér ressourcerne

```bash
APP_SKU=B1 FREE_SQL=false RG=rg_gaestereg_app_prod ./infra/opret-miljo.sh prod
```

- **B1** (ca. 100 kr./md.): Always On (skærme og månedsmail virker hele døgnet), health check og eget domæne med SSL.
- **Betalt serverless SQL** (`FREE_SQL=false`): den gratis database rækker kun til ca. en uge med rigtige kunder.
  Den sover stadig om natten. Regn med nogle hundrede kroner om måneden, og tjek Azure-prisberegneren.
- **Billeder i Blob Storage** er standard i prod (`BLOB=true`, få kroner om måneden). Scriptet opretter lagerkontoen og
  sætter `AZURE_STORAGE_CONNECTION_STRING`.

### 3. App-indstillinger

```bash
az webapp config appsettings set -g rg_gaestereg_app_prod -n <prod-app> --settings \
  GATEWAYAPI_TOKEN='<token>' \
  SMTP_HOST=smtp.office365.com SMTP_PORT=587 SMTP_USER='<bruger>' SMTP_PASSWORD='<kode>' SMTP_FROM='noreply@getnodd.dk' \
  PUBLIC_URL='https://getnodd.dk' OPS_EMAIL='<din mail>' \
  OPERATOR_NAME='<firmanavn>' OPERATOR_CVR='<cvr>' OPERATOR_ADDRESS='<adresse>' OPERATOR_EMAIL='<kontaktmail>'
```

Når juristen har godkendt databehandleraftalen, så sæt `DPA_FINAL=1`. Så skal kunderne acceptere den endelige version
ved næste login. Indstillingerne bliver stående, hvis opsætningsscriptet køres igen.

| Indstilling | Bruges til |
|---|---|
| `GATEWAYAPI_TOKEN` | SMS til værter, gæstekoder, køkken og nødbesked |
| `SMTP_*` | Mail til værter, invitationer, månedsrapport, nødbesked og fejlmails |
| `PUBLIC_URL` | Links i mails (ellers bruges `*.azurewebsites.net`) |
| `OPS_EMAIL` | Fejlmails til dig (højst én pr. slags fejl pr. 15 min. og 20 om dagen) |
| `OPERATOR_*` | Leverandøren i databehandleraftalen og på gæsternes privatlivsside |
| `DPA_FINAL` | `1`, når databehandleraftalen er juridisk godkendt |
| `AZURE_STORAGE_CONNECTION_STRING` | Sættes af scriptet (billeder i Blob) |
| `REPORT_SCHEDULER` | Månedsrapporter den 1. kl. 7 (standard til) |

### 4. Eget domæne med SSL

1. DNS: `www` som CNAME til `<prod-app>.azurewebsites.net`, og en TXT-post `asuid` med appens verifikations-id
   (Portalen: **App Service > Custom domains > Add custom domain** viser begge dele).
2. Tilføj domænet og et gratis certifikat i samme vindue (App Service Managed Certificate).
3. Sæt `PUBLIC_URL` til domænet (trin 3).

### 5. GitHub: beskyt prod og slå oppetidstjek til

- **Settings > Environments > production > Required reviewers**: tilføj dig selv, så hver prod-udrulning skal godkendes.
- **Settings > Branches > Add rule** for `production`: "Require a pull request before merging". Så kan der kun
  komme kode i prod via en PR fra `main`.
- **Settings > Secrets and variables > Actions > Variables**: `PROD_URL = https://getnodd.dk`. Så tjekker workflowet
  `Oppetid` prod hver time (også databasen), og GitHub mailer dig, hvis det fejler. Tjek at
  **Settings (din profil) > Notifications > Actions** står til mail.

### 6. Udrul

Opret en PR fra `main` til `production`, merge den, og godkend udrulningen under Actions. Første start tager et par
minutter, fordi databasen opgraderes.

### 7. Efter udrulningen

1. Kopiér de billeder, prod har i forvejen, op i Blob: knappen **Kopiér gamle billeder til Blob** under
   **Fakturering > Klar til prod** i admin. Den kan køres igen uden skade.
2. Log ind i admin og åbn **Fakturering**: kortet **Klar til prod** skal vise "Alt er klar".
3. Lav en rigtig check-in på en skærm og se, at værten får SMS og mail.
4. Åbn `https://getnodd.dk/healthz?db=1`. Den skal svare `"db": "ok"`.

## Eget domæne pr. kunde (senere, kræver B1)

Én installation kan servere alle kunder. Hver kundes skærm bruger sit eget link `/k/<kode>`.
Vil en partner have sit eget domæne, peg et CNAME på prod-appen og tilføj domænet:
`az webapp config hostname add -g rg_gaestereg_app_prod --webapp-name <prod-app> --hostname kiosk.partner.dk`

## Slet et miljø

```bash
az group delete -n rg_gaestereg_app_dev
```

Sletter app, database og billeder. Kan ikke fortrydes.
