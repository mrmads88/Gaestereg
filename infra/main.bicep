// Ét miljø af gæsteregistreringen: App Service (Linux, Python) + Azure SQL Database.
// Køres af infra/opret-miljo.sh, som også sætter app-indstillingerne (de flettes, så
// nøgler du selv har tilføjet, fx GATEWAYAPI_TOKEN, bliver ikke slettet). Kan køres igen uden at miste data.
//
// Standard er gratis:
//   - App Service plan F1 (Free): 60 CPU-minutter pr. dag, 1 GB disk, ingen "Always On".
//   - Azure SQL Database "free offer": 100.000 vCore-sekunder og 32 GB pr. måned.
//     Når det gratis forbrug er brugt, går databasen på pause til næste måned (koster aldrig noget).

@description('dev eller prod')
@allowed(['dev', 'prod'])
param miljo string

param location string = resourceGroup().location

@description('Navn på web-appen. Skal være unikt i hele Azure (bliver <navn>.azurewebsites.net).')
param appName string

@description('Navn på SQL-serveren. Skal være unikt i hele Azure.')
param sqlServerName string

@description('F1 = gratis. B1 = ca. 100 kr./md. med Always On og health check.')
@allowed(['F1', 'B1', 'B2', 'S1', 'P0v3', 'P1v3'])
param appSku string = 'F1'

@description('true = Azure SQL free offer (gratis, pauser når forbruget er brugt). false = betalt serverless.')
param freeSql bool = true

param sqlAdminLogin string = 'gaestereg_admin'

@secure()
param sqlAdminPassword string

var free = appSku == 'F1'
var dbName = 'gaestereg-${miljo}'
var tags = { app: 'gaestereg', miljo: miljo }

resource plan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: 'plan-gaestereg-${miljo}'
  location: location
  tags: tags
  kind: 'linux'
  sku: { name: appSku }
  properties: { reserved: true }
}

resource sql 'Microsoft.Sql/servers@2023-08-01-preview' = {
  name: sqlServerName
  location: location
  tags: tags
  properties: {
    administratorLogin: sqlAdminLogin
    administratorLoginPassword: sqlAdminPassword
    minimalTlsVersion: '1.2'
    publicNetworkAccess: 'Enabled'
  }
}

// Lader tjenester i Azure (bl.a. App Service) nå serveren. Adgang kræver stadig login.
resource sqlAllowAzure 'Microsoft.Sql/servers/firewallRules@2023-08-01-preview' = {
  parent: sql
  name: 'AllowAllWindowsAzureIps'
  properties: { startIpAddress: '0.0.0.0', endIpAddress: '0.0.0.0' }
}

resource db 'Microsoft.Sql/servers/databases@2023-08-01-preview' = {
  parent: sql
  name: dbName
  location: location
  tags: tags
  sku: { name: 'GP_S_Gen5', tier: 'GeneralPurpose', family: 'Gen5', capacity: 2 }
  properties: {
    useFreeLimit: freeSql
    freeLimitExhaustionBehavior: freeSql ? 'AutoPause' : null
    autoPauseDelay: 60
    minCapacity: json('0.5')
    maxSizeBytes: 34359738368 // 32 GB, det gratis loft
    collation: 'Danish_Norwegian_CI_AS'
    zoneRedundant: false
    requestedBackupStorageRedundancy: 'Local'
  }
}

resource app 'Microsoft.Web/sites@2023-12-01' = {
  name: appName
  location: location
  tags: tags
  kind: 'app,linux'
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.12'
      appCommandLine: 'sh startup.sh'
      alwaysOn: !free // ikke muligt på F1
      healthCheckPath: free ? null : '/healthz'
      http20Enabled: true
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
    }
  }
}

// GitHub Actions udruller med en publish profile, som kræver basic auth på SCM.
resource scmBasicAuth 'Microsoft.Web/sites/basicPublishingCredentialsPolicies@2023-12-01' = {
  parent: app
  name: 'scm'
  properties: { allow: true }
}

output appName string = app.name
output appUrl string = 'https://${app.properties.defaultHostName}'
output sqlServer string = sql.properties.fullyQualifiedDomainName
output database string = dbName
