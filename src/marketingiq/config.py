"""Application settings, read from environment variables or a local .env file."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Owner role: runs migrations and loaders.
    database_url: str
    # Least-privilege role used by analytics, REST endpoints and assistant tools.
    database_url_app: str | None = None
    # Separate database that integration tests may wipe and rebuild.
    test_database_url: str | None = None
    # Role that migrations grant read access to (must match the role in DATABASE_URL_APP).
    app_db_role: str = "miq_app"
    # Organization the API serves when a request doesn't name one (one org in the MVP).
    default_org_slug: str = "synthetic-home-services"
    # The assistant's model: any OpenAI-compatible endpoint. Default: Gemini's free tier, which
    # may use prompts to improve Google's products, so it is for synthetic data only (U-14).
    llm_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    llm_api_key: SecretStr | None = None
    llm_model: str = "gemini-3.5-flash-lite"

    @property
    def app_url(self) -> str:
        """URL for read paths; falls back to the owner URL when no app role is configured."""
        return self.database_url_app or self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
