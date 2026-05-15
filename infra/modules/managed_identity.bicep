// User-assigned managed identity used by the container app.
// Used for: ACR pulls, Storage Blob Data Contributor, Cognitive Services
// OpenAI User (Foundry), Azure AI User (Foundry), Cognitive Services Speech
// User (Foundry/Speech account), and DefaultAzureCredential inside the running
// app (via AZURE_CLIENT_ID env var on the container app).

@description('Azure region.')
param location string

@description('Managed identity name.')
param name string

resource managedIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: name
  location: location
}

output id string = managedIdentity.id
output name string = managedIdentity.name
output principalId string = managedIdentity.properties.principalId
output clientId string = managedIdentity.properties.clientId
