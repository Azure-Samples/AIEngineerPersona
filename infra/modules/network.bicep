// VNet + subnets + private DNS zone for blob storage.
//
// CIDR plan (defaults — 1024 addresses total, plenty of headroom):
//   VNet                10.20.0.0/22
//     cae-infra         10.20.0.0/23   (delegated to Microsoft.App/environments)
//     private-endpoints 10.20.2.0/26   (network policies disabled for PE NICs)
//
// Sizing notes:
//   - Consumption-only CAE requires a /23 minimum infrastructure subnet.
//   - PE subnets are tiny — /26 (64 addrs) is overkill for one PE but leaves
//     headroom if we later add PEs for ACR / Speech / Foundry.

@description('Azure region for the VNet and DNS zone link.')
param location string

@description('VNet name.')
param vnetName string

@description('VNet CIDR. Default 10.20.0.0/22.')
param vnetAddressPrefix string = '10.20.0.0/22'

@description('Container Apps Environment infrastructure subnet name.')
param caeSubnetName string = 'cae-infra'

@description('CAE infrastructure subnet CIDR. Consumption-only CAE requires /23 minimum.')
param caeSubnetAddressPrefix string = '10.20.0.0/23'

@description('Private endpoints subnet name.')
param privateEndpointsSubnetName string = 'private-endpoints'

@description('Private endpoints subnet CIDR.')
param privateEndpointsSubnetAddressPrefix string = '10.20.2.0/26'

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: vnetName
  location: location
  properties: {
    addressSpace: {
      addressPrefixes: [
        vnetAddressPrefix
      ]
    }
    subnets: [
      {
        name: caeSubnetName
        properties: {
          addressPrefix: caeSubnetAddressPrefix
          delegations: [
            {
              name: 'cae-delegation'
              properties: {
                serviceName: 'Microsoft.App/environments'
              }
            }
          ]
        }
      }
      {
        name: privateEndpointsSubnetName
        properties: {
          addressPrefix: privateEndpointsSubnetAddressPrefix
          // Required so PEs can be created in this subnet without NSG-applied
          // network policies interfering with the PE NICs.
          privateEndpointNetworkPolicies: 'Disabled'
        }
      }
    ]
  }
}

// `existing` lookups give us typed subnet references for clean outputs that
// don't depend on subnet array ordering inside the VNet declaration.
resource caeSubnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  parent: vnet
  name: caeSubnetName
}

resource privateEndpointsSubnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  parent: vnet
  name: privateEndpointsSubnetName
}

// Private DNS zone for blob storage privatelink. Must be exactly this name —
// it's the well-known privatelink hostname for blob storage.
resource blobPrivateDnsZone 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  #disable-next-line no-hardcoded-env-urls
  name: 'privatelink.blob.core.windows.net'
  location: 'global'
}

// Link the zone to the VNet so the apps' DNS resolves blob hostnames to private IPs.
// `registrationEnabled: false` because we only want the zone-group-managed A
// record for the storage account; nothing in this VNet should auto-register.
resource blobPrivateDnsZoneLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: blobPrivateDnsZone
  name: '${vnetName}-link'
  location: 'global'
  properties: {
    virtualNetwork: {
      id: vnet.id
    }
    registrationEnabled: false
  }
}

output vnetId string = vnet.id
output vnetName string = vnet.name
output caeSubnetId string = caeSubnet.id
output privateEndpointsSubnetId string = privateEndpointsSubnet.id
output blobPrivateDnsZoneId string = blobPrivateDnsZone.id
output blobPrivateDnsZoneName string = blobPrivateDnsZone.name
