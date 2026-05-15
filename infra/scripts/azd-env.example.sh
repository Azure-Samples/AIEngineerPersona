#!/usr/bin/env bash
#
# azd-env.example.sh — sample template that populates every Azure Developer CLI
# (azd) environment variable required by infra/main.bicep so you can deploy
# the Children's Story Studio Container App with a single `azd up`.
#
# Why a script?  `infra/main.parameters.json` reads its values from the azd
# environment (e.g. ${AZURE_STORAGE_ACCOUNT_NAME}). Without these set, `azd up`
# either fails or prompts interactively for each value. Setting them up-front
# makes the deploy reproducible.
#
# ─── How to use ───────────────────────────────────────────────────────────────
#
#   1. Make sure you've created an azd environment first:
#        azd env new <env-name>      # e.g. azd env new zavastory
#
#   2. Copy this file to a gitignored working copy and edit the values:
#        cp infra/scripts/azd-env.example.sh infra/scripts/azd-env.local.sh
#        $EDITOR infra/scripts/azd-env.local.sh
#
#   3. Run it from the repo root (the active azd env will receive the values):
#        bash infra/scripts/azd-env.local.sh
#
#   4. Then deploy:
#        azd up
#
# Re-running this script is safe — `azd env set` overwrites existing values.

set -euo pipefail

# ─── Required: confirm an azd environment is selected ────────────────────────
if ! azd env list --output json 2>/dev/null | grep -q '"IsDefault": true'; then
    echo "ERROR: no default azd environment selected." >&2
    echo "Run:  azd env new <env-name>" >&2
    exit 1
fi
echo "[azd-env] active environment: $(azd env get-value AZURE_ENV_NAME)"

# ─── Required: where to deploy ───────────────────────────────────────────────
# Region for the new resource group + Container Apps environment + ACR.
# Pick a region that supports Azure Container Apps and where your AI Foundry
# / Speech resources live (or a region close to them, since cross-region
# traffic between the app and Foundry adds latency).
azd env set AZURE_LOCATION                  "eastus2"

# ─── Required: Storage account for persisted demo stories ────────────────────
# Globally unique, 3-24 lowercase alphanumeric characters. The Bicep template
# creates this account; pick a name that's not already taken in Azure.
azd env set AZURE_STORAGE_ACCOUNT_NAME      "stchildrenstory$(printf '%s' "$RANDOM" | head -c 6)"

# ─── Required: existing Azure AI Foundry account ─────────────────────────────
# The deploy does NOT create a Foundry resource — it reuses one you already
# have so RBAC + model deployments survive between teardowns.
#
# AZURE_FOUNDRY_RESOURCE_ID is the FULL ARM resource ID of the Cognitive
# Services / AIServices account that hosts your project.
#   az cognitiveservices account list -o table
azd env set AZURE_FOUNDRY_RESOURCE_ID       "/subscriptions/<sub-id>/resourceGroups/<foundry-rg>/providers/Microsoft.CognitiveServices/accounts/<foundry-account>"

# FOUNDRY_PROJECT_ENDPOINT is the SHORT account-level endpoint
# (NOT the long /api/projects/<name> form used in the local .env file).
# Format: https://<account>.services.ai.azure.com/
azd env set FOUNDRY_PROJECT_ENDPOINT        "https://<foundry-account>.services.ai.azure.com/"

# Names of the model deployments inside that Foundry account. Defaults match
# the Bicep defaults; override only if your deployment names differ.
azd env set FOUNDRY_MODEL_DEPLOYMENT_NAME       "gpt-5.2"
azd env set FOUNDRY_IMAGE_MODEL_DEPLOYMENT_NAME "gpt-image-1.5"

# ─── Required (only if you want TTS): existing Azure AI Speech account ──────
# AZURE_SPEECH_RESOURCE_ID can be the same as AZURE_FOUNDRY_RESOURCE_ID when
# Speech is exposed by your AIServices multi-service account. If you have a
# dedicated Speech account, use its ARM ID here.
azd env set AZURE_SPEECH_RESOURCE_ID        "/subscriptions/<sub-id>/resourceGroups/<speech-rg>/providers/Microsoft.CognitiveServices/accounts/<speech-account>"
azd env set AZURE_SPEECH_REGION             "eastus2"

# ─── Optional: Container App scaling knobs (defaults are fine for a demo) ────
# azd env set CONTAINER_CPU                   "1.0"
# azd env set CONTAINER_MEMORY                "2Gi"
# azd env set MIN_REPLICAS                    "1"
# azd env set MAX_REPLICAS                    "3"

# ─── Optional: Override the resource group name ──────────────────────────────
# Default is rg-<env-name>. Set this if you want a hyphenated form
# (e.g. rg-zava-story instead of the default rg-zavastory).
# azd env set RESOURCE_GROUP_NAME             "rg-children-story"

# ─── Optional: Microsoft Entra Easy Auth in front of the app ─────────────────
# By default the app is publicly reachable. To put Entra sign-in in front,
# first run infra/scripts/create_entra_app_reg.sh (after the first deploy
# so you have an FQDN), then set these values and re-run `azd provision`.
#
# azd env set ENABLE_ENTRA_AUTH               "true"
# azd env set ENTRA_CLIENT_ID                 "<from create_entra_app_reg.sh>"
# azd env set ENTRA_CLIENT_SECRET             "<from create_entra_app_reg.sh>"
# azd env set ENTRA_TENANT_ID                 "<from create_entra_app_reg.sh>"

echo "[azd-env] all values written to .azure/$(azd env get-value AZURE_ENV_NAME)/.env"
echo "[azd-env] next:  azd up"
