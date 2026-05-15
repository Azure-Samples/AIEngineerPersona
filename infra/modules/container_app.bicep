// The single Children's Story Studio container app.
// Env-var names match what backend/app/config.py and backend/app/storage/blob.py
// actually read at runtime — DO NOT rename without updating the app code.

@description('Azure region.')
param location string

@description('Container App name (e.g. <env>-app).')
param name string

@description('Resource ID of the parent Container Apps Environment.')
param containerAppsEnvironmentId string

@description('Resource ID of the user-assigned managed identity to bind.')
param managedIdentityId string

@description('Client ID of the managed identity. Plumbed to the app as AZURE_CLIENT_ID so DefaultAzureCredential picks the right MI in CAE.')
param managedIdentityClientId string

@description('ACR login server (e.g. <name>.azurecr.io).')
param acrLoginServer string

@description('Optional explicit container image reference. When set (typically by azd as SERVICE_APP_IMAGE_NAME after the first `azd deploy`), this image is used verbatim. When empty (the first `azd up`, before any image has been pushed to ACR), a public placeholder image is used so the Container App can be created — `azd deploy` then builds, pushes, and updates the revision to the real image. After that, azd populates this value on subsequent provisions.')
param appImageName string = ''

@description('Public placeholder image used when appImageName is empty AND the ACR repository has no image yet. Must be publicly pullable without auth.')
param placeholderImage string = 'mcr.microsoft.com/k8se/quickstart:latest'

@description('CPU cores per replica (e.g. 1.0).')
param cpu string

@description('Memory per replica (e.g. 2Gi).')
param memory string

@description('Minimum replica count.')
@minValue(0)
param minReplicas int = 1

@description('Maximum replica count.')
@minValue(1)
param maxReplicas int = 3

@description('Storage account name. Plumbed to the app as AZURE_STORAGE_ACCOUNT_NAME (BlobBackend constructs https://<name>.blob.core.windows.net/ from this).')
param storageAccountName string

@description('Blob container name. Plumbed to the app as AZURE_STORAGE_CONTAINER_NAME. Default matches BlobBackend default.')
param storageContainerName string = 'demo-stories'

@description('Foundry project endpoint. AIEngineerPersona uses the SHORT account-level form (https://<acct>.services.ai.azure.com/) — agent-framework OpenAIChatClient builds the Responses URL from this.')
param foundryProjectEndpoint string

@description('Foundry chat model deployment name (e.g. gpt-5.2). Plumbed as FOUNDRY_MODEL_DEPLOYMENT_NAME.')
param foundryModelDeploymentName string

@description('Foundry image model deployment name (e.g. gpt-image-1.5). Plumbed as FOUNDRY_IMAGE_MODEL_DEPLOYMENT_NAME.')
param foundryImageModelDeploymentName string

@description('Azure region for the colocated Speech resource (e.g. eastus2). Plumbed as AZURE_SPEECH_REGION.')
param azureSpeechRegion string

@description('Public Speech TTS endpoint (e.g. https://eastus2.tts.speech.microsoft.com). Plumbed as AZURE_SPEECH_ENDPOINT.')
param azureSpeechEndpoint string

@description('Full ARM resource ID of the Cognitive Services account that exposes the Speech surface (typically the Foundry / AIServices account). Plumbed as AZURE_SPEECH_RESOURCE_ID for AAD-token speech auth.')
param azureSpeechResourceId string

@description('Application Insights connection string. Empty disables telemetry export.')
@secure()
param appInsightsConnectionString string

@description('CORS allow-origin. The SPA is served from the same origin as the API, so this only matters for local development against the deployed API. FastAPI uses allow_credentials=true, which forbids "*", so set to a concrete origin or leave at the localhost dev default.')
param corsOrigin string = 'http://localhost:5173'

@description('Container target port. Matches Dockerfile EXPOSE.')
param targetPort int = 8000

// ---------------------------------------------------------------------------
// Container Apps Easy Auth — wires the Entra client secret as a Container
// App secret named `entraClientSecretName`. The companion authConfig
// resource (modules/container_app_auth.bicep) references this secret by
// name. Both are gated on `enableEntraAuth` so they appear and disappear
// together — eliminating the dangling-reference foot-gun.
// ---------------------------------------------------------------------------

@description('Master switch for Container Apps Easy Auth (Microsoft Entra). When false, no auth is enforced. When true, an Entra client secret is mounted as a Container App secret and the authConfig is wired up by the parent module.')
param enableEntraAuth bool = false

@description('Entra app registration client secret. Required when enableEntraAuth is true.')
@secure()
param entraClientSecret string = ''

@description('Name of the Container App secret holding the Entra client secret. Must match clientSecretSettingName in container_app_auth.bicep.')
#disable-next-line secure-secrets-in-params
param entraClientSecretName string = 'entra-client-secret'

var entraSecretEntries = enableEntraAuth ? [
  {
    name: entraClientSecretName
    value: entraClientSecret
  }
] : []

// Image resolution: prefer the explicit override (set by azd as
// SERVICE_APP_IMAGE_NAME after `azd deploy`), fall back to the public
// placeholder for the very first `azd up` when the ACR repo is empty.
// `azd deploy` will then build, push, and update the revision to the real
// `<acrLoginServer>/<imageName>:<imageTag>` image, AND populate
// SERVICE_APP_IMAGE_NAME in the azd env so subsequent `azd provision` runs
// don't regress the image back to the placeholder.
var resolvedImage = !empty(appImageName) ? appImageName : placeholderImage
var usingAcrImage = !empty(appImageName)

resource containerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: name
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${managedIdentityId}': {}
    }
  }
  properties: {
    managedEnvironmentId: containerAppsEnvironmentId
    configuration: {
      activeRevisionsMode: 'Single'
      secrets: entraSecretEntries
      ingress: {
        external: true
        targetPort: targetPort
        transport: 'auto'
        allowInsecure: false
        traffic: [
          {
            latestRevision: true
            weight: 100
          }
        ]
      }
      // Only declare ACR as a registry when we're actually pulling from it.
      // The placeholder image is anonymously pullable from MCR, so no registry
      // entry is needed for the bootstrap revision. After `azd deploy`, the
      // resolved image lives in ACR and the registry block is required so the
      // UAMI authenticates the pull.
      registries: usingAcrImage ? [
        {
          server: acrLoginServer
          identity: managedIdentityId
        }
      ] : []
    }
    template: {
      containers: [
        {
          name: 'app'
          image: resolvedImage
          resources: {
            cpu: json(cpu)
            memory: memory
          }
          env: [
            // ── Storage backend ─────────────────────────────────────────
            {
              name: 'STORAGE_BACKEND'
              value: 'blob'
            }
            {
              // BlobBackend reads AZURE_STORAGE_ACCOUNT_NAME (note the _NAME
              // suffix — different from marketing-campaign's AZURE_STORAGE_ACCOUNT).
              // See backend/app/storage/blob.py:55.
              name: 'AZURE_STORAGE_ACCOUNT_NAME'
              value: storageAccountName
            }
            {
              name: 'AZURE_STORAGE_CONTAINER_NAME'
              value: storageContainerName
            }
            // ── Identity ────────────────────────────────────────────────
            {
              // Tells DefaultAzureCredential which UAMI to use when multiple
              // are bound to the container.
              name: 'AZURE_CLIENT_ID'
              value: managedIdentityClientId
            }
            // ── Foundry / Azure OpenAI ──────────────────────────────────
            {
              // AIEngineerPersona uses the SHORT account-level form (no
              // /api/projects/<p>/ suffix). Agent-framework's OpenAIChatClient
              // builds the Responses URL from the account endpoint + the
              // deployment name passed via FOUNDRY_MODEL_DEPLOYMENT_NAME.
              name: 'FOUNDRY_PROJECT_ENDPOINT'
              value: foundryProjectEndpoint
            }
            {
              name: 'FOUNDRY_MODEL_DEPLOYMENT_NAME'
              value: foundryModelDeploymentName
            }
            {
              name: 'FOUNDRY_IMAGE_MODEL_DEPLOYMENT_NAME'
              value: foundryImageModelDeploymentName
            }
            // ── Speech ──────────────────────────────────────────────────
            {
              name: 'AZURE_SPEECH_REGION'
              value: azureSpeechRegion
            }
            {
              name: 'AZURE_SPEECH_ENDPOINT'
              value: azureSpeechEndpoint
            }
            {
              name: 'AZURE_SPEECH_RESOURCE_ID'
              value: azureSpeechResourceId
            }
            // ── Telemetry ───────────────────────────────────────────────
            {
              name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
              value: appInsightsConnectionString
            }
            {
              name: 'ENABLE_INSTRUMENTATION'
              value: 'true'
            }
            {
              name: 'ENABLE_SENSITIVE_DATA'
              value: 'false'
            }
            {
              name: 'OTEL_SERVICE_NAME'
              value: 'children-story-studio'
            }
            // ── CORS ────────────────────────────────────────────────────
            {
              name: 'CORS_ORIGIN'
              value: corsOrigin
            }
          ]
          probes: [
            {
              type: 'Startup'
              httpGet: {
                path: '/api/health'
                port: targetPort
                scheme: 'HTTP'
              }
              initialDelaySeconds: 5
              periodSeconds: 10
              timeoutSeconds: 5
              failureThreshold: 30
            }
            {
              type: 'Readiness'
              httpGet: {
                path: '/api/health'
                port: targetPort
                scheme: 'HTTP'
              }
              periodSeconds: 10
              timeoutSeconds: 5
              failureThreshold: 3
            }
            {
              type: 'Liveness'
              httpGet: {
                path: '/api/health'
                port: targetPort
                scheme: 'HTTP'
              }
              periodSeconds: 30
              timeoutSeconds: 5
              failureThreshold: 3
            }
          ]
        }
      ]
      scale: {
        minReplicas: minReplicas
        maxReplicas: maxReplicas
        rules: [
          {
            name: 'http-scaler'
            http: {
              metadata: {
                concurrentRequests: '50'
              }
            }
          }
        ]
      }
    }
  }
}

output id string = containerApp.id
output name string = containerApp.name
output fqdn string = containerApp.properties.configuration.ingress.fqdn
output url string = 'https://${containerApp.properties.configuration.ingress.fqdn}'
