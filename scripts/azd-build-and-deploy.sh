#!/bin/sh
# azd-build-and-deploy.sh — postprovision hook for Children's Story Studio.
#
# azd doesn't natively support deploying a custom container to App Service
# (the `docker:` service block is containerapp/aks only). So we do it
# ourselves after provisioning:
#
#   1. Log in to the ACR that Bicep just created (managed-identity-less,
#      uses the developer's az credentials).
#   2. Build the image for linux/amd64 (App Service Linux is x64 only).
#   3. Push it to the ACR.
#   4. Point the Web App at the new image and restart it.
#
# Required azd environment variables (populated automatically from main.bicep
# outputs):
#   AZURE_RESOURCE_GROUP
#   AZURE_CONTAINER_REGISTRY_NAME
#   AZURE_CONTAINER_REGISTRY_ENDPOINT
#   SERVICE_WEB_NAME
#   SERVICE_WEB_IMAGE_NAME      (e.g. <registry>.azurecr.io/app-xyz:latest)

set -eu

: "${AZURE_RESOURCE_GROUP:?missing — run \`azd provision\` first}"
: "${AZURE_CONTAINER_REGISTRY_NAME:?missing — main.bicep should output this}"
: "${AZURE_CONTAINER_REGISTRY_ENDPOINT:?missing — main.bicep should output this}"
: "${SERVICE_WEB_NAME:?missing — main.bicep should output this}"
: "${SERVICE_WEB_IMAGE_NAME:?missing — main.bicep should output this}"

# Tag with both :latest and a unique build tag so rollbacks are possible.
BUILD_TAG="$(date +%Y%m%d-%H%M%S)"
IMAGE_LATEST="$SERVICE_WEB_IMAGE_NAME"
IMAGE_BUILD="${SERVICE_WEB_IMAGE_NAME%:*}:${BUILD_TAG}"

echo "[deploy] ACR login: $AZURE_CONTAINER_REGISTRY_NAME"
az acr login --name "$AZURE_CONTAINER_REGISTRY_NAME" >/dev/null

echo "[deploy] Building image: $IMAGE_BUILD"
docker build \
    --platform linux/amd64 \
    -t "$IMAGE_LATEST" \
    -t "$IMAGE_BUILD" \
    -f "$(dirname "$0")/../Dockerfile" \
    "$(dirname "$0")/.."

echo "[deploy] Pushing $IMAGE_BUILD"
docker push "$IMAGE_BUILD"
echo "[deploy] Pushing $IMAGE_LATEST"
docker push "$IMAGE_LATEST"

echo "[deploy] Updating Web App container: $SERVICE_WEB_NAME -> $IMAGE_BUILD"
# The web app uses its system-assigned managed identity for ACR pull
# (configured in Bicep via acrUseManagedIdentityCreds=true).  No registry
# credentials are passed here.
az webapp config container set \
    --name "$SERVICE_WEB_NAME" \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --container-image-name "$IMAGE_BUILD" \
    --container-registry-url "https://${AZURE_CONTAINER_REGISTRY_ENDPOINT}" \
    >/dev/null

echo "[deploy] Restarting $SERVICE_WEB_NAME"
az webapp restart --name "$SERVICE_WEB_NAME" --resource-group "$AZURE_RESOURCE_GROUP" >/dev/null

URL="$(az webapp show --name "$SERVICE_WEB_NAME" --resource-group "$AZURE_RESOURCE_GROUP" --query defaultHostName -o tsv)"
echo ""
echo "[deploy] Done. App is reachable at: https://$URL"
