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

    # StoryReviewer fan-out concurrency cap. The reviewer dispatches N+3
    # focused LLM calls (per-page + cover + end + text + cross-page) in
    # parallel; this semaphore guards against bursting through Azure OpenAI
    # RPM limits when multiple user sessions overlap. Default of 5 is well
    # below typical S0/S1 RPM ceilings while still keeping wall-time close
    # to the slowest single call.
    story_reviewer_max_concurrent_calls: int = 5


settings = Settings()
