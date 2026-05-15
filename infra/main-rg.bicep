// RG-scoped orchestrator for the Children's Story Studio Container Apps stack.
//
// Mirrors the structure of ai-marketing-campaign/infra/prod/main.bicep but
// adapted for AIEngineerPersona:
//   - ONE container app (no streaming-on/off split)
//   - ONE blob container `demo-stories`
//   - AIEngineerPersona env-var names (FOUNDRY_PROJECT_ENDPOINT,
//     AZURE_STORAGE_ACCOUNT_NAME, etc.)
//   - Foundry and Speech surfaces colocated on the same AIServices account
//     (e.g. sofio-eus2-foundry-resource); same-account dedup avoids
//     duplicate role-assignment GUIDs.
//
// The Foundry account is EXISTING (the user pre-provisions it). Pass its
// full ARM resource ID as `foundryResourceId` so the cross-scope role
// assignments can target it (potentially in a different RG).
//
// This module is RG-scoped — it does NOT create the resource group. The
// parent (infra/main.bicep) creates the RG and dispatches into here.

targetScope = 'resourceGroup'

// ---------------------------------------------------------------------------
// Parameters
// ---------------------------------------------------------------------------

@description('Azure region for all resources provisioned by this template. Defaults to the parent resource group location.')
param location string = resourceGroup().location

@description('Short prefix used for every resource name (lowercase alphanumeric, max 12 chars).')
@minLength(2)
@maxLength(12)
param environmentName string

@description('Optional explicit container image reference (set by azd as SERVICE_APP_IMAGE_NAME after `azd deploy`). When empty, the placeholder image is used so the Container App can be created on the very first `azd up` before the ACR repo has any image. After the first deploy, azd populates this on subsequent provisions so the live image is preserved.')
param appImageName string = ''

@description('ACR name (5–50 lowercase alphanumeric, globally unique). Defaults to <env>acr.')
@minLength(5)
@maxLength(50)
param acrName string = '${toLower(environmentName)}acr'

@description('Storage account name. Globally unique, 3–24 lowercase alphanumeric. Required (no default — must be supplied).')
@minLength(3)
@maxLength(24)
param storageAccountName string

@description('Blob container name for demo stories. Default matches BlobBackend default.')
param storageContainerName string = 'demo-stories'

@description('Foundry project endpoint URL. AIEngineerPersona uses the SHORT account-level form (https://<acct>.services.ai.azure.com/).')
param foundryProjectEndpoint string

@description('Foundry chat model deployment name.')
param foundryModelDeploymentName string = 'gpt-5.2'

@description('Foundry image model deployment name.')
param foundryImageModelDeploymentName string = 'gpt-image-1.5'

@description('Full ARM resource ID of the EXISTING Foundry / AIServices account that backs the foundryProjectEndpoint. Format: /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.CognitiveServices/accounts/<name>')
param foundryResourceId string

@description('Azure region for the colocated Speech resource (e.g. eastus2). Used by the TTS pipeline. Typically matches the Foundry/AIServices account region.')
param azureSpeechRegion string = 'eastus2'

@description('Public Speech TTS endpoint base URL. Leave empty to derive from azureSpeechRegion (https://<region>.tts.speech.microsoft.com).')
param azureSpeechEndpoint string = ''

@description('Full ARM resource ID of the Cognitive Services account that exposes the Speech surface. Leave empty to default to foundryResourceId (the multi-service AIServices account exposes Speech alongside OpenAI).')
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

@description('CORS allow-origin. The SPA is served from the same origin as the API, so this only matters for local development against the deployed API.')
param corsOrigin string = 'http://localhost:5173'

// ---------------------------------------------------------------------------
// Private networking parameters. All have safe defaults.
// ---------------------------------------------------------------------------

@description('VNet name. Leave empty to derive from environmentName as <env>vnet.')
param vnetName string = ''

@description('VNet CIDR. Default 10.20.0.0/22 (1024 addresses).')
param vnetAddressPrefix string = '10.20.0.0/22'

@description('CAE infrastructure subnet name.')
param caeSubnetName string = 'cae-infra'

@description('CAE infrastructure subnet CIDR. Consumption-only CAE requires /23 minimum.')
param caeSubnetAddressPrefix string = '10.20.0.0/23'

@description('Private endpoints subnet name.')
param privateEndpointsSubnetName string = 'private-endpoints'

@description('Private endpoints subnet CIDR. /26 (64 addresses) leaves headroom for future PEs.')
param privateEndpointsSubnetAddressPrefix string = '10.20.2.0/26'

@description('Storage blob private endpoint name. Leave empty to derive from storageAccountName as <storage>-blob-pe.')
param storageBlobPeName string = ''

// ---------------------------------------------------------------------------
// Container Apps Easy Auth — Microsoft Entra (single-tenant) sign-in in
// front of the app. All four params default to off so a fresh `azd up`
// against an empty subscription doesn't get blocked on Entra bootstrapping.
// To enable: run infra/scripts/create_entra_app_reg.sh, then re-deploy with
// the captured values + enableEntraAuth=true.
// ---------------------------------------------------------------------------

@description('Master switch for Container Apps Easy Auth. When false, no auth is enforced and the other Entra params are ignored. When true, all three of entraClientId, entraClientSecret, entraTenantId must be non-empty.')
param enableEntraAuth bool = false

@description('Entra app registration client (application) ID. Required when enableEntraAuth is true.')
param entraClientId string = ''

@description('Entra app registration client secret. Required when enableEntraAuth is true. Mounted as a Container App secret named entra-client-secret.')
@secure()
param entraClientSecret string = ''

@description('Entra tenant ID for the OIDC issuer (single-tenant). Defaults to the deploying subscription tenant.')
param entraTenantId string = subscription().tenantId

// ---------------------------------------------------------------------------
// Names — deterministic from environmentName so re-deploys are idempotent.
// ---------------------------------------------------------------------------

var nameSuffix = toLower(environmentName)
var logAnalyticsName = '${nameSuffix}law'
var appInsightsName = '${nameSuffix}ai'
var managedIdentityName = '${nameSuffix}mi'
var containerEnvName = '${nameSuffix}cae'
var containerAppName = '${nameSuffix}-app'

// Derived names: parameters allow empty so the parameters.json file can pass
// empty defaults from unset env vars without overriding the computed names.
var resolvedVnetName = empty(vnetName) ? '${nameSuffix}vnet' : vnetName
var resolvedStorageBlobPeName = empty(storageBlobPeName) ? '${storageAccountName}-blob-pe' : storageBlobPeName

// Resolve Speech defaults (parameters.json passes empty strings when env vars
// are unset, which would otherwise override the param defaults).
var resolvedSpeechEndpoint = empty(azureSpeechEndpoint) ? 'https://${azureSpeechRegion}.tts.speech.microsoft.com' : azureSpeechEndpoint
var resolvedSpeechResourceId = empty(azureSpeechResourceId) ? foundryResourceId : azureSpeechResourceId

// ---------------------------------------------------------------------------
// Parse the Foundry / Speech ARM IDs so we can scope role assignments to the
// correct subscription + RG. Format expected:
//   /subscriptions/{sub}/resourceGroups/{rg}/providers/{ns}/accounts/{name}
// indices:           1               2     3               4   5         6/7  8
// ---------------------------------------------------------------------------

var foundryParts = split(foundryResourceId, '/')
var foundrySubscriptionId = foundryParts[2]
var foundryResourceGroupName = foundryParts[4]
var foundryAccountName = foundryParts[8]

var speechParts = split(resolvedSpeechResourceId, '/')
var speechSubscriptionId = speechParts[2]
var speechResourceGroupName = speechParts[4]
var speechAccountName = speechParts[8]

// True when Speech and Foundry point to the same Cognitive Services account
// (the AIServices resource exposes both surfaces). When true, we grant the
// Speech User role on the Foundry account and skip the duplicate
// cross-scope module to avoid same-name role-assignment GUID collisions.
var speechAndFoundryAreSameAccount = toLower(speechSubscriptionId) == toLower(foundrySubscriptionId) && toLower(speechResourceGroupName) == toLower(foundryResourceGroupName) && toLower(speechAccountName) == toLower(foundryAccountName)

// Built-in role definition GUIDs.
//   Cognitive Services OpenAI User: 5e0bd9bd-7b93-4f28-af87-19fc36ad61bd
//   Azure AI User:                  53ca6127-db72-4b80-b1b0-d745d6d5456d
//     (preserves the role used by the prior infra/rbac-foundry.bicep —
//      grants data-plane access to the Foundry project surface)
//   Cognitive Services Speech User: f2dc8367-1007-4938-bd23-fe263f013447
//     (Speech SDK uses AAD when AZURE_SPEECH_API_KEY is unset and
//      AZURE_SPEECH_RESOURCE_ID is set)
var cognitiveServicesOpenAIUserRoleId = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
var azureAIUserRoleId = '53ca6127-db72-4b80-b1b0-d745d6d5456d'
var cognitiveServicesSpeechUserRoleId = 'f2dc8367-1007-4938-bd23-fe263f013447'

// ---------------------------------------------------------------------------
// Modules
// ---------------------------------------------------------------------------

module logAnalytics 'modules/log_analytics.bicep' = {
  name: 'logAnalytics'
  params: {
    location: location
    name: logAnalyticsName
  }
}

module appInsights 'modules/app_insights.bicep' = {
  name: 'appInsights'
  params: {
    location: location
    name: appInsightsName
    logAnalyticsWorkspaceId: logAnalytics.outputs.id
  }
}

module acr 'modules/acr.bicep' = {
  name: 'acr'
  params: {
    location: location
    name: acrName
    sku: 'Basic'
  }
}

module managedIdentity 'modules/managed_identity.bicep' = {
  name: 'managedIdentity'
  params: {
    location: location
    name: managedIdentityName
  }
}

module storage 'modules/storage.bicep' = {
  name: 'storage'
  params: {
    location: location
    name: storageAccountName
    sku: 'Standard_LRS'
    containerName: storageContainerName
  }
}

// ---------------------------------------------------------------------------
// Private networking — VNet + private DNS zone + storage Private Endpoint.
// The CAE is bound to the cae-infra subnet; the container app reaches storage
// via the Private Endpoint, so storage's publicNetworkAccess is 'Disabled'.
// ---------------------------------------------------------------------------

module network 'modules/network.bicep' = {
  name: 'network'
  params: {
    location: location
    vnetName: resolvedVnetName
    vnetAddressPrefix: vnetAddressPrefix
    caeSubnetName: caeSubnetName
    caeSubnetAddressPrefix: caeSubnetAddressPrefix
    privateEndpointsSubnetName: privateEndpointsSubnetName
    privateEndpointsSubnetAddressPrefix: privateEndpointsSubnetAddressPrefix
  }
}

module storageBlobPrivateEndpoint 'modules/storage_private_endpoint.bicep' = {
  name: 'storageBlobPrivateEndpoint'
  params: {
    location: location
    peName: resolvedStorageBlobPeName
    subnetId: network.outputs.privateEndpointsSubnetId
    storageAccountId: storage.outputs.id
    blobPrivateDnsZoneId: network.outputs.blobPrivateDnsZoneId
  }
}

module containerEnv 'modules/container_apps_env.bicep' = {
  name: 'containerEnv'
  params: {
    location: location
    name: containerEnvName
    logAnalyticsWorkspaceName: logAnalytics.outputs.name
    infrastructureSubnetId: network.outputs.caeSubnetId
    internalLoadBalancer: false
  }
}

// In-RG role grants: Storage Blob Data Contributor + AcrPull on the UAMI.
module roleAssignments 'modules/role_assignments.bicep' = {
  name: 'roleAssignments'
  params: {
    managedIdentityPrincipalId: managedIdentity.outputs.principalId
    storageAccountName: storage.outputs.name
    acrName: acr.outputs.name
  }
}

// ---------------------------------------------------------------------------
// Cross-scope role grants on the EXISTING Foundry account.
//   - Cognitive Services OpenAI User: chat + image generation via Foundry's
//     /openai/v1/responses + /openai/v1/images endpoints.
//   - Azure AI User: matches the role granted by the prior
//     infra/rbac-foundry.bicep template (data-plane access to the Foundry
//     project surface).
//   - Cognitive Services Speech User: Speech SDK uses AAD when
//     AZURE_SPEECH_API_KEY is unset and AZURE_SPEECH_RESOURCE_ID is set.
//     Granted on the Foundry account when Speech is colocated there
//     (the typical case — a single multi-service AIServices account).
// ---------------------------------------------------------------------------

module foundryOpenAIUserRoleAssignment 'modules/external_role_assignment.bicep' = {
  name: 'foundryOpenAIUserRoleAssignment'
  scope: resourceGroup(foundrySubscriptionId, foundryResourceGroupName)
  params: {
    cognitiveServicesAccountName: foundryAccountName
    principalId: managedIdentity.outputs.principalId
    roleDefinitionGuid: cognitiveServicesOpenAIUserRoleId
  }
}

module foundryAIUserRoleAssignment 'modules/external_role_assignment.bicep' = {
  name: 'foundryAIUserRoleAssignment'
  scope: resourceGroup(foundrySubscriptionId, foundryResourceGroupName)
  params: {
    cognitiveServicesAccountName: foundryAccountName
    principalId: managedIdentity.outputs.principalId
    roleDefinitionGuid: azureAIUserRoleId
  }
}

// Speech User on the Foundry account (when Speech is colocated). Skipped
// when Speech lives elsewhere — that case is handled by the next module.
module foundrySpeechUserRoleAssignment 'modules/external_role_assignment.bicep' = if (speechAndFoundryAreSameAccount) {
  name: 'foundrySpeechUserRoleAssignment'
  scope: resourceGroup(foundrySubscriptionId, foundryResourceGroupName)
  params: {
    cognitiveServicesAccountName: foundryAccountName
    principalId: managedIdentity.outputs.principalId
    roleDefinitionGuid: cognitiveServicesSpeechUserRoleId
  }
}

// Speech User on a SEPARATE Speech account (when Speech is not colocated
// with Foundry). Skipped in the typical AIEngineerPersona setup.
module speechAccountRoleAssignment 'modules/external_role_assignment.bicep' = if (!speechAndFoundryAreSameAccount) {
  name: 'speechAccountRoleAssignment'
  scope: resourceGroup(speechSubscriptionId, speechResourceGroupName)
  params: {
    cognitiveServicesAccountName: speechAccountName
    principalId: managedIdentity.outputs.principalId
    roleDefinitionGuid: cognitiveServicesSpeechUserRoleId
  }
}

// ---------------------------------------------------------------------------
// Container App.
// ---------------------------------------------------------------------------

module app 'modules/container_app.bicep' = {
  name: 'app'
  dependsOn: [
    roleAssignments
  ]
  params: {
    location: location
    name: containerAppName
    containerAppsEnvironmentId: containerEnv.outputs.id
    managedIdentityId: managedIdentity.outputs.id
    managedIdentityClientId: managedIdentity.outputs.clientId
    acrLoginServer: acr.outputs.loginServer
    appImageName: appImageName
    cpu: containerCpu
    memory: containerMemory
    minReplicas: minReplicas
    maxReplicas: maxReplicas
    storageAccountName: storage.outputs.name
    storageContainerName: storage.outputs.containerName
    foundryProjectEndpoint: foundryProjectEndpoint
    foundryModelDeploymentName: foundryModelDeploymentName
    foundryImageModelDeploymentName: foundryImageModelDeploymentName
    azureSpeechRegion: azureSpeechRegion
    azureSpeechEndpoint: resolvedSpeechEndpoint
    azureSpeechResourceId: resolvedSpeechResourceId
    appInsightsConnectionString: appInsights.outputs.connectionString
    corsOrigin: corsOrigin
    enableEntraAuth: enableEntraAuth
    entraClientSecret: entraClientSecret
  }
}

// ---------------------------------------------------------------------------
// Container Apps Easy Auth — gated on the same enableEntraAuth flag as the
// secret-injection in container_app.bicep, so the secret + the authConfig
// appear and disappear together (no dangling-reference foot-gun on
// subsequent deploys).
// ---------------------------------------------------------------------------

module appAuth 'modules/container_app_auth.bicep' = if (enableEntraAuth) {
  name: 'appAuth'
  dependsOn: [
    app
  ]
  params: {
    containerAppName: containerAppName
    entraClientId: entraClientId
    entraTenantId: entraTenantId
  }
}

// ---------------------------------------------------------------------------
// Outputs — bubbled to the sub-scoped parent and consumed by azd.
// ---------------------------------------------------------------------------

output containerAppName string = app.outputs.name
output containerAppFqdn string = app.outputs.fqdn
output containerAppUrl string = app.outputs.url
output acrName string = acr.outputs.name
output acrLoginServer string = acr.outputs.loginServer
output storageAccountName string = storage.outputs.name
output storageContainerName string = storage.outputs.containerName
output managedIdentityId string = managedIdentity.outputs.id
output managedIdentityName string = managedIdentity.outputs.name
output managedIdentityClientId string = managedIdentity.outputs.clientId
output managedIdentityPrincipalId string = managedIdentity.outputs.principalId
output containerAppsEnvironmentId string = containerEnv.outputs.id
output appInsightsConnectionString string = appInsights.outputs.connectionString
output logAnalyticsWorkspaceId string = logAnalytics.outputs.id
output vnetId string = network.outputs.vnetId
output vnetName string = network.outputs.vnetName
output caeSubnetId string = network.outputs.caeSubnetId
output privateEndpointsSubnetId string = network.outputs.privateEndpointsSubnetId
output blobPrivateDnsZoneId string = network.outputs.blobPrivateDnsZoneId
output storageBlobPrivateEndpointName string = storageBlobPrivateEndpoint.outputs.name
output entraAuthEnabled bool = enableEntraAuth
output loginUrl string = '${app.outputs.url}/.auth/login/aad'
