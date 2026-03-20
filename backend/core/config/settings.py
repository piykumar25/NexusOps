"""
NexusOps Central Configuration
================================
Single source of truth for all application settings.
Replaces scattered os.environ.get() calls across the codebase.

Configuration is loaded from (in priority order):
  1. Environment variables
  2. .env file (auto-loaded by pydantic-settings)
  3. Default values

Customers copy .env.example → .env and fill in their infrastructure details.
"""

from typing import Dict, List, Literal, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class NexusOpsSettings(BaseSettings):
    """
    Central configuration for the NexusOps SaaS platform.
    All settings can be overridden via environment variables.
    """
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ─── Application ─────────────────────────────────────────────────────
    app_name: str = "NexusOps"
    app_version: str = "0.3.0"
    app_env: Literal["development", "staging", "production"] = "development"
    debug: bool = False

    # ─── LLM Configuration ──────────────────────────────────────────────
    llm_model_name: str = Field(
        default="test",
        description="LLM model identifier. Use 'test' for demo mode, 'ollama:<model>' for Ollama"
    )
    ollama_base_url: str = Field(
        default="http://localhost:11434/v1",
        description="Ollama API base URL (must include /v1)"
    )

    # ─── Embedding Configuration ─────────────────────────────────────────
    embedding_provider: Literal["ollama", "openai", "fallback"] = "ollama"
    embedding_model: str = "nomic-embed-text"
    embedding_dim: int = 768

    # ─── Qdrant Vector Database ──────────────────────────────────────────
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "nexusops-knowledge"

    # ─── Prometheus ──────────────────────────────────────────────────────
    prometheus_url: str = "http://localhost:9090"

    # ─── Kafka ───────────────────────────────────────────────────────────
    kafka_bootstrap_servers: str = "localhost:9093"
    kafka_group_id: str = "nexusops-default"
    kafka_required_topics: List[str] = [
        "incident-alerts",
        "ai-data-stream",
        "triage-results",
        "nexusops-dlq",
    ]

    # ─── Database (PostgreSQL) ───────────────────────────────────────────
    database_url: str = "postgresql://nexusops:nexusops_password@localhost:5432/nexusops_db"

    # ─── Redis ───────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"

    # ─── API Server ──────────────────────────────────────────────────────
    api_host: str = "0.0.0.0"
    api_port: int = 8082
    cors_origins: List[str] = ["http://localhost:3000"]

    # ─── Guardrails ──────────────────────────────────────────────────────
    guardrail_max_input_length: int = 4000
    guardrail_rate_limit_requests: int = 30
    guardrail_rate_limit_window: int = 60
    guardrail_enable_topic_filter: bool = True
    guardrail_enable_injection_filter: bool = True

    # ─── Circuit Breaker ─────────────────────────────────────────────────
    circuit_breaker_failure_threshold: int = 3
    circuit_breaker_recovery_timeout: int = 60

    # ─── Agent Timeouts ──────────────────────────────────────────────────
    agent_timeout_coordinator: float = 120.0
    agent_timeout_specialist: float = 60.0
    agent_max_retries: int = 3

    # ─── OpenAI (optional, for embedding or LLM) ────────────────────────
    openai_api_key: Optional[str] = None

    @property
    def is_demo_mode(self) -> bool:
        """Check if the system is running in demo mode (no real LLM)."""
        return self.llm_model_name in ("test", "test:fake", "")

    def startup_summary(self) -> str:
        """Generate a human-readable startup config summary (with masked secrets)."""
        lines = [
            f"  App:         {self.app_name} v{self.app_version} ({self.app_env})",
            f"  LLM Model:   {self.llm_model_name}",
            f"  Ollama URL:  {self.ollama_base_url}",
            f"  Embeddings:  {self.embedding_provider} ({self.embedding_model})",
            f"  Qdrant:      {self.qdrant_url}",
            f"  Prometheus:  {self.prometheus_url}",
            f"  Kafka:       {self.kafka_bootstrap_servers}",
            f"  Database:    {self._mask_url(self.database_url)}",
            f"  Redis:       {self.redis_url}",
            f"  Guardrails:  topic_filter={self.guardrail_enable_topic_filter}, injection_filter={self.guardrail_enable_injection_filter}",
            f"  Demo Mode:   {self.is_demo_mode}",
        ]
        return "\n".join(lines)

    @staticmethod
    def _mask_url(url: str) -> str:
        """Mask passwords in database URLs."""
        import re
        return re.sub(r'://([^:]+):([^@]+)@', r'://\1:****@', url)


# ─── Singleton ───────────────────────────────────────────────────────────────

_settings: Optional[NexusOpsSettings] = None


def get_settings() -> NexusOpsSettings:
    """Get the singleton settings instance."""
    global _settings
    if _settings is None:
        _settings = NexusOpsSettings()
    return _settings
