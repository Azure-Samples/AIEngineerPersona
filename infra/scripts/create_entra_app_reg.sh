#!/usr/bin/env bash
set -euo pipefail

# create_entra_app_reg.sh — Bootstrap (or reuse) the Microsoft Entra app
# registration that backs Container Apps Easy Auth in front of the
# Children's Story Studio Container App.
#
# Idempotent: safe to re-run. Looks up an existing app reg by display name +
# sign-in audience + matching redirect URIs. If exactly one match is found it
# reuses the client ID; if none, it creates a new app reg; if more than one,
# it FAILS (display names are not unique in Entra) and asks the operator to
# pass --app-id explicitly.
#
# Outputs the three values needed by `infra/main.bicep`:
#   ENTRA_CLIENT_ID
#   ENTRA_CLIENT_SECRET   (only minted on first-create OR when --rotate-secret)
#   ENTRA_TENANT_ID
#
# Required CLI: az 2.55+, jq.
# Required Entra role on the operator: Application.ReadWrite.All
#   (Application Administrator / Cloud Application Administrator).

# ---------------------------------------------------------------------------
# Defaults / args
# ---------------------------------------------------------------------------

APP_DISPLAY_NAME="${APP_DISPLAY_NAME:-Zava-Story-Demo}"
APP_FQDN=""
ROTATE_SECRET="false"
EXPLICIT_APP_ID=""
SECRET_LIFETIME_DAYS="${SECRET_LIFETIME_DAYS:-365}"

usage() {
    cat <<EOF
Usage: $0 --fqdn <container-app-fqdn> [options]

Required:
  --fqdn <fqdn>         FQDN of the Container App (no scheme).
                        Get this with: azd env get-value SERVICE_APP_FQDN

Optional:
  --display-name <s>    Entra app reg display name. Default: $APP_DISPLAY_NAME.
  --app-id <guid>       Reuse a specific app reg (skips display-name lookup).
                        Required if multiple apps match the display name.
  --rotate-secret       Mint a NEW client secret. Default: only mints on
                        first-create. The previous secret remains valid until
                        you delete it from the app reg.
  --secret-days <n>     Lifetime of a newly-minted secret in days. Default: $SECRET_LIFETIME_DAYS.
                        Will be clamped down if the tenant's app management
                        policy enforces a shorter maximum.
  -h, --help            Show this help.

Outputs (printed at the end):
  ENTRA_CLIENT_ID=<guid>
  ENTRA_CLIENT_SECRET=<secret>     (only on create or --rotate-secret)
  ENTRA_TENANT_ID=<guid>
  ENTRA_CLIENT_SECRET_EXPIRES_AT=<ISO8601>
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --fqdn)           APP_FQDN="$2";           shift 2;;
        --display-name)   APP_DISPLAY_NAME="$2";   shift 2;;
        --app-id)         EXPLICIT_APP_ID="$2";    shift 2;;
        --rotate-secret)  ROTATE_SECRET="true";    shift;;
        --secret-days)    SECRET_LIFETIME_DAYS="$2"; shift 2;;
        --secret-months)  SECRET_LIFETIME_DAYS=$(( $2 * 30 )); shift 2;;
        -h|--help)        usage; exit 0;;
        *)                echo "[entra] unknown arg: $1" >&2; usage; exit 2;;
    esac
done

if [[ -z "$APP_FQDN" ]]; then
    echo "[entra] --fqdn is required" >&2
    usage
    exit 2
fi

REDIRECT_URI="https://${APP_FQDN}/.auth/login/aad/callback"

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

command -v az >/dev/null 2>&1 || { echo "[entra] 'az' not found on PATH"  >&2; exit 1; }
command -v jq >/dev/null 2>&1 || { echo "[entra] 'jq' not found on PATH" >&2; exit 1; }

AZ_VERSION=$(az version --query '"azure-cli"' -o tsv)
echo "[entra] az version: $AZ_VERSION"

# Probe MS Graph permissions early. /me requires only the signed-in user's own
# profile and works for any tenant member; if THIS call fails the operator
# definitely cannot create app registrations either.
if ! az rest --method GET --url "https://graph.microsoft.com/v1.0/me" --output none 2>/dev/null; then
    echo "[entra] cannot reach Microsoft Graph as the current az identity." >&2
    echo "[entra] Run 'az login' (with a user, not a service principal) first." >&2
    exit 1
fi

ENTRA_TENANT_ID=$(az account show --query tenantId -o tsv)
echo "[entra] tenant: $ENTRA_TENANT_ID"

# ---------------------------------------------------------------------------
# Look up (or create) the app registration
# ---------------------------------------------------------------------------

CLIENT_ID=""
CREATED_NEW="false"

if [[ -n "$EXPLICIT_APP_ID" ]]; then
    CLIENT_ID="$EXPLICIT_APP_ID"
    if ! az ad app show --id "$CLIENT_ID" --output none 2>/dev/null; then
        echo "[entra] --app-id $EXPLICIT_APP_ID does not exist" >&2
        exit 1
    fi
    echo "[entra] using --app-id: $CLIENT_ID"
else
    echo "[entra] looking up app reg by displayName='$APP_DISPLAY_NAME'..."
    # Use --filter (server-side) for a clean exact match; --all guards
    # against the default top=100 cutoff.
    MATCHES_JSON=$(az ad app list --filter "displayName eq '$APP_DISPLAY_NAME'" --all -o json)
    MATCH_COUNT=$(echo "$MATCHES_JSON" | jq 'length')

    if [[ "$MATCH_COUNT" -eq 0 ]]; then
        echo "[entra] no existing app reg; creating..."
        # --enable-id-token-issuance is required for Easy Auth's OIDC code flow.
        # Pre-create with the redirect URI so we don't need a follow-up update.
        CLIENT_ID=$(az ad app create \
            --display-name "$APP_DISPLAY_NAME" \
            --sign-in-audience "AzureADMyOrg" \
            --web-redirect-uris "$REDIRECT_URI" \
            --enable-id-token-issuance true \
            --query appId -o tsv)
        CREATED_NEW="true"
        echo "[entra] created app reg: $CLIENT_ID"
    elif [[ "$MATCH_COUNT" -eq 1 ]]; then
        CLIENT_ID=$(echo "$MATCHES_JSON" | jq -r '.[0].appId')
        echo "[entra] found existing app reg: $CLIENT_ID"
    else
        echo "[entra] multiple app regs match displayName='$APP_DISPLAY_NAME':" >&2
        echo "$MATCHES_JSON" | jq -r '.[] | "  appId=\(.appId)  createdDateTime=\(.createdDateTime)"' >&2
        echo "[entra] re-run with --app-id <guid> to disambiguate." >&2
        exit 1
    fi
fi

# ---------------------------------------------------------------------------
# Ensure single-tenant audience, redirect URI (merged), id-token issuance,
# and identifier URI. All these `az ad app update` calls are idempotent —
# they're no-ops when the value is already what we want.
# ---------------------------------------------------------------------------

# signInAudience: must be AzureADMyOrg for single-tenant. `az ad app create`
# sets it; for an existing app we may still need to enforce it.
CURRENT_AUDIENCE=$(az ad app show --id "$CLIENT_ID" --query signInAudience -o tsv)
if [[ "$CURRENT_AUDIENCE" != "AzureADMyOrg" ]]; then
    echo "[entra] updating signInAudience: $CURRENT_AUDIENCE -> AzureADMyOrg"
    az ad app update --id "$CLIENT_ID" --sign-in-audience "AzureADMyOrg"
fi

# Merge redirect URIs. The CLI replaces the entire list when --web-redirect-uris
# is passed, so we read existing + merge before writing.
EXISTING_REDIRECTS=$(az ad app show --id "$CLIENT_ID" --query "web.redirectUris" -o json)
MERGED_REDIRECTS=$(jq -nc \
    --argjson existing "$EXISTING_REDIRECTS" \
    --arg uri "$REDIRECT_URI" \
    '($existing + [$uri]) | unique')
NEEDS_REDIRECT_UPDATE=$(jq -nc --argjson a "$EXISTING_REDIRECTS" --argjson b "$MERGED_REDIRECTS" '($a | sort) != ($b | sort)')
if [[ "$NEEDS_REDIRECT_UPDATE" == "true" ]]; then
    echo "[entra] updating web.redirectUris (merged $(echo "$MERGED_REDIRECTS" | jq 'length') entries)"
    REDIRECT_ARGS=()
    while IFS= read -r u; do REDIRECT_ARGS+=("$u"); done < <(echo "$MERGED_REDIRECTS" | jq -r '.[]')
    az ad app update --id "$CLIENT_ID" --web-redirect-uris "${REDIRECT_ARGS[@]}"
else
    echo "[entra] web.redirectUris already correct"
fi

# Ensure id-token issuance (Easy Auth's OIDC code flow needs it).
ID_TOKEN_ENABLED=$(az ad app show --id "$CLIENT_ID" --query "web.implicitGrantSettings.enableIdTokenIssuance" -o tsv)
if [[ "$ID_TOKEN_ENABLED" != "True" && "$ID_TOKEN_ENABLED" != "true" ]]; then
    echo "[entra] enabling id-token issuance"
    az ad app update --id "$CLIENT_ID" --enable-id-token-issuance true
fi

# Merge identifier URIs to include api://<clientId> (matches Bicep allowedAudiences).
TARGET_IDENTIFIER_URI="api://${CLIENT_ID}"
EXISTING_IDENTIFIERS=$(az ad app show --id "$CLIENT_ID" --query "identifierUris" -o json)
MERGED_IDENTIFIERS=$(jq -nc \
    --argjson existing "$EXISTING_IDENTIFIERS" \
    --arg target "$TARGET_IDENTIFIER_URI" \
    '($existing + [$target]) | unique')
NEEDS_IDENTIFIER_UPDATE=$(jq -nc --argjson a "$EXISTING_IDENTIFIERS" --argjson b "$MERGED_IDENTIFIERS" '($a | sort) != ($b | sort)')
if [[ "$NEEDS_IDENTIFIER_UPDATE" == "true" ]]; then
    echo "[entra] updating identifierUris (merged $(echo "$MERGED_IDENTIFIERS" | jq 'length') entries)"
    IDENTIFIER_ARGS=()
    while IFS= read -r u; do IDENTIFIER_ARGS+=("$u"); done < <(echo "$MERGED_IDENTIFIERS" | jq -r '.[]')
    az ad app update --id "$CLIENT_ID" --identifier-uris "${IDENTIFIER_ARGS[@]}"
else
    echo "[entra] identifierUris already correct"
fi

# Ensure the SP exists (Easy Auth needs it for the OAuth2 flow).
if ! az ad sp show --id "$CLIENT_ID" --output none 2>/dev/null; then
    echo "[entra] creating service principal for $CLIENT_ID"
    az ad sp create --id "$CLIENT_ID" --output none
else
    echo "[entra] service principal already exists"
fi

# ---------------------------------------------------------------------------
# Mint a client secret (only on first-create OR when --rotate-secret).
# Uses --append so the prior secret stays valid; guards against the historical
# CLI bug where --append accidentally clobbered prior credentials by
# checking the credential count before/after.
# ---------------------------------------------------------------------------

ENTRA_CLIENT_SECRET=""
ENTRA_CLIENT_SECRET_EXPIRES_AT=""

if [[ "$CREATED_NEW" == "true" || "$ROTATE_SECRET" == "true" ]]; then
    BEFORE_COUNT=$(az ad app credential list --id "$CLIENT_ID" --query "length(@)" -o tsv)

    # Probe the tenant's default app management policy and clamp the requested
    # lifetime down to the policy's maxLifetime if needed. The policy expresses
    # max as ISO8601 duration like "P30D" / "P180D". We only handle days here
    # (which covers the typical enterprise policy values).
    REQUESTED_DAYS="$SECRET_LIFETIME_DAYS"
    POLICY_MAX_DAYS=""
    POLICY_JSON=$(az rest --method GET --url "https://graph.microsoft.com/v1.0/policies/defaultAppManagementPolicy" -o json 2>/dev/null || echo "")
    if [[ -n "$POLICY_JSON" ]]; then
        POLICY_MAX_RAW=$(echo "$POLICY_JSON" | jq -r '
            .applicationRestrictions.passwordCredentials // []
            | map(select(.restrictionType == "passwordLifetime" and .state == "enabled" and .maxLifetime != null))
            | .[0].maxLifetime // empty
        ')
        if [[ -n "$POLICY_MAX_RAW" ]]; then
            # Parse "P30D" / "P180D" / "P1Y" into days. Quick & narrow.
            if [[ "$POLICY_MAX_RAW" =~ ^P([0-9]+)D$ ]]; then
                POLICY_MAX_DAYS="${BASH_REMATCH[1]}"
            elif [[ "$POLICY_MAX_RAW" =~ ^P([0-9]+)Y$ ]]; then
                POLICY_MAX_DAYS=$(( ${BASH_REMATCH[1]} * 365 ))
            elif [[ "$POLICY_MAX_RAW" =~ ^P([0-9]+)M$ ]]; then
                POLICY_MAX_DAYS=$(( ${BASH_REMATCH[1]} * 30 ))
            fi
        fi
    fi

    EFFECTIVE_DAYS="$REQUESTED_DAYS"
    if [[ -n "$POLICY_MAX_DAYS" && "$EFFECTIVE_DAYS" -gt "$POLICY_MAX_DAYS" ]]; then
        echo "[entra] tenant app management policy caps secret lifetime at $POLICY_MAX_DAYS days; clamping from $REQUESTED_DAYS to $POLICY_MAX_DAYS"
        EFFECTIVE_DAYS="$POLICY_MAX_DAYS"
    fi

    # End date: now + N days in ISO8601 UTC. macOS `date` and GNU `date`
    # have different syntax; try GNU first, fall back to macOS.
    END_DATE=""
    if END_DATE=$(date -u -d "+${EFFECTIVE_DAYS} days" '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null); then
        :
    else
        END_DATE=$(date -u -v+"${EFFECTIVE_DAYS}"d '+%Y-%m-%dT%H:%M:%SZ')
    fi

    SECRET_DISPLAY_NAME="container-apps-easy-auth-$(date -u '+%Y%m%d-%H%M%S')"
    echo "[entra] minting client secret '$SECRET_DISPLAY_NAME' (expires $END_DATE, lifetime ${EFFECTIVE_DAYS}d)"
    SECRET_JSON=$(az ad app credential reset \
        --id "$CLIENT_ID" \
        --append \
        --display-name "$SECRET_DISPLAY_NAME" \
        --end-date "$END_DATE" \
        -o json)

    ENTRA_CLIENT_SECRET=$(echo "$SECRET_JSON" | jq -r '.password')
    ENTRA_CLIENT_SECRET_EXPIRES_AT=$(echo "$SECRET_JSON" | jq -r '.endDateTime // .endDate // empty')
    if [[ -z "$ENTRA_CLIENT_SECRET_EXPIRES_AT" ]]; then
        ENTRA_CLIENT_SECRET_EXPIRES_AT="$END_DATE"
    fi

    AFTER_COUNT=$(az ad app credential list --id "$CLIENT_ID" --query "length(@)" -o tsv)
    if [[ "$AFTER_COUNT" -le "$BEFORE_COUNT" ]]; then
        echo "[entra] FATAL: credential count did not increase (before=$BEFORE_COUNT after=$AFTER_COUNT)" >&2
        echo "[entra] Likely the historical --append clobber bug. Investigate az version." >&2
        exit 1
    fi
    echo "[entra] credential count: $BEFORE_COUNT -> $AFTER_COUNT (good)"
else
    echo "[entra] skipping secret mint (existing app, no --rotate-secret)."
    echo "[entra] If you need the secret value, re-run with --rotate-secret and the prior secret stays valid until you delete it."
fi

# ---------------------------------------------------------------------------
# Print outputs.
# ---------------------------------------------------------------------------

echo ""
echo "==============================================================="
echo "  Entra app registration ready."
echo "==============================================================="
echo ""
echo "  ENTRA_TENANT_ID=$ENTRA_TENANT_ID"
echo "  ENTRA_CLIENT_ID=$CLIENT_ID"
if [[ -n "$ENTRA_CLIENT_SECRET" ]]; then
    echo "  ENTRA_CLIENT_SECRET=$ENTRA_CLIENT_SECRET"
    echo "  ENTRA_CLIENT_SECRET_EXPIRES_AT=$ENTRA_CLIENT_SECRET_EXPIRES_AT"
    echo ""
    echo "  *** SAVE THE SECRET NOW. It cannot be retrieved later. ***"
    echo "  *** Plan to rotate before $ENTRA_CLIENT_SECRET_EXPIRES_AT (re-run with --rotate-secret). ***"
fi
echo ""
echo "  Redirect URI configured:"
echo "    $REDIRECT_URI"
echo ""
echo "  Next: wire up azd + redeploy:"
echo "    azd env set ENABLE_ENTRA_AUTH true"
echo "    azd env set ENTRA_CLIENT_ID     $CLIENT_ID"
if [[ -n "$ENTRA_CLIENT_SECRET" ]]; then
    echo "    azd env set ENTRA_CLIENT_SECRET <secret-from-above>"
fi
echo "    azd env set ENTRA_TENANT_ID     $ENTRA_TENANT_ID"
echo "    azd provision"
echo ""
