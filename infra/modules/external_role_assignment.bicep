// Cross-scope role assignment helper. Deployed at the resource group of the
// target Cognitive Services account (the AI Foundry / AIServices account
// that exposes both OpenAI chat/image AND the Speech surface). The caller is
// responsible for invoking this module with `scope: resourceGroup(<sub>, <rg>)`.

@description('Name of the Cognitive Services account (AIServices/Foundry) that already exists in the target RG.')
param cognitiveServicesAccountName string

@description('Principal ID of the managed identity to grant the role to.')
param principalId string

@description('Built-in role definition GUID. Examples: 5e0bd9bd-7b93-4f28-af87-19fc36ad61bd (Cognitive Services OpenAI User), 53ca6127-db72-4b80-b1b0-d745d6d5456d (Azure AI User), f2dc8367-1007-4938-bd23-fe263f013447 (Cognitive Services Speech User).')
param roleDefinitionGuid string

resource account 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
  name: cognitiveServicesAccountName
}

resource roleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: account
  name: guid(account.id, principalId, roleDefinitionGuid)
  properties: {
    principalId: principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      roleDefinitionGuid
    )
  }
}

output roleAssignmentId string = roleAssignment.id
