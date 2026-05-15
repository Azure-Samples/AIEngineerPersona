// Storage account + the single blob container the app reads/writes.
// Container name `demo-stories` matches BlobBackend's default
// (backend/app/storage/blob.py:60-64).

@description('Azure region.')
param location string

@description('Storage account name. Must be globally unique, 3–24 lowercase alphanumeric.')
@minLength(3)
@maxLength(24)
param name string

@description('Storage SKU. Standard_LRS is cheap and regional; bump to ZRS for higher durability.')
@allowed([
  'Standard_LRS'
  'Standard_ZRS'
  'Standard_GRS'
  'Standard_RAGRS'
])
param sku string = 'Standard_LRS'

@description('Name of the single blob container the app reads/writes. Must match AZURE_STORAGE_CONTAINER_NAME on the container app (default: demo-stories).')
param containerName string = 'demo-stories'

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: name
  location: location
  sku: {
    name: sku
  }
  kind: 'StorageV2'
  properties: {
    accessTier: 'Hot'
    allowBlobPublicAccess: false
    // BlobBackend uses MI / AAD auth exclusively (DefaultAzureCredential +
    // Storage Blob Data Contributor on the UAMI). Disabling shared-key auth
    // eliminates an attack surface and matches the marketing-campaign posture.
    allowSharedKeyAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    // Data plane is reachable ONLY through the Private Endpoint provisioned
    // by storage_private_endpoint.bicep. ARM control plane is always public;
    // only blob endpoints are locked down.
    publicNetworkAccess: 'Disabled'
    networkAcls: {
      // bypass=AzureServices preserves the trusted-services exception
      // (Event Grid system topic, Defender for Storage, etc.).
      bypass: 'AzureServices'
      defaultAction: 'Deny'
    }
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storageAccount
  name: 'default'
  properties: {
    deleteRetentionPolicy: {
      enabled: true
      days: 7
    }
    containerDeleteRetentionPolicy: {
      enabled: true
      days: 7
    }
  }
}

resource container 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: containerName
  properties: {
    publicAccess: 'None'
  }
}

output id string = storageAccount.id
output name string = storageAccount.name
output blobEndpoint string = storageAccount.properties.primaryEndpoints.blob
output containerName string = container.name
