#!/usr/bin/env bash
# Opretter (eller opdaterer) et miljø i Azure og forbinder det til GitHub.
#
#   ./infra/opret-miljo.sh dev     # gratis testserver + gratis database i Sweden Central
#   ./infra/opret-miljo.sh prod    # senere
#
# Køres i Azure Cloud Shell (Bash), hvor az og gh er installeret, eller lokalt efter `az login`.
# Kan køres igen: data, admin-adgangskode og SECRET_KEY bevares. SQL-adgangskoden skiftes hver gang.
#
# Kan ændres med miljøvariabler, fx:  APP_SKU=B1 LOC=northeurope ./infra/opret-miljo.sh prod
set -euo pipefail

MILJO="${1:-dev}"
case "$MILJO" in dev|prod) ;; *) echo "Brug: $0 dev|prod" >&2; exit 1 ;; esac

LOC="${LOC:-swedencentral}"
RG="${RG:-rg-gaestereg-$MILJO}"
APP_SKU="${APP_SKU:-F1}"          # F1 = gratis. B1 til prod, når der er rigtige kunder.
FREE_SQL="${FREE_SQL:-true}"      # Azure SQL free offer
GITHUB_REPO="${GITHUB_REPO:-mrmads88/gaestereg}"
GH_ENV=$([ "$MILJO" = prod ] && echo production || echo dev)

SUB_ID="$(az account show --query id -o tsv)"
# Navne skal være unikke i hele Azure. Et fast suffiks ud fra abonnementet giver de samme navne hver gang.
SUFFIX="$(printf %s "$SUB_ID" | sha1sum | cut -c1-6)"
APP="${APP:-gaestereg-$MILJO-$SUFFIX}"
SQL="${SQL:-sql-gaestereg-$MILJO-$SUFFIX}"

echo "Abonnement: $(az account show --query name -o tsv) ($SUB_ID)"
echo "Miljø: $MILJO   Region: $LOC   Ressourcegruppe: $RG"
echo "Web-app: $APP ($APP_SKU)   SQL-server: $SQL (gratis: $FREE_SQL)"
echo

az provider register --namespace Microsoft.Web -o none
az provider register --namespace Microsoft.Sql -o none
# Findes ressourcegruppen allerede (fx oprettet i portalen), bruges den, uanset hvilken region den står i.
# Gruppens region er kun metadata. Selve ressourcerne lægges i $LOC.
if az group show -n "$RG" -o none 2>/dev/null; then
  echo "Bruger den eksisterende ressourcegruppe $RG."
else
  az group create -n "$RG" -l "$LOC" --tags app=gaestereg miljo="$MILJO" -o none
fi

# Genbrug adgangskode og nøgle, hvis appen findes i forvejen.
eksisterende() {
  az webapp config appsettings list -g "$RG" -n "$APP" --query "[?name=='$1'].value | [0]" -o tsv 2>/dev/null || true
}
tilfaeldig() { openssl rand -base64 96 | tr -dc 'A-Za-z0-9' | head -c "$1"; }

ADMIN_PASSWORD="$(eksisterende ADMIN_PASSWORD)"
NY_ADMIN=false
if [ -z "$ADMIN_PASSWORD" ]; then ADMIN_PASSWORD="$(tilfaeldig 20)"; NY_ADMIN=true; fi
SECRET_KEY="$(eksisterende SECRET_KEY)"
[ -n "$SECRET_KEY" ] || SECRET_KEY="$(tilfaeldig 64)"
# Store og små bogstaver, tal og tegn, så Azure SQL's krav til adgangskoder altid er opfyldt.
SQL_PASSWORD="$(tilfaeldig 28)Aa1-"

echo "Opretter ressourcer (tager 3-6 minutter første gang) ..."
az deployment group create -g "$RG" -n "gaestereg-$MILJO" \
  -f "$(dirname "$0")/main.bicep" \
  -p miljo="$MILJO" location="$LOC" appName="$APP" sqlServerName="$SQL" appSku="$APP_SKU" freeSql="$FREE_SQL" \
     sqlAdminPassword="$SQL_PASSWORD" \
  -o none

SQL_FQDN="$(az sql server show -g "$RG" -n "$SQL" --query fullyQualifiedDomainName -o tsv)"
DB="gaestereg-$MILJO"
# Adgangskoden består kun af bogstaver, tal og '-', så den kan stå direkte i URL'en.
DATABASE_URL="mssql+pyodbc://gaestereg_admin:$SQL_PASSWORD@$SQL_FQDN:1433/$DB?driver=ODBC+Driver+18+for+SQL+Server&Encrypt=yes&TrustServerCertificate=no&Connection+Timeout=30"

echo "Sætter app-indstillinger ..."
# "set" fletter: indstillinger, du selv har tilføjet (fx GATEWAYAPI_TOKEN og SMTP_*), bliver stående.
if [ "$MILJO" = prod ]; then NOTIFY_MODE=live; SEED_DEMO=false; else NOTIFY_MODE=test; SEED_DEMO=true; fi
[ -n "$(eksisterende NOTIFY_MODE)" ] && NOTIFY_MODE="$(eksisterende NOTIFY_MODE)"   # bevar dit eget valg
az webapp config appsettings set -g "$RG" -n "$APP" -o none --settings \
  APP_ENV="$MILJO" DATA_DIR=/home/data DATABASE_URL="$DATABASE_URL" \
  NOTIFY_MODE="$NOTIFY_MODE" SEED_DEMO="$SEED_DEMO" \
  ADMIN_PASSWORD="$ADMIN_PASSWORD" SECRET_KEY="$SECRET_KEY" \
  SCM_DO_BUILD_DURING_DEPLOYMENT=true

URL="https://$(az webapp show -g "$RG" -n "$APP" --query defaultHostName -o tsv)"

# Forbind GitHub: miljø, publish profile og app-navn. Kræver `gh auth login` (er klar i Cloud Shell).
PROFIL="$(mktemp)"
trap 'rm -f "$PROFIL"' EXIT
az webapp deployment list-publishing-profiles -g "$RG" -n "$APP" --xml > "$PROFIL"

GITHUB_OK=false
if command -v gh >/dev/null && gh auth status >/dev/null 2>&1; then
  echo "Forbinder GitHub-miljøet '$GH_ENV' i $GITHUB_REPO ..."
  BRANCH=$([ "$MILJO" = prod ] && echo production || echo main)
  gh api -X PUT "repos/$GITHUB_REPO/environments/$GH_ENV" --silent \
     -F "deployment_branch_policy[protected_branches]=false" -F "deployment_branch_policy[custom_branch_policies]=true"
  gh api -X POST "repos/$GITHUB_REPO/environments/$GH_ENV/deployment-branch-policies" --silent \
     -f name="$BRANCH" -f type=branch 2>/dev/null || true   # findes allerede
  gh secret set AZURE_WEBAPP_PUBLISH_PROFILE --repo "$GITHUB_REPO" --env "$GH_ENV" < "$PROFIL"
  gh variable set AZURE_WEBAPP_NAME --repo "$GITHUB_REPO" --env "$GH_ENV" --body "$APP"
  GITHUB_OK=true
fi

cat <<EOF

Færdig.

  Adresse:      $URL
  Admin:        $URL/admin
  Demo-skærm:   $URL/k/demo      (når koden er udrullet)
EOF
if $NY_ADMIN; then
  echo "  Admin-kode:   $ADMIN_PASSWORD   <- gem den i din adgangskodemanager nu"
else
  echo "  Admin-kode:   uændret (se den under App Service > Environment variables > ADMIN_PASSWORD)"
fi
echo
if $GITHUB_OK; then
  echo "GitHub-miljøet '$GH_ENV' er sat op. Udrul ved at pushe til $([ "$MILJO" = prod ] && echo production || echo main),"
  echo "eller kør workflowet 'Test og udrul' igen under Actions."
else
  echo "GitHub CLI er ikke logget ind, så GitHub skal sættes op i hånden (se docs/azure.md, trin 3):"
  echo "  Miljø '$GH_ENV' > secret AZURE_WEBAPP_PUBLISH_PROFILE = indholdet herunder"
  echo "  Miljø '$GH_ENV' > variable AZURE_WEBAPP_NAME = $APP"
  echo
  cat "$PROFIL"
  echo
fi
