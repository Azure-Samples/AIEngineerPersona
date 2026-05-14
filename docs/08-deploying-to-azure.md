# Deploying to Azure

This guide deploys Children's Story Studio to **Azure App Service for Linux** as a single custom container, using **Azure Developer CLI (`azd`)** and the Bicep templates in [infra/](../infra).

## What gets deployed

```
Resource group: rg-<env-name>
├── Azure Container Registry (Basic)        — stores the app image
├── Log Analytics + Application Insights    — diagnostics
├── App Service Plan (Linux, B2 default)
└── Web App (custom container, system MI)   — pulls image from ACR via managed identity
```

Two existing resources are **reused** (not created): your Azure AI Foundry project and your Azure AI Speech account. The deployment grants the web app's managed identity the runtime roles it needs on each:

| Resource           | Role granted to App Service MI            |
| ------------------ | ----------------------------------------- |
| Foundry account    | Azure AI User, Cognitive Services OpenAI User |
| Speech account     | Cognitive Services Speech User            |

## Prerequisites

- **Azure subscription** with permission to create resources and assign RBAC roles
- [**Azure Developer CLI**](https://aka.ms/azd-install) (`azd`) — `brew install azure-dev` on macOS
- **Docker Desktop** running locally (azd builds the image on your machine before pushing)
- An existing **Azure AI Foundry** project with `gpt-4o` (or similar) and `gpt-image-1` model deployments
- An existing **Azure AI Speech** account in the region you plan to use

## One-time setup

```bash
# From the repo root
azd auth login

# Create a new azd environment (pick any short name, e.g. "story-prod")
azd env new story-prod
azd env select story-prod

# Required configuration ─ adjust to your existing Foundry + Speech resources
azd env set AZURE_LOCATION                      eastus2
azd env set FOUNDRY_RESOURCE_GROUP              <rg-of-your-foundry-account>
azd env set FOUNDRY_ACCOUNT_NAME                <your-ai-services-account-name>
azd env set FOUNDRY_PROJECT_ENDPOINT            "https://<acct>.services.ai.azure.com/api/projects/<project>"
azd env set FOUNDRY_MODEL_DEPLOYMENT_NAME       gpt-4o
azd env set FOUNDRY_IMAGE_MODEL_DEPLOYMENT_NAME gpt-image-1
azd env set SPEECH_RESOURCE_GROUP               <rg-of-your-speech-account>
azd env set SPEECH_ACCOUNT_NAME                 <your-speech-account-name>
azd env set AZURE_SPEECH_REGION                 eastus

# (Optional) Also grant your own user account RBAC on Foundry/Speech for local dev
azd env set AZURE_PRINCIPAL_ID $(az ad signed-in-user show --query id -o tsv)
```

## Deploy

```bash
azd up
```

`azd up` will:

1. Provision all resources in [main.bicep](../infra/main.bicep) (~3-5 min).
2. Run the postprovision hook ([scripts/azd-build-and-deploy.sh](../scripts/azd-build-and-deploy.sh)), which:
   - logs in to the new ACR,
   - builds the Docker image locally for `linux/amd64`,
   - pushes it to the registry,
   - points the Web App at the new image and restarts it.

When it's done, the script prints the public URL — open it in a browser.

> **Why a hook?** azd's `services:` block with `docker:` is only valid for Container Apps / AKS. For App Service custom containers there's no built-in service type, so the hook handles build/push/deploy directly. The override under `workflows.up` in [azure.yaml](../azure.yaml) prevents azd from running its default `package`/`deploy` steps (which would fail with `no package artifacts found`).

## Subsequent code-only deploys

Use `azd provision` — it re-runs the postprovision hook, which is what actually pushes the new image. Bicep deploys are idempotent, so this is cheap when infra hasn't changed:

```bash
azd provision
```

To tear everything down:

```bash
azd down --purge --force
```

## How it fits together

- **Single origin.** The container's [Dockerfile](../Dockerfile) builds the React SPA in a Node stage, then copies `dist/` into the Python runtime image. FastAPI serves the SPA from `/` and the API from `/api/*`, so there's no CORS to configure and Server-Sent Events work natively.
- **Managed identity, no secrets.** The web app has a system-assigned managed identity. Bicep grants it `AcrPull` on the registry (so App Service can pull the image) and the runtime roles listed above on Foundry + Speech. The Python code already uses `DefaultAzureCredential`, which picks up the MI automatically.
- **Persistent demo stories.** Saved stories (`POST /api/demo-stories`) are written under `DEMO_STORIES_DIR=/home/data/demo-stories`. App Service Linux mounts `/home` as a built-in persistent volume that survives restarts and is shared across all instances on the plan — no separate Storage Account needed. On first start, [scripts/entrypoint.sh](../scripts/entrypoint.sh) seeds the directory with the bundled sample stories from the image (no-clobber, so user content is never overwritten).
- **Health probes.** App Service pings `/api/health` (handler in [backend/app/main.py](../backend/app/main.py)). If your container fails to start, that endpoint is the first thing to check in the App Service logs.

## Configuration knobs

All exposed via `azd env set <KEY> <value>` and re-applied on the next `azd up` / `azd provision`:

| Setting                              | Default                  | Notes                                         |
| ------------------------------------ | ------------------------ | --------------------------------------------- |
| `AZURE_LOCATION`                     | (prompted)               | Region for new resources.                     |
| `AZURE_PRINCIPAL_ID`                 | _(empty)_                | Optional dev user to also grant RBAC.         |
| `FOUNDRY_MODEL_DEPLOYMENT_NAME`      | `gpt-4o`                 |                                                |
| `FOUNDRY_IMAGE_MODEL_DEPLOYMENT_NAME`| `gpt-image-1`            |                                                |

Plan SKU is hard-coded to `B2` in [infra/core.bicep](../infra/core.bicep) — change `appServicePlanSku` (allowed: B2/B3/P0v3/P1v3/P2v3/P3v3) for production workloads. **B-tier plans don't honour `alwaysOn`** the same way as Premium; for serious demos use at least `P0v3`.

## Troubleshooting

- **Container won't start / `WEBSITES_PORT` errors** — Check that `WEBSITES_PORT=8000` is present under App Service → Configuration. The Bicep sets it; if you edited settings manually, it may have been removed.
- **`DefaultAzureCredential` failures from logs** — Confirm the role assignments landed on the Foundry / Speech accounts: `az role assignment list --assignee <web-app-MI-objectId> --all`.
- **Image pull failures (`MANIFEST_UNKNOWN`)** — The web app starts with a placeholder image and only switches to the real one after the postprovision hook runs. If the hook failed (look for errors after Bicep finished), re-run `azd provision`.
- **Demo stories disappearing** — Verify `WEBSITES_ENABLE_APP_SERVICE_STORAGE=true` and `DEMO_STORIES_DIR=/home/data/demo-stories` are set in App Service → Configuration. The entrypoint script logs `[entrypoint] Seeding demo stories...` on startup; check App Service log stream.
- **SSE connection drops** — App Service Linux supports streaming, but make sure you're not behind a proxy that buffers responses. The SPA uses fetch streaming, not EventSource, so any HTTP/1.1+ origin works.
