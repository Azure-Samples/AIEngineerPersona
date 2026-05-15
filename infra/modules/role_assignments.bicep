// Role assignments scoped to resources in this resource group: storage account
// (Storage Blob Data Contributor) and ACR (AcrPull). Cross-RG/subscription
// grants on the Foundry/Speech account are handled by external_role_assignment.bicep.

@description('Principal ID of the user-assigned managed identity to grant roles to.')
param managedIdentityPrincipalId string

@description('Storage account name (must already exist in this RG).')
param storageAccountName string

@description('ACR name (must already exist in this RG).')
param acrName string

// Built-in role definition GUIDs — stable across all Azure clouds.
// Reference:
//   Storage Blob Data Contributor: ba92f5b4-2d11-453d-a403-e96b0029c9fe
//   AcrPull:                       7f951dda-4ed3-4680-a7ca-43fe172d538d
var storageBlobDataContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

resource acr 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' existing = {
  name: acrName
}

resource storageBlobDataContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storageAccount
  name: guid(storageAccount.id, managedIdentityPrincipalId, storageBlobDataContributorRoleId)
  properties: {
    principalId: managedIdentityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      storageBlobDataContributorRoleId
    )
  }
}

resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acr
  name: guid(acr.id, managedIdentityPrincipalId, acrPullRoleId)
  properties: {
    principalId: managedIdentityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      acrPullRoleId
    )
  }
}

output storageRoleAssignmentId string = storageBlobDataContributor.id
output acrPullRoleAssignmentId string = acrPull.id
