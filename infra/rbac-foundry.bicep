// rbac-foundry.bicep — grants the App Service managed identity the runtime
// roles it needs to invoke models on an *existing* Azure AI Foundry account.
//
// Roles assigned (at the Cognitive Services account scope):
//   - "Azure AI User"         (53ca6127-db72-4b80-b1b0-d745d6d5456d)
//       Required by Azure AI Foundry / Agent Framework for project + agent
//       runtime operations.
//   - "Cognitive Services OpenAI User" (5e0bd9bd-7b93-4f28-af87-19fc36ad61bd)
//       Required to call the deployed chat / image models on the account.

param foundryAccountName string
param principalId string
@description('Optional second principal (e.g. a developer) to receive the same roles.')
param additionalPrincipalId string = ''

resource foundry 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
  name: foundryAccountName
}

var azureAiUserRoleId          = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '53ca6127-db72-4b80-b1b0-d745d6d5456d')
var cognitiveOpenAiUserRoleId  = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd')

// ── App Service MI ─────────────────────────────────────────────────────────
resource appAiUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundry.id, principalId, 'AzureAIUser')
  scope: foundry
  properties: {
    roleDefinitionId: azureAiUserRoleId
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

resource appOpenAiUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundry.id, principalId, 'CognitiveServicesOpenAIUser')
  scope: foundry
  properties: {
    roleDefinitionId: cognitiveOpenAiUserRoleId
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

// ── Optional dev principal (User) ──────────────────────────────────────────
resource devAiUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(additionalPrincipalId)) {
  name: guid(foundry.id, additionalPrincipalId, 'AzureAIUser')
  scope: foundry
  properties: {
    roleDefinitionId: azureAiUserRoleId
    principalId: additionalPrincipalId
    principalType: 'User'
  }
}

resource devOpenAiUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(additionalPrincipalId)) {
  name: guid(foundry.id, additionalPrincipalId, 'CognitiveServicesOpenAIUser')
  scope: foundry
  properties: {
    roleDefinitionId: cognitiveOpenAiUserRoleId
    principalId: additionalPrincipalId
    principalType: 'User'
  }
}
