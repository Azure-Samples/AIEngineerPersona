// core.bicep — resource-group-scoped infra for Children's Story Studio.
//
// Creates:
//   - Azure Container Registry  (image storage; pulled by App Service via MI)
//   - Storage Account + Blob Container (persistent demo-stories store, MI-only)
//   - Log Analytics + Application Insights (App Service diagnostics)
//   - App Service Plan (Linux B2 by default; resize via param)
//   - Web App (custom container, system-assigned managed identity)
//
// All cross-resource references stay inside this module so main.bicep can
// stay focused on inputs/outputs and cross-RG RBAC.

@description('Region for all resources.')
param location string

@description('Stable token derived from environment + subscription, used in resource names.')
param resourceToken string

@description('Common tags applied to every resource.')
param tags object

@description('App Service Plan SKU.  P1v3 recommended for production demos; B2 is cheaper for personal demos.')
@allowed([ 'B2', 'B3', 'P0v3', 'P1v3', 'P2v3', 'P3v3' ])
param appServicePlanSku string = 'B2'

// Foundry / Speech config — passed straight through to App Settings
param foundryProjectEndpoint string
param foundryModelDeploymentName string
param foundryImageModelDeploymentName string
param azureSpeechRegion string
param speechAccountName string
param speechResourceGroup string

// ─── Naming ────────────────────────────────────────────────────────────────

// ACR names: 5-50, alphanumeric only, globally unique
var acrName     = toLower('acr${take(replace(resourceToken, '-', ''), 20)}')
var planName    = 'plan-${resourceToken}'
var webAppName  = 'app-${resourceToken}'
var lawName     = 'log-${resourceToken}'
var aiName      = 'appi-${resourceToken}'
// Storage account names: 3-24, lowercase alphanumeric only, globally unique
var storageName = toLower('st${take(replace(resourceToken, '-', ''), 22)}')
var storageContainerName = 'demo-stories'

// ─── Container Registry ─────────────────────────────────────────────────────

#disable-next-line BCP334
resource acr 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' = {
  #disable-next-line BCP334
  name: acrName
  location: location
  tags: tags
  sku: { name: 'Basic' }
  properties: {
    adminUserEnabled: false
  }
}

// Note on persistent storage:
//   Demo stories (the bundled samples and any the user saves at runtime) are
//   kept in an Azure Storage blob container.  We require Entra-only auth
//   (allowSharedKeyAccess: false) per company policy — the web app's system-
//   assigned managed identity is granted Storage Blob Data Contributor below,
//   and BlobBackend uses DefaultAzureCredential to authenticate.

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  #disable-next-line BCP334
  name: storageName
  location: location
  tags: tags
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    accessTier: 'Hot'
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowSharedKeyAccess: false       // RBAC / Entra only — no account keys
    allowBlobPublicAccess: false
    defaultToOAuthAuthentication: true
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      defaultAction: 'Allow'
      bypass: 'AzureServices'
    }
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
  properties: {
    deleteRetentionPolicy: { enabled: true, days: 7 }
    containerDeleteRetentionPolicy: { enabled: true, days: 7 }
  }
}

resource demoContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: storageContainerName
  properties: {
    publicAccess: 'None'
  }
}

// ─── Observability ─────────────────────────────────────────────────────────

resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: lawName
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: aiName
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: law.id
  }
}

// ─── App Service Plan + Web App (Linux container) ──────────────────────────

resource plan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: planName
  location: location
  tags: tags
  sku: { name: appServicePlanSku }
  kind: 'linux'
  properties: {
    reserved: true
  }
}

// Placeholder image — `azd deploy` will push the real image to ACR and
// update the linuxFxVersion to point at it.
var placeholderImage = 'mcr.microsoft.com/appsvc/staticsite:latest'

resource web 'Microsoft.Web/sites@2023-12-01' = {
  name: webAppName
  location: location
  tags: union(tags, { 'azd-service-name': 'web' })
  kind: 'app,linux,container'
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    publicNetworkAccess: 'Enabled'
    siteConfig: {
      linuxFxVersion: 'DOCKER|${placeholderImage}'
      acrUseManagedIdentityCreds: true
      alwaysOn: true
      http20Enabled: true
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      healthCheckPath: '/api/health'
      appSettings: [
        // Tell App Service which port the container listens on
        { name: 'WEBSITES_PORT', value: '8000' }
        { name: 'PORT',          value: '8000' }
        // Pull image from our ACR
        { name: 'DOCKER_REGISTRY_SERVER_URL', value: 'https://${acr.properties.loginServer}' }
        // Application Insights
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsights.properties.ConnectionString }
        { name: 'ApplicationInsightsAgent_EXTENSION_VERSION', value: '~3' }
        // Persistent demo-stories store — Azure Blob Storage, Entra-auth only.
        // BlobBackend uses DefaultAzureCredential against the web app's MI;
        // RBAC (Storage Blob Data Contributor) is granted on the container below.
        { name: 'STORAGE_BACKEND',              value: 'blob' }
        { name: 'AZURE_STORAGE_ACCOUNT_NAME',   value: storage.name }
        { name: 'AZURE_STORAGE_CONTAINER_NAME', value: storageContainerName }
        // Foundry config (consumed by backend/app/config.py and Agent Framework)
        { name: 'FOUNDRY_PROJECT_ENDPOINT',           value: foundryProjectEndpoint }
        { name: 'FOUNDRY_MODEL_DEPLOYMENT_NAME',      value: foundryModelDeploymentName }
        { name: 'FOUNDRY_IMAGE_MODEL_DEPLOYMENT_NAME', value: foundryImageModelDeploymentName }
        // Speech config
        { name: 'AZURE_SPEECH_REGION',      value: azureSpeechRegion }
        { name: 'AZURE_SPEECH_ENDPOINT',    value: 'https://${azureSpeechRegion}.tts.speech.microsoft.com' }
        { name: 'AZURE_SPEECH_RESOURCE_ID', value: resourceId(speechResourceGroup, 'Microsoft.CognitiveServices/accounts', speechAccountName) }
        // CORS — same-origin in production, but keep harmless default
        { name: 'CORS_ORIGIN', value: 'https://${webAppName}.azurewebsites.net' }
      ]
    }
  }
}

// ─── RBAC: AppService MI -> AcrPull on the registry ────────────────────────

var acrPullRoleId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')

resource acrPullAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, web.id, 'AcrPull')
  scope: acr
  properties: {
    roleDefinitionId: acrPullRoleId
    principalId: web.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// ─── RBAC: AppService MI -> Storage Blob Data Contributor on the container ──

var blobDataContributorRoleId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')

resource blobDataContribAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(demoContainer.id, web.id, 'BlobDataContributor')
  scope: demoContainer
  properties: {
    roleDefinitionId: blobDataContributorRoleId
    principalId: web.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// ─── Diagnostics → Log Analytics ───────────────────────────────────────────

resource webDiag 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'to-law'
  scope: web
  properties: {
    workspaceId: law.id
    logs: [
      { categoryGroup: 'allLogs', enabled: true }
    ]
    metrics: [
      { category: 'AllMetrics', enabled: true }
    ]
  }
}

// ─── Outputs ───────────────────────────────────────────────────────────────

output acrName string = acr.name
output acrLoginServer string = acr.properties.loginServer
output webAppName string = web.name
output webAppUri string = 'https://${web.properties.defaultHostName}'
output webAppImageName string = '${acr.properties.loginServer}/${webAppName}:latest'
output appPrincipalId string = web.identity.principalId
output storageAccountName string = storage.name
output storageContainerName string = storageContainerName
