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

    # Feature flags
    # When True, the StoryReviewerExecutor is bypassed and every story is auto-approved.
    skip_story_reviewer: bool = False

    # CORS origin for the React dev server
    cors_origin: str = "http://localhost:5173"


settings = Settings()
