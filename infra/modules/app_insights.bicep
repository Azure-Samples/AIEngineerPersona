// Application Insights, workspace-based. Connection string is consumed by
// the container app via the APPLICATIONINSIGHTS_CONNECTION_STRING env var
// (read by Agent Framework's observability layer + OpenTelemetry exporter).

@description('Azure region.')
param location string

@description('App Insights component name.')
param name string

@description('Resource ID of the Log Analytics workspace to bind to.')
param logAnalyticsWorkspaceId string

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: name
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalyticsWorkspaceId
    IngestionMode: 'LogAnalytics'
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
  }
}

output id string = appInsights.id
output connectionString string = appInsights.properties.ConnectionString
output instrumentationKey string = appInsights.properties.InstrumentationKey
