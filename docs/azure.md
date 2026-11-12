# Opsætning i Azure: dev og prod

To App Services, én pr. miljø. GitHub udruller automatisk:

| Branch       | Miljø i GitHub | App Service      | NOTIFY_MODE |
|--------------|----------------|------------------|-------------|
| `main`       | `dev`          | `gaestereg-dev`  | `test`      |
| `production` | `production`   | `gaestereg-prod` | `live`      |

Navnene er forslag. App Service-navne skal være unikke i hele Azure.

## 1. Opret ressourcerne (én gang)

Kør i Azure Cloud Shell eller lokalt med `az login`:

```bash
RG=rg-gaestereg
LOC=swedencentral          # eller northeurope / westeurope
az group create -n $RG -l $LOC

# Én plan til dev (billig). Prod får sin egen, så dev aldrig kan tage kræfter fra prod.
az appservice plan create -g $RG -n plan-gaestereg-dev  --is-linux --sku B1
az appservice plan create -g $RG -n plan-gaestereg-prod --is-linux --sku B1

az webapp create -g $RG -p plan-gaestereg-dev  -n gaestereg-dev  --runtime "PYTHON:3.12"
az webapp create -g $RG -p plan-gaestereg-prod -n gaestereg-prod --runtime "PYTHON:3.12"

for APP in gaestereg-dev gaestereg-prod; do
  az webapp config set -g $RG -n $APP --startup-file "sh startup.sh" --always-on true --http20-enabled true
  az webapp update     -g $RG -n $APP --https-only true
  az webapp config set -g $RG -n $APP --generic-configurations '{"healthCheckPath": "/healthz"}'
  # Tillad udrulning med publish profile fra GitHub
  az resource update -g $RG --namespace Microsoft.Web --resource-type basicPublishingCredentialsPolicies \
     --parent sites/$APP -n scm --set properties.allow=true
done
```

## 2. Indstillinger pr. miljø

```bash
az webapp config appsettings set -g $RG -n gaestereg-dev --settings \
  APP_ENV=dev DATA_DIR=/home/data NOTIFY_MODE=test SEED_DEMO=true \
  SCM_DO_BUILD_DURING_DEPLOYMENT=true \
  ADMIN_PASSWORD='<vælg en stærk kode>' SECRET_KEY="$(openssl rand -hex 32)"

az webapp config appsettings set -g $RG -n gaestereg-prod --settings \
  APP_ENV=prod DATA_DIR=/home/data NOTIFY_MODE=live SEED_DEMO=false \
  SCM_DO_BUILD_DURING_DEPLOYMENT=true \
  ADMIN_PASSWORD='<en anden stærk kode>' SECRET_KEY="$(openssl rand -hex 32)" \
  GATEWAYAPI_TOKEN='<token>' \
  SMTP_HOST=smtp.office365.com SMTP_PORT=587 SMTP_USER='<bruger>' SMTP_PASSWORD='<kode>' SMTP_FROM='reception@ditdomæne.dk'
```

`/home` er det eneste sted i App Service, der overlever genstart og ny udrulning. Derfor ligger database og billeder i `/home/data`.

Vil du teste rigtige SMS'er på dev, så sæt `NOTIFY_MODE=live` og `GATEWAYAPI_TOKEN` på dev også.

## 3. Forbind GitHub

Hent publish profiles:

```bash
az webapp deployment list-publishing-profiles -g $RG -n gaestereg-dev  --xml > dev.publishsettings
az webapp deployment list-publishing-profiles -g $RG -n gaestereg-prod --xml > prod.publishsettings
```

I GitHub-repoet: **Settings → Environments**

- Opret miljøet `dev`:
  - Secret `AZURE_WEBAPP_PUBLISH_PROFILE` = hele indholdet af `dev.publishsettings`
  - Variable `AZURE_WEBAPP_NAME` = `gaestereg-dev`
  - Deployment branches: kun `main`
- Opret miljøet `production`:
  - Secret `AZURE_WEBAPP_PUBLISH_PROFILE` = indholdet af `prod.publishsettings`
  - Variable `AZURE_WEBAPP_NAME` = `gaestereg-prod`
  - Deployment branches: kun `production`
  - Slå gerne **Required reviewers** til, så du selv godkender hver prod-udrulning

Slet `.publishsettings`-filerne bagefter. De giver fuld adgang til at udrulle.

Under **Settings → Branches** kan du beskytte `production`, så der kun kan merges via pull request fra `main`.

## 4. Udrulning i hverdagen

```bash
# Nyt arbejde
git checkout main && git pull
git checkout -b feature/noget-nyt
# ... ret, test ...
git push -u origin feature/noget-nyt     # opret PR mod main -> tests kører
# Merge PR -> main udrulles til DEV automatisk

# Når dev ser rigtigt ud:
# Opret PR fra main til production -> merge -> PROD udrulles
```

## 5. Eget domæne pr. kunde (senere)

Én installation kan servere alle kunder. Hver kundes skærm bruger sit eget link `/k/<kode>`.
Vil en partner have sit eget domæne, peg et CNAME på prod-appen og tilføj domænet:
`az webapp config hostname add -g $RG --webapp-name gaestereg-prod --hostname kiosk.partner.dk`

## Når der kommer mange kunder

SQLite i `/home/data` er fint til start og nogle hundrede besøg om dagen. Når det vokser:
sæt `DATABASE_URL` til en Azure Database for PostgreSQL (`postgresql+psycopg://...`), tilføj `psycopg[binary]` til requirements, og flyt billeder til Azure Blob Storage.
