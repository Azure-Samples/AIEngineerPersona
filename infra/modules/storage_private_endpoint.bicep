// Private Endpoint for the storage account's blob endpoint, plus a DNS zone
// group binding so blob hostnames inside the VNet resolve to the PE's private
// IP.

@description('Azure region.')
param location string

@description('Private endpoint name.')
param peName string

@description('ID of the subnet where the PE NIC will be created.')
param subnetId string

@description('ARM resource ID of the storage account to attach the PE to.')
param storageAccountId string

@description('Resource ID of the privatelink.blob.core.windows.net Private DNS zone.')
param blobPrivateDnsZoneId string

resource privateEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: peName
  location: location
  properties: {
    subnet: {
      id: subnetId
    }
    privateLinkServiceConnections: [
      {
        // Connection name is part of the PE resource shape; doesn't need to
        // be unique outside this PE.
        name: '${peName}-conn'
        properties: {
          privateLinkServiceId: storageAccountId
          // groupIds: which subresource of the target service we're attaching
          // to. For storage accounts: 'blob', 'file', 'queue', 'table', 'web', 'dfs'.
          // We only need 'blob' for this app.
          groupIds: [
            'blob'
          ]
        }
      }
    ]
  }
}

// Bind the PE to the privatelink DNS zone so an A record for the storage
// account is auto-created (and updated if the PE's IP ever changes).
resource privateDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: privateEndpoint
  // The zone-group resource name is conventionally 'default' when there's a
  // single zone bound; that's the pattern Microsoft templates and the portal
  // use.
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'privatelink-blob-core-windows-net'
        properties: {
          privateDnsZoneId: blobPrivateDnsZoneId
        }
      }
    ]
  }
}

output id string = privateEndpoint.id
output name string = privateEndpoint.name
