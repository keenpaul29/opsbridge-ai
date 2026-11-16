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

    # LLM via any OpenAI-compatible chat API; default is Groq's free tier.
    # Empty key -> deterministic HeuristicLLM (used by tests/CI).
    groq_api_key: str = ""
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_model: str = "openai/gpt-oss-120b"
    llm_max_output_tokens: int = 2048
    llm_max_retries: int = 3
    llm_backoff_base_s: float = 1.0

    # Agent guardrails
    confidence_threshold: float = 0.85
    embedding_dim: int = 1536

    # CI eval gate
    eval_pass_threshold: float = 0.85


@lru_cache
def get_settings() -> Settings:
    return Settings()
