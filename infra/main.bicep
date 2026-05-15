// Subscription-scoped entrypoint for AIEngineerPersona's Container Apps deploy.
//
// Creates a resource group named rg-${environmentName} (default: rg-zavastory)
// and dispatches into infra/main-rg.bicep at that scope. This keeps `azd up`
// a single command (no manual `az group create` step) while still mirroring
// the marketing-campaign module structure.
//
// Override the resource group name with `azd env set RESOURCE_GROUP_NAME <name>`
// — useful if you want to deploy into rg-zava-story (with hyphen) instead of
// the default rg-zavastory.

targetScope = 'subscription'

// ---------------------------------------------------------------------------
// Required parameters (azd auto-supplies environmentName + location)
// ---------------------------------------------------------------------------

@minLength(2)
@maxLength(12)
@description('Short prefix used for every resource name (lowercase alphanumeric, max 12 chars). azd supplies this from AZURE_ENV_NAME.')
param environmentName string

@minLength(1)
@description('Azure region for the new resources. azd supplies this from AZURE_LOCATION.')
param location string

@description('Override for the resource group name. Default: rg-<environmentName>.')
param resourceGroupName string = ''

// ---------------------------------------------------------------------------
// App configuration parameters (forwarded to main-rg.bicep)
// ---------------------------------------------------------------------------

@description('Optional explicit container image reference (set by azd as SERVICE_APP_IMAGE_NAME after `azd deploy`). When empty, the placeholder image is used so the Container App can be created on the very first `azd up` before the ACR repo has any image. After the first deploy, azd populates this on subsequent provisions so the live image is preserved.')
param appImageName string = ''

@description('ACR name. Defaults to <env>acr.')
param acrName string = ''

@description('Storage account name. Globally unique, 3–24 lowercase alphanumeric.')
@minLength(3)
@maxLength(24)
param storageAccountName string

@description('Blob container name for demo stories.')
param storageContainerName string = 'demo-stories'

@description('Foundry project endpoint URL. AIEngineerPersona uses the SHORT account-level form.')
param foundryProjectEndpoint string

@description('Foundry chat model deployment name.')
param foundryModelDeploymentName string = 'gpt-5.2'

@description('Foundry image model deployment name.')
param foundryImageModelDeploymentName string = 'gpt-image-1.5'

@description('Full ARM resource ID of the EXISTING Foundry / AIServices account.')
param foundryResourceId string

@description('Azure region for the colocated Speech resource.')
param azureSpeechRegion string = 'eastus2'

@description('Public Speech TTS endpoint base URL. Leave empty to derive from azureSpeechRegion.')
param azureSpeechEndpoint string = ''

@description('Full ARM resource ID of the Cognitive Services account that exposes the Speech surface. Leave empty to default to foundryResourceId.')
param azureSpeechResourceId string = ''

@description('CPU cores per replica (string, e.g. "1.0").')
param containerCpu string = '1.0'

@description('Memory per replica (e.g. "2Gi").')
param containerMemory string = '2Gi'

@description('Minimum replica count.')
@minValue(0)
param minReplicas int = 1

@description('Maximum replica count.')
@minValue(1)
param maxReplicas int = 3

@description('CORS allow-origin. The SPA is served from the same origin as the API; this only matters for local dev hitting the deployed API.')
param corsOrigin string = 'http://localhost:5173'

// ---------------------------------------------------------------------------
// Private networking parameters (forwarded with safe defaults)
// ---------------------------------------------------------------------------

param vnetName string = ''
param vnetAddressPrefix string = '10.20.0.0/22'
param caeSubnetName string = 'cae-infra'
param caeSubnetAddressPrefix string = '10.20.0.0/23'
param privateEndpointsSubnetName string = 'private-endpoints'
param privateEndpointsSubnetAddressPrefix string = '10.20.2.0/26'
param storageBlobPeName string = ''

// ---------------------------------------------------------------------------
// Container Apps Easy Auth parameters (gated off by default)
// ---------------------------------------------------------------------------

@description('Master switch for Container Apps Easy Auth. Off by default.')
param enableEntraAuth bool = false

@description('Entra app registration client (application) ID. Required when enableEntraAuth is true.')
param entraClientId string = ''

@description('Entra app registration client secret. Required when enableEntraAuth is true.')
@secure()
param entraClientSecret string = ''

@description('Entra tenant ID for the OIDC issuer. Defaults to the deploying subscription tenant.')
param entraTenantId string = subscription().tenantId

// ---------------------------------------------------------------------------
// Resource group + RG-scoped dispatch
// ---------------------------------------------------------------------------

var resolvedResourceGroupName = empty(resourceGroupName) ? 'rg-${environmentName}' : resourceGroupName

var tags = {
  'azd-env-name': environmentName
}

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: resolvedResourceGroupName
  location: location
  tags: tags
}

module main 'main-rg.bicep' = {
  name: 'main-rg'
  scope: rg
  params: {
    location: location
    environmentName: environmentName
    appImageName: appImageName
    acrName: empty(acrName) ? '${toLower(environmentName)}acr' : acrName
    storageAccountName: storageAccountName
    storageContainerName: storageContainerName
    foundryProjectEndpoint: foundryProjectEndpoint
    foundryModelDeploymentName: foundryModelDeploymentName
    foundryImageModelDeploymentName: foundryImageModelDeploymentName
    foundryResourceId: foundryResourceId
    azureSpeechRegion: azureSpeechRegion
    azureSpeechEndpoint: azureSpeechEndpoint
    azureSpeechResourceId: azureSpeechResourceId
    containerCpu: containerCpu
    containerMemory: containerMemory
    minReplicas: minReplicas
    maxReplicas: maxReplicas
    corsOrigin: corsOrigin
    vnetName: vnetName
    vnetAddressPrefix: vnetAddressPrefix
    caeSubnetName: caeSubnetName
    caeSubnetAddressPrefix: caeSubnetAddressPrefix
    privateEndpointsSubnetName: privateEndpointsSubnetName
    privateEndpointsSubnetAddressPrefix: privateEndpointsSubnetAddressPrefix
    storageBlobPeName: storageBlobPeName
    enableEntraAuth: enableEntraAuth
    entraClientId: entraClientId
    entraClientSecret: entraClientSecret
    entraTenantId: empty(entraTenantId) ? subscription().tenantId : entraTenantId
  }
}

// ---------------------------------------------------------------------------
// Outputs — written by azd to .azure/<env>/.env.
//
// Naming follows the azd convention so `azd up` automatically wires the
// container app deploy step to the right resources:
//   - AZURE_CONTAINER_REGISTRY_ENDPOINT / _NAME → tells azd which ACR to push to
//   - SERVICE_APP_NAME                          → ties the `app` service to the right Container App
//   - AZURE_RESOURCE_GROUP                      → propagated for scripts and rg-scoped CLI
// ---------------------------------------------------------------------------

output AZURE_LOCATION string = location
output AZURE_RESOURCE_GROUP string = rg.name
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = main.outputs.acrLoginServer
output AZURE_CONTAINER_REGISTRY_NAME string = main.outputs.acrName
output SERVICE_APP_NAME string = main.outputs.containerAppName
output SERVICE_APP_URI string = main.outputs.containerAppUrl
output SERVICE_APP_FQDN string = main.outputs.containerAppFqdn
output AZURE_STORAGE_ACCOUNT_NAME string = main.outputs.storageAccountName
output AZURE_STORAGE_CONTAINER_NAME string = main.outputs.storageContainerName
output AZURE_MANAGED_IDENTITY_CLIENT_ID string = main.outputs.managedIdentityClientId
output AZURE_MANAGED_IDENTITY_PRINCIPAL_ID string = main.outputs.managedIdentityPrincipalId
output APPLICATIONINSIGHTS_CONNECTION_STRING string = main.outputs.appInsightsConnectionString
output VNET_ID string = main.outputs.vnetId
output VNET_NAME string = main.outputs.vnetName
output STORAGE_BLOB_PRIVATE_ENDPOINT_NAME string = main.outputs.storageBlobPrivateEndpointName
output ENTRA_AUTH_ENABLED bool = main.outputs.entraAuthEnabled
output LOGIN_URL string = main.outputs.loginUrl
