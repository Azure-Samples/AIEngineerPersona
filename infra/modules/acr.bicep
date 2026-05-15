// Azure Container Registry. Admin user disabled — pulls go through the
// shared user-assigned managed identity (AcrPull granted in role_assignments).

@description('Azure region.')
param location string

@description('Registry name. 5–50 alphanumeric, lowercase, globally unique.')
@minLength(5)
@maxLength(50)
param name string

@description('Registry SKU. Basic is fine for the demo; bump to Standard/Premium for geo-replication.')
@allowed([
  'Basic'
  'Standard'
  'Premium'
])
param sku string = 'Basic'

resource acr 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' = {
  name: name
  location: location
  sku: {
    name: sku
  }
  properties: {
    adminUserEnabled: false
    publicNetworkAccess: 'Enabled'
    anonymousPullEnabled: false
  }
}

output id string = acr.id
output name string = acr.name
output loginServer string = acr.properties.loginServer
