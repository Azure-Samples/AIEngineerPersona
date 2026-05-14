targetScope = 'subscription'

// ─── Required parameters (azd auto-supplies environmentName + location) ──────

@minLength(1)
@maxLength(64)
@description('Name of the azd environment. Used to derive resource names.')
param environmentName string

@minLength(1)
@description('Azure region for the new resources (App Service, ACR, Storage).')
param location string

// ─── Existing Azure AI Foundry project (reused, not created) ────────────────

@description('Resource group containing your existing Azure AI Foundry (Cognitive Services) account.')
param foundryResourceGroup string

@description('Name of the existing Azure AI Foundry / AI Services account.')
param foundryAccountName string

@description('Full Foundry project endpoint (https://<acct>.services.ai.azure.com/api/projects/<project>).')
param foundryProjectEndpoint string

@description('Chat/text model deployment name on the Foundry account.')
param foundryModelDeploymentName string = 'gpt-4o'

@description('Image model deployment name on the Foundry account.')
param foundryImageModelDeploymentName string = 'gpt-image-1.5'

// ─── Existing Azure AI Speech account (reused) ──────────────────────────────

@description('Resource group containing your existing Speech (Cognitive Services) account.')
param speechResourceGroup string

@description('Name of the existing Speech account.')
param speechAccountName string

@description('Region of the Speech account (e.g. eastus).')
param azureSpeechRegion string

// ─── Optional principal for local-dev RBAC (not required) ────────────────────
@description('Object ID of a user/SP to also grant runtime RBAC (optional, for local dev with the same identity).')
param principalId string = ''

// ─── Naming ─────────────────────────────────────────────────────────────────

var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))
var tags = {
  'azd-env-name': environmentName
}

// Resource group for everything we create
resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-${environmentName}'
  location: location
  tags: tags
}

// ─── Core deployment ────────────────────────────────────────────────────────

module core 'core.bicep' = {
  name: 'core-${resourceToken}'
  scope: rg
  params: {
    location: location
    resourceToken: resourceToken
    tags: tags
    foundryProjectEndpoint: foundryProjectEndpoint
    foundryModelDeploymentName: foundryModelDeploymentName
    foundryImageModelDeploymentName: foundryImageModelDeploymentName
    azureSpeechRegion: azureSpeechRegion
    speechAccountName: speechAccountName
    speechResourceGroup: speechResourceGroup
  }
}

// ─── RBAC: grant the App Service's managed identity access to existing Foundry/Speech ─
// These role assignments live in the *existing* resource groups (not rg).

module foundryRbac 'rbac-foundry.bicep' = {
  name: 'rbac-foundry-${resourceToken}'
  scope: resourceGroup(foundryResourceGroup)
  params: {
    foundryAccountName: foundryAccountName
    principalId: core.outputs.appPrincipalId
    additionalPrincipalId: principalId
  }
}

module speechRbac 'rbac-speech.bicep' = {
  name: 'rbac-speech-${resourceToken}'
  scope: resourceGroup(speechResourceGroup)
  params: {
    speechAccountName: speechAccountName
    principalId: core.outputs.appPrincipalId
    additionalPrincipalId: principalId
  }
}

// ─── Outputs consumed by azd ────────────────────────────────────────────────

output AZURE_LOCATION string = location
output AZURE_RESOURCE_GROUP string = rg.name
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = core.outputs.acrLoginServer
output AZURE_CONTAINER_REGISTRY_NAME string = core.outputs.acrName
output SERVICE_WEB_NAME string = core.outputs.webAppName
output SERVICE_WEB_URI string = core.outputs.webAppUri
output SERVICE_WEB_IMAGE_NAME string = core.outputs.webAppImageName
output AZURE_STORAGE_ACCOUNT_NAME string = core.outputs.storageAccountName
output AZURE_STORAGE_CONTAINER_NAME string = core.outputs.storageContainerName
