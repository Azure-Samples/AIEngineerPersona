// Log Analytics workspace — backs Container Apps Environment diagnostics.
// PerGB2018 is the standard pay-as-you-go SKU.

@description('Azure region.')
param location string

@description('Workspace name.')
param name string

@description('Retention in days. 30 keeps the demo cheap.')
param retentionInDays int = 30

resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: name
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: retentionInDays
    features: {
      enableLogAccessUsingOnlyResourcePermissions: true
    }
  }
}

output id string = workspace.id
output name string = workspace.name
output customerId string = workspace.properties.customerId
