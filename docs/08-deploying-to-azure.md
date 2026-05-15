# Deploying to Azure

[← Back to README](../README.md)

This guide deploys Children's Story Studio to **Azure Container Apps** as a single custom container, using the **Azure Developer CLI (`azd`)** and the Bicep templates in [`infra/`](../infra). One command — `azd up` — provisions every resource and pushes the image. No local Docker daemon required.

> **Which branch should I deploy?** Either works:
> - **`main`** — the minimal workshop starter (fewer features, smaller infra footprint, easiest to read)
> - **`all-features`** — the fully-built reference application (everything from every guide enabled)

---

## Table of Contents

- [What gets deployed](#what-gets-deployed)
- [Prerequisites](#prerequisites)
- [Sample config files in this repo](#sample-config-files-in-this-repo)
- [One-time setup](#one-time-setup)
- [Deploy](#deploy)
- [Subsequent deploys](#subsequent-deploys)
- [Optional: Microsoft Entra sign-in (Easy Auth)](#optional-microsoft-entra-sign-in-easy-auth)
- [Configuration reference](#configuration-reference)
- [Tear down](#tear-down)
- [Troubleshooting](#troubleshooting)

---

## What gets deployed

[`infra/main.bicep`](../infra/main.bicep) is **subscription-scoped** — it creates the resource group itself, so the entire stack is one `azd up` away.

```
Subscription
└── Resource group: rg-<env-name>            (created by Bicep)
    ├── Virtual network (10.20.0.0/22)       — CAE-infra + private-endpoints subnets
    ├── Azure Container Registry (Basic)     — stores the app image
    ├── Storage Account                      — persisted demo stories (Blob, private endpoint)
    ├── Log Analytics + Application Insights — diagnostics + OTEL ingestion
    ├── User-assigned managed identity       — RBAC principal for the Container App
    ├── Container Apps Environment           — runs in the VNet
    └── Container App: <env>-app             — pulls image from ACR, mounted to MI
```

**Two pre-existing resources are reused** (the deploy does not create them — it grants the app's managed identity runtime roles on each):

| Resource          | Roles granted to the Container App's managed identity |
| ----------------- | ----------------------------------------------------- |
| Foundry account   | `Azure AI User`, `Cognitive Services OpenAI User`     |
| Speech account    | `Cognitive Services Speech User`                      |
| Storage account   | `Storage Blob Data Contributor` (on the new account)  |
| Container Registry| `AcrPull` (on the new ACR)                            |

The container's [`Dockerfile`](../Dockerfile) builds the React SPA in a Node stage and copies it into the Python runtime image, so FastAPI serves both the SPA (`/`) and the API (`/api/*`) from one origin — no CORS to configure and Server-Sent Events work natively.

---

## Prerequisites

| Tool | Required for | Notes |
| ---- | ------------ | ----- |
| **Azure subscription** | All deploys | You need permission to create resources, assign RBAC roles, and (if using Entra Easy Auth) create app registrations. |
| **[Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli)** | All deploys | `az login` is used for both the deploy and the Entra app-registration script. |
| **[Azure Developer CLI](https://aka.ms/azd-install)** (`azd`) | All deploys | macOS: `brew install azure-dev`. Windows: `winget install microsoft.azd`. |
| **`jq`** | Entra Easy Auth script only | macOS: `brew install jq`. |
| **Existing Azure AI Foundry account + project** | All deploys | With a chat-model deployment (e.g. `gpt-5.2` / `gpt-5.4`) and an image-model deployment (e.g. `gpt-image-1.5`). See [Prerequisites & Environment Setup](01-prerequisites-and-setup.md) for provisioning steps. |
| **Existing Azure AI Speech account** | TTS feature only | Or share the same multi-service AIServices account as Foundry by setting `AZURE_SPEECH_RESOURCE_ID` to the Foundry resource ID. |
| **Docker** | _Not required_ | `azure.yaml` declares `remoteBuild: true`, so Azure Container Registry builds the image remotely on `linux/amd64`. This sidesteps Mac M1 cross-platform headaches. |

---

## Sample config files in this repo

The repo ships three template files — each maps to a different stage of the workflow. Knowing which goes where prevents a lot of "why is my variable being ignored" pain.

| File | Used by | What it's for |
| ---- | ------- | ------------- |
| [`backend/.env.example`](../backend/.env.example) | **Local dev only** (`uvicorn` on your laptop) | Copy to `backend/.env` and fill in. The Container App **never reads this file** — runtime env vars are injected by Bicep. |
| [`infra/scripts/azd-env.example.sh`](../infra/scripts/azd-env.example.sh) | **Deploy only** (`azd up`) | Copy to `infra/scripts/azd-env.local.sh` (gitignored), edit the placeholders, and `bash` it once. It runs all the `azd env set` commands in one go so you don't have to remember them. |
| [`infra/main.parameters.json`](../infra/main.parameters.json) | **Bicep** (read by `azd up`) | Don't edit this. It maps Bicep parameters to azd-env values like `${AZURE_STORAGE_ACCOUNT_NAME}` — the variables you set via the script above. |
| [`azure.yaml`](../azure.yaml) | **azd** (read by every `azd` command) | The `azd` project definition. Already configured for Container Apps with remote-build. |

> **What about the `.azure/` folder?** You'll see it appear in the repo root after your first `azd env new`. It contains per-environment config (`.azure/<env>/.env`, `.azure/<env>/config.json`) that **`azd` generates and owns** — never hand-edit it. It's intentionally gitignored (`.azure/.gitignore` contains `*`) because it ends up holding subscription IDs, resource IDs, and — if you enable Entra Easy Auth — your `ENTRA_CLIENT_SECRET`. Three things write to it:
> 1. `azd env new <name>` creates the subdirectory.
> 2. `azd env set KEY value` (what the sample script above runs) populates it with your input.
> 3. `azd up` appends Bicep outputs (`SERVICE_APP_FQDN`, `AZURE_RESOURCE_GROUP`, etc.) so subsequent commands and the postprovision hook can read them.
>
> If you ever need to inspect what's set: `azd env get-values`. If you need to start over: `rm -rf .azure/<env>` and re-run `azd env new`.

---

## One-time setup

```bash
# From the repo root
azd auth login
az login                             # also needed — the Bicep deploy uses az too

# 1. Create a fresh azd environment (any short name; becomes part of resource names)
azd env new childrenstory
azd env select childrenstory

# 2. Populate every azd env var the deploy needs.
#    - Copy the sample script and edit the placeholders (subscription IDs,
#      Foundry account names, region, etc.).
cp infra/scripts/azd-env.example.sh infra/scripts/azd-env.local.sh
$EDITOR infra/scripts/azd-env.local.sh
bash  infra/scripts/azd-env.local.sh
```

> **What the script writes.** All values land in `.azure/childrenstory/.env` (gitignored). To inspect what's actually set, run `azd env get-values`. To change one value later, run `azd env set KEY value` and the next `azd up` / `azd provision` picks it up.

---

## Deploy

```bash
azd up
```

`azd up` runs end-to-end:

1. **Provision** — `infra/main.bicep` (~3-7 min on first run): VNet, ACR, Log Analytics, App Insights, Storage, managed identity, Container Apps Environment, and the Container App itself (using `mcr.microsoft.com/k8se/quickstart` as a placeholder image since the ACR is empty).
2. **Deploy** — ACR Tasks builds the image remotely on `linux/amd64` from the [`Dockerfile`](../Dockerfile), pushes it to the new registry, then updates the Container App revision to point at it.
3. **Postprovision hook** — prints the public URL: `https://<env>-app.<unique>.<region>.azurecontainerapps.io/`.

When the command finishes, the URL above will load the SPA. The app self-seeds the `demo-stories` blob container on first boot via `seed_demo_stories_if_empty()`, so canned demo stories are available immediately.

---

## Subsequent deploys

Different commands for different change types:

| Change | Command | What runs |
| ------ | ------- | --------- |
| App code only (Python or React) | `azd deploy` | ACR remote build + Container App revision update. ~2 min. |
| Bicep / infra change | `azd provision` | Re-runs Bicep (idempotent — no-op if nothing changed). |
| Both | `azd up` | Provision then deploy. |
| Just one azd env var (e.g. switch model) | `azd env set KEY value && azd provision` | Bicep applies the new container env var. |

---

## Optional: Microsoft Entra sign-in (Easy Auth)

Off by default — the app is publicly reachable. To require Entra sign-in (single-tenant) on every request:

```bash
# 1. After the first `azd up` you have an FQDN. Get it:
FQDN=$(azd env get-value SERVICE_APP_FQDN)

# 2. Run the helper to create (or reuse) an Entra app registration with the
#    correct redirect URI. Idempotent. Mints a client secret only on first run
#    (or with --rotate-secret).
bash infra/scripts/create_entra_app_reg.sh --fqdn "$FQDN"

# 3. Copy the four ENTRA_* values it prints and feed them to azd:
azd env set ENABLE_ENTRA_AUTH true
azd env set ENTRA_CLIENT_ID     <from script output>
azd env set ENTRA_CLIENT_SECRET <from script output>   # one-time — save it now
azd env set ENTRA_TENANT_ID     <from script output>

# 4. Re-provision so the Container App's auth config is updated.
azd provision
```

The script requires the `Application.ReadWrite.All` Graph permission on your Entra account (Application Administrator or Cloud Application Administrator role). After provisioning, `/api/health` stays anonymous (200) but every other route returns 401 → 302 to the Entra sign-in page on a browser navigation.

To rotate the client secret later: `bash infra/scripts/create_entra_app_reg.sh --fqdn "$FQDN" --rotate-secret` then re-set `ENTRA_CLIENT_SECRET` and re-provision.

---

## Configuration reference

Every value is settable via `azd env set <KEY> <value>`. Bold = required (no default). Defaults shown match [`infra/main.parameters.json`](../infra/main.parameters.json).

### Required

| Variable | Description |
| -------- | ----------- |
| **`AZURE_LOCATION`** | Region for new resources (e.g. `eastus2`). |
| **`AZURE_STORAGE_ACCOUNT_NAME`** | New Storage Account name; globally unique, 3-24 lowercase alphanumeric. |
| **`FOUNDRY_PROJECT_ENDPOINT`** | Short account-level Foundry endpoint, e.g. `https://<account>.services.ai.azure.com/`. |
| **`AZURE_FOUNDRY_RESOURCE_ID`** | ARM resource ID of the existing Foundry account. The deploy grants the app's MI `Azure AI User` + `Cognitive Services OpenAI User` on this. |

### Commonly set

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `FOUNDRY_MODEL_DEPLOYMENT_NAME` | `gpt-5.2` | Chat-model deployment name in your Foundry project. |
| `FOUNDRY_IMAGE_MODEL_DEPLOYMENT_NAME` | `gpt-image-1.5` | Image-model deployment name. |
| `AZURE_SPEECH_RESOURCE_ID` | `""` | ARM ID of the Speech account. Empty → defaults to `AZURE_FOUNDRY_RESOURCE_ID`. |
| `AZURE_SPEECH_REGION` | `eastus2` | Region of your Speech / multi-service account. |
| `AZURE_SPEECH_ENDPOINT` | _(derived)_ | Override the Speech TTS endpoint. Leave empty to derive from region. |
| `RESOURCE_GROUP_NAME` | `rg-<env>` | Override the auto-generated resource group name. |

### Container App scaling

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `CONTAINER_CPU` | `1.0` | CPU cores per replica. |
| `CONTAINER_MEMORY` | `2Gi` | Memory per replica. |
| `MIN_REPLICAS` | `1` | Minimum running replicas (set to `0` to allow scale-to-zero). |
| `MAX_REPLICAS` | `3` | Maximum replicas. |

### Networking (advanced)

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `VNET_NAME` | _(derived)_ | Override VNet name. |
| `VNET_ADDRESS_PREFIX` | `10.20.0.0/22` | VNet CIDR. Must be /22 or larger to fit the Container Apps Environment subnet. |
| `CAE_SUBNET_ADDRESS_PREFIX` | `10.20.0.0/23` | Subnet for Container Apps Environment infrastructure. |
| `PRIVATE_ENDPOINTS_SUBNET_ADDRESS_PREFIX` | `10.20.2.0/26` | Subnet for the storage private endpoint. |

### Entra Easy Auth

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `ENABLE_ENTRA_AUTH` | `false` | Master switch. When `true`, all four `ENTRA_*` values must also be set. |
| `ENTRA_CLIENT_ID` | `""` | App registration client (application) ID. |
| `ENTRA_CLIENT_SECRET` | `""` | App registration client secret. **Treat as a secret.** |
| `ENTRA_TENANT_ID` | _(deploy tenant)_ | Tenant ID for the OIDC issuer. |

---

## Tear down

```bash
azd down --purge --force
```

Deletes the resource group and purge-empties the soft-deleted services (Log Analytics, App Insights, ACR, KeyVault if any). The pre-existing Foundry and Speech accounts are NOT touched — they live in different resource groups.

> **Easy-Auth gotcha:** `azd down` does **not** delete the Entra app registration created by `create_entra_app_reg.sh`. Delete it manually in the Entra portal if you want a clean slate.

---

## Troubleshooting

- **`azd up` errors with `Failed to deploy service "app": no Container App with name … found`** — The first `azd up` is provisioning + deploying together. If provision fails partway, the Container App may not exist yet. Check the Bicep error in the azd output, fix the input that caused it, and re-run `azd up`.

- **`MANIFEST_UNKNOWN` / image pull failures on first revision** — Expected briefly. The Container App is created with a public placeholder image and only switches to the real one after `azd deploy` completes. If you see this in logs after `azd up` finished cleanly, run `azd deploy` again to retry the image push.

- **`DefaultAzureCredential` failures from the running container** — Confirm the role assignments landed on the Foundry / Speech accounts. The user-assigned managed identity name is in `azd env get-value AZURE_MANAGED_IDENTITY_PRINCIPAL_ID`:
  ```bash
  MI=$(azd env get-value AZURE_MANAGED_IDENTITY_PRINCIPAL_ID)
  az role assignment list --assignee "$MI" --all -o table
  ```

- **`Pydantic Invalid JSON: EOF while parsing a string` from the orchestrator/architect** — Reasoning models (gpt-5.x) consume most of the response budget on internal reasoning tokens. The agents in this repo pass an explicit `max_tokens` to leave room for the JSON output; if you've cloned an older fork, bump `max_tokens` on the structured-output `agent.run()` calls to 16k+ for the orchestrator and 24k+ for the architect.

- **SSE story-stream drops after a few seconds in production** — Container Apps supports streaming over HTTP/1.1. If your client is behind a corporate proxy that buffers responses, switch the proxy off or increase its read timeout. The SPA uses fetch streaming (not EventSource), so any HTTP/1.1+ origin works.

- **Easy Auth: 500 from `/.auth/login/aad/callback`** — Almost always either (a) the redirect URI in the Entra app registration doesn't match `https://<fqdn>/.auth/login/aad/callback` exactly (re-run `create_entra_app_reg.sh --fqdn $FQDN` to re-merge), or (b) the client secret in `ENTRA_CLIENT_SECRET` is stale (rotate with `--rotate-secret` and re-set + `azd provision`).

- **Health check** — `GET https://<fqdn>/api/health` should return `200 OK` even when Easy Auth is on. If it doesn't, check the Container App revision logs:
  ```bash
  az containerapp logs show \
    --name "$(azd env get-value SERVICE_APP_NAME)" \
    --resource-group "$(azd env get-value AZURE_RESOURCE_GROUP)" \
    --tail 50 --type console
  ```

[← Back to README](../README.md)
