from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://opsbridge:opsbridge@localhost:5432/opsbridge"

    # Webhook ingestion
    webhook_secret: str = "change-me"

    # External connector (GitHub Issues)
    github_token: str = ""
    github_api_url: str = "https://api.github.com"
    connector_max_retries: int = 4
    connector_backoff_base_s: float = 0.5
    connector_breaker_threshold: int = 5
    connector_breaker_reset_s: float = 30.0

    # LLM (empty key -> deterministic HeuristicLLM, used by tests/CI)
    anthropic_api_key: str = ""
    llm_model: str = "claude-opus-5-5"

    # Agent guardrails
    confidence_threshold: float = 0.85
    embedding_dim: int = 1536

    # CI eval gate
    eval_pass_threshold: float = 0.85


@lru_cache
def get_settings() -> Settings:
    return Settings()
