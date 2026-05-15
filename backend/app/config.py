from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    foundry_project_endpoint: str = ""
    foundry_model_deployment_name: str = "gpt-4o"
    foundry_image_model_deployment_name: str = "gpt-image-1"

    # Azure Speech Service (TTS)
    azure_speech_region: str = ""
    azure_speech_resource_id: str = ""   # /subscriptions/.../resourceGroups/.../providers/Microsoft.CognitiveServices/accounts/<name>
    azure_speech_endpoint: str = ""       # optional custom endpoint override

    # CORS origin for the React dev server
    cors_origin: str = "http://localhost:5173"

    # OpenTelemetry — master switch (set to False to disable without removing env vars)
    otel_enabled: bool = True

    # StoryReviewer fan-out concurrency cap (LOCAL mode). The reviewer
    # dispatches N+3 focused LLM calls (per-page + cover + end + text +
    # cross-page) in parallel; this semaphore guards against bursting
    # through Azure OpenAI RPM limits when multiple user sessions overlap.
    # Default of 5 is well below typical S0/S1 RPM ceilings while still
    # keeping wall-time close to the slowest single call.
    story_reviewer_max_concurrent_calls: int = 5

    # ── Foundry-hosted agent mode ────────────────────────────────────────
    # When `local` (default), each agent is constructed in-process via
    # OpenAIChatClient pointed at the Foundry/AOAI deployment. When
    # `foundry`, agents are looked up by name in the user's Foundry
    # project (provisioned ahead of time via
    # `python -m app.scripts.provision_foundry_agents`). See
    # docs/09-guide-foundry-hosted-agents.md for the full contract,
    # including the source-of-truth rule for instructions.
    agent_hosting_mode: Literal["local", "foundry"] = "local"

    # The Foundry project's name under the account at FOUNDRY_PROJECT_ENDPOINT.
    # Required when agent_hosting_mode=='foundry' because AIProjectClient
    # (and FoundryAgent + the provisioning script) need the LONG project-
    # scoped endpoint form (`<account>/api/projects/<project_name>`),
    # whereas OpenAIChatClient is happy with the SHORT account-level form
    # we use elsewhere. Keeping these split avoids breaking local mode.
    foundry_project_name: str = ""

    # StoryReviewer fan-out concurrency cap (FOUNDRY mode). Hosted-agent
    # calls add per-call thread/session creation that raw chat completions
    # don't have, so we default lower than the local cap to avoid hosted-
    # agent rate limits and thread-creation overhead. Ignored in local mode.
    foundry_reviewer_max_concurrent_calls: int = 3

    @property
    def foundry_agents_endpoint(self) -> str:
        """The LONG project-scoped endpoint used by AIProjectClient and
        FoundryAgent. Computed by appending `/api/projects/<project_name>`
        to the (short) account endpoint. Returns an empty string if either
        component is missing — callers in foundry mode should validate and
        emit a helpful error in that case (see foundry_agents.validate_…)."""
        if not self.foundry_project_endpoint or not self.foundry_project_name:
            return ""
        base = self.foundry_project_endpoint.rstrip("/")
        # If the user has already pasted the long form, don't double-append.
        if "/api/projects/" in base:
            return base
        return f"{base}/api/projects/{self.foundry_project_name}"


settings = Settings()
