"""Application Configuration module.

Adheres strictly to Requirement D4:
No credentials, environment-specific endpoints, or concrete model identifiers
appear in tracked application repository files.
"""

from pathlib import Path
from typing import Literal, Optional

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[3] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    APP_ENV: str = Field(default="development")
    LOG_LEVEL: str = Field(default="INFO")
    API_PORT: int = Field(default=8000)

    # Database
    DATABASE_URL: str = Field(default="", repr=False)
    DATABASE_URL_SYNC: str = Field(default="", repr=False)
    DATABASE_DNS_RESOLVER: Literal["system", "cloudflare"] = "system"
    AUTH_CLIENT_TOKENS: dict[str, SecretStr] = Field(default_factory=dict, repr=False)
    CORS_ORIGINS: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # Redis / Celery
    REDIS_URL: str = Field(default="redis://localhost:6379/0")
    CELERY_BROKER_URL: Optional[str] = None
    CELERY_RESULT_BACKEND: Optional[str] = None

    # Vector Storage
    CHROMA_HOST: str = Field(default="localhost")
    CHROMA_PORT: int = Field(default=8000)

    CHROMA_COLLECTION: str = "workplace_compliance_provisions_v1"
    CHROMA_LOCAL_PATH: Optional[str] = None

    # Local Embeddings
    EMBEDDING_MODEL_NAME: str = Field(default="all-MiniLM-L6-v2")
    EMBEDDING_DEVICE: str = Field(default="cpu")
    EMBEDDING_CACHE_DIR: Optional[str] = None
    RETRIEVAL_MODE: Literal["hybrid", "lexical"] = "hybrid"
    RETRIEVAL_MIN_DENSE_SCORE: float = Field(default=0.25, ge=0, le=1)

    # Provider-Neutral LLM Configuration
    LLM_PROVIDER: str = Field(default="stub")  # "stub", "hosted", or "ollama"
    LLM_API_KEY: Optional[str] = Field(default=None, repr=False)
    LLM_BASE_URL: Optional[str] = Field(default=None)
    LLM_MODEL_NAME: Optional[str] = Field(default=None)
    OLLAMA_BASE_URL: str = Field(default="http://127.0.0.1:11434")
    OLLAMA_TIMEOUT_SECONDS: float = Field(default=30.0, gt=0, le=120)
    OLLAMA_THINK: bool = False
    OLLAMA_MAX_OUTPUT_TOKENS: int = Field(default=512, ge=64, le=4096)
    OLLAMA_CONTEXT_TOKENS: int = Field(default=16384, ge=4096, le=32768)

    # Delayed Model Stub
    STUB_SERVICE_URL: str = Field(default="http://localhost:8001")
    STUB_DELAY_SECONDS: float = Field(default=2.0)

    # Observability
    PROMETHEUS_METRICS_ENABLED: bool = Field(default=True)
    OTEL_SERVICE_NAME: str = Field(default="workplace-compliance-desk")
    OTEL_EXPORTER_OTLP_ENDPOINT: str = Field(default="http://localhost:4317")

    # Rate Limiting & Bounds
    RATE_LIMIT_REQUESTS_PER_MINUTE: int = Field(default=20)
    MAX_QUARANTINE_PAYLOAD_BYTES: int = Field(default=4096)
    MAX_REQUEST_BYTES: int = 16384
    RUN_LEASE_SECONDS: int = 120
    MAX_RUN_ATTEMPTS: int = 3
    QUEUE_WAIT_TIMEOUT_SECONDS: int = Field(default=20, ge=5, le=120)
    RUN_TIMEOUT_SECONDS: int = Field(default=45, ge=5, le=120)
    RESPONSE_DEADLINE_SECONDS: int = Field(default=60, ge=10, le=180)
    SLO_P95_SECONDS: float = Field(default=60.0)

    @field_validator("AUTH_CLIENT_TOKENS")
    @classmethod
    def validate_client_tokens(cls, clients):
        seen = set()
        for client, secret in clients.items():
            value = secret.get_secret_value()
            if not client or len(client) > 128 or not value.strip() or value in seen:
                raise ValueError(
                    "Client identities and tokens must be nonempty, distinct, and within field bounds."
                )
            seen.add(value)
        return clients

    def get_celery_broker_url(self) -> str:
        return self.CELERY_BROKER_URL or self.REDIS_URL

    def get_celery_backend_url(self) -> str:
        return self.CELERY_RESULT_BACKEND or self.REDIS_URL


settings = Settings()
