// rbac-speech.bicep — grants the App Service managed identity the
// "Cognitive Services Speech User" role on an existing Speech account.

param speechAccountName string
param principalId string
@description('Optional second principal (e.g. a developer) to receive the same role.')
param additionalPrincipalId string = ''

resource speech 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
  name: speechAccountName
}

// "Cognitive Services Speech User" — required for AAD-based TTS calls.
var speechUserRoleId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'f2dc8367-1007-4938-bd23-fe263f013447')

resource appSpeechUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(speech.id, principalId, 'SpeechUser')
  scope: speech
  properties: {
    roleDefinitionId: speechUserRoleId
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

resource devSpeechUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(additionalPrincipalId)) {
  name: guid(speech.id, additionalPrincipalId, 'SpeechUser')
  scope: speech
  properties: {
    roleDefinitionId: speechUserRoleId
    principalId: additionalPrincipalId
    principalType: 'User'
  }
}
