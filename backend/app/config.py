from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://opsbridge:opsbridge@localhost:5432/opsbridge"

    # Webhook ingestion
    webhook_secret: str = "change-me"

    # "production" refuses to run (or accept writes) without an operator token; anything else is a
    # local/dev instance where an empty token means no auth.
    environment: str = "development"

    # Console writes: approve/reject require `Authorization: Bearer <operator_token>`. Reads stay
    # public (read-only demo). Empty token = no auth, for local development only.
    operator_token: str = ""
    cors_origins: str = "http://localhost:3000"  # comma-separated

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
    # Retrieved policies scoring below this similarity count as absent, so a weak match can
    # neither be cited nor lift confidence. Needs calibrating against real embeddings.
    min_policy_score: float = 0.5

    # Policy embeddings via the Gemini API. Empty key -> offline HashEmbedder (tests, keyless dev).
    gemini_api_key: str = ""
    embedding_model: str = "gemini-embedding-2"
    embedding_api_url: str = "https://generativelanguage.googleapis.com/v1beta"
    embedding_dim: int = 768  # Google recommends 768, 1536 or 3072; changing it needs a migration
    embedding_max_retries: int = 3
    embedding_backoff_base_s: float = 1.0

    # CI eval gate
    eval_pass_threshold: float = 0.85
    eval_p95_ms: int = 5000


@lru_cache
def get_settings() -> Settings:
    return Settings()
