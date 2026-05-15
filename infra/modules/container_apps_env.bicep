// Container Apps Environment, bound to the Log Analytics workspace.
// The single AIEngineerPersona container app lives inside this environment.
//
// VNet integration is OPTIONAL: pass `infrastructureSubnetId` (the
// resource ID of a /23+ subnet delegated to Microsoft.App/environments)
// to put the CAE inside a custom VNet. Empty string = no VNet
// integration.

@description('Azure region.')
param location string

@description('CAE name.')
param name string

@description('Name of the Log Analytics workspace in this resource group to bind for diagnostics.')
param logAnalyticsWorkspaceName string

@description('Optional: resource ID of the infrastructure subnet for VNet integration. Must be /23 or larger and delegated to Microsoft.App/environments. Empty = no VNet integration.')
param infrastructureSubnetId string = ''

@description('When VNet-integrated, controls whether the CAE has a public ingress endpoint. true = public ingress (still routed via VNet egress); false = internal-only (apps reachable only inside the VNet). Ignored when infrastructureSubnetId is empty.')
param internalLoadBalancer bool = false

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: logAnalyticsWorkspaceName
}

var vnetConfig = empty(infrastructureSubnetId)
  ? null
  : {
      infrastructureSubnetId: infrastructureSubnetId
      internal: internalLoadBalancer
    }

resource containerEnv 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: name
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
    vnetConfiguration: vnetConfig
  }
}

output id string = containerEnv.id
output name string = containerEnv.name
output defaultDomain string = containerEnv.properties.defaultDomain
