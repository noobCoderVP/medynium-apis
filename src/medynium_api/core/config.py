"""Runtime configuration, read from environment variables (see .env.example)."""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    app_env: Literal["local", "test", "staging", "production"] = "local"
    log_level: str = "INFO"
    # Comma-separated browser origins allowed to call the API directly (the UI normally proxies).
    cors_origins: str = "http://localhost:3000"
    session_secret: SecretStr = SecretStr("dev-only-change-me")
    session_ttl_minutes: int = 480
    cookie_secure: bool = False

    # Snowflake connection. Runtime auth is one key pair per app user (SEC-01, SEC-03).
    snowflake_account: str = ""
    snowflake_warehouse: str = "MEDYNIUM_WH"
    snowflake_database: str = "MEDYNIUM"
    # JSON object: {"SHARMA_DR": "<base64 PEM private key>", ...}
    snowflake_user_keys: SecretStr = SecretStr("{}")
    snowflake_user_key_passphrase: SecretStr | None = None

    # Cortex objects
    router_model: str = "llama3.1-8b"
    strong_model: str = ""
    cortex_search_service: str = "MEDYNIUM.KNOWLEDGE.LABEL_SEARCH"
    cortex_semantic_view: str = "MEDYNIUM.ANALYTICS.PATIENT_SEMANTIC_VIEW"
    cortex_agent: str = "MEDYNIUM.ANALYTICS.MEDYNIUM_AGENT"

    # Routing and agent behaviour (implementation plan section 4)
    router_confidence_threshold: float = 0.7
    router_timeout_seconds: float = 5.0
    agent_timeout_seconds: float = 30.0

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def snowflake_configured(self) -> bool:
        return bool(self.snowflake_account and self.snowflake_user_keys.get_secret_value() != "{}")


@lru_cache
def get_settings() -> Settings:
    return Settings()
