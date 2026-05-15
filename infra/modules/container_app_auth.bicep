// Container Apps Easy Auth ("authConfigs") for the AIEngineerPersona app.
//
// Sits in a sidecar in front of the app's ingress, redirects unauthenticated
// requests to Microsoft Entra (single-tenant), and injects identity headers
// (X-MS-CLIENT-PRINCIPAL-*) on subsequent requests. Exposes:
//   /.auth/login/aad
//   /.auth/logout
//   /.auth/me           ← the SPA can read claims from here
//
// /api/health is excluded so Container Apps probes (and any external uptime
// check) keep working unauthenticated. The probes themselves are documented
// to hit the container directly and bypass the auth sidecar, but the explicit
// excludedPaths is belt-and-suspenders against future probe-routing changes.

@description('Name of the parent Container App.')
param containerAppName string

@description('Entra app registration client (application) ID.')
param entraClientId string

@description('Entra tenant ID. Single-tenant deployments only — this scopes the OIDC issuer.')
param entraTenantId string

@description('Name of the Container App secret (under properties.configuration.secrets) that holds the Entra client secret value. Must already exist on the parent Container App when this resource is deployed.')
#disable-next-line secure-secrets-in-params
param clientSecretSettingName string = 'entra-client-secret'

@description('HTTP paths excluded from auth. Container Apps probes (and external uptime checks) hit /api/health.')
param excludedPaths array = [
  '/api/health'
]

resource containerApp 'Microsoft.App/containerApps@2024-03-01' existing = {
  name: containerAppName
}

resource authConfig 'Microsoft.App/containerApps/authConfigs@2024-03-01' = {
  parent: containerApp
  name: 'current'
  properties: {
    platform: {
      enabled: true
    }
    globalValidation: {
      unauthenticatedClientAction: 'RedirectToLoginPage'
      redirectToProvider: 'azureactivedirectory'
      excludedPaths: excludedPaths
    }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        registration: {
          clientId: entraClientId
          clientSecretSettingName: clientSecretSettingName
          #disable-next-line no-hardcoded-env-urls
          openIdIssuer: 'https://login.microsoftonline.com/${entraTenantId}/v2.0'
        }
        validation: {
          allowedAudiences: [
            'api://${entraClientId}'
          ]
        }
      }
    }
    login: {
      // Token store is unnecessary for the splash-and-display use case — the
      // SPA only reads /.auth/me claims, never an access/refresh token.
      // Keeping this off avoids needing a storage account dependency for the
      // token cache.
      tokenStore: {
        enabled: false
      }
      preserveUrlFragmentsForLogins: false
    }
  }
}

output id string = authConfig.id
output name string = authConfig.name
