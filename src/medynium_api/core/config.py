"""Runtime configuration, read from environment variables (see .env.example)."""

import base64
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_KEY_PATH = Path.home() / ".medynium" / "keys" / "med_api_svc.p8"
DEV_SESSION_SECRET = "dev-only-change-me"
IST = timezone(timedelta(hours=5, minutes=30))  # a fixed offset: no tz database needed on any host


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    app_env: Literal["local", "test", "staging", "production"] = "local"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:3000"
    session_secret: SecretStr = SecretStr(DEV_SESSION_SECRET)
    cookie_secure: bool = False
    # The browser reaches the API through the UI proxy at /api, so the refresh cookie path must be /api/auth there.
    refresh_cookie_path: str = "/auth"
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    invite_hours: int = 72
    login_max_failures: int = 5
    login_lock_minutes: int = 15
    # "Recent" and change flags are measured from this date. Empty means today in IST (production). Set it to
    # 2026-10-02 to pin the seeded demo dataset, as the live tests do.
    demo_as_of_date: str = ""
    public_app_url: str = "http://localhost:3000"  # base of invitation and reset links

    # Email (Resend). With no key the app runs and simply does not send.
    resend_api_key: SecretStr | None = None
    email_from: str = "Medynium <onboarding@resend.dev>"  # use a verified domain in production
    email_reply_to: str | None = None
    # Patient summaries may only be emailed to these domains (comma separated). Empty means any domain.
    share_allowed_domains: str = ""
    # Second step at sign-in: a six-digit code emailed after the password is accepted.
    login_otp_enabled: bool = False
    otp_minutes: int = 10

    # Snowflake: one service identity (key pair), per-request role U_<user> (ADR-003)
    snowflake_account: str = ""
    snowflake_warehouse: str = "MEDYNIUM_WH"
    snowflake_database: str = "MEDYNIUM"
    snowflake_api_user: str = "MED_API_SVC"
    snowflake_api_role: str = "MED_API"
    snowflake_api_private_key_path: Path = DEFAULT_KEY_PATH
    snowflake_api_private_key_b64: SecretStr | None = (
        None  # deployed: base64 PEM from Secret Manager
    )
    snowflake_pool_size: int = 8
    snowflake_acquire_timeout_seconds: float = 20.0

    # Cortex
    router_model: str = "llama3.1-8b"
    planner_model: str = (
        "llama3.3-70b"  # picks tools; the router model is the fallback when it fails
    )
    planner_timeout_seconds: float = 12.0
    strong_model: str = "claude-sonnet-4-6"
    safety_path: Literal["pack", "agent"] = "pack"
    cortex_search_service: str = "MEDYNIUM.KNOWLEDGE.LABEL_SEARCH"
    cortex_semantic_view: str = "MEDYNIUM.ANALYTICS.PATIENT_SEMANTIC_VIEW"
    cortex_agent: str = "MEDYNIUM.ANALYTICS.MEDYNIUM_AGENT"
    router_confidence_threshold: float = 0.7
    # Reading uploaded reports: a cost-effective hosted model, and caps on size and pages (each page costs credits).
    extract_model: str = "llama3.3-70b"
    report_max_bytes: int = 10 * 1024 * 1024
    report_max_pages: int = 20
    # Share of a similar-patient score that comes from embedding similarity; the rest is structured overlap.
    similar_weight_embedding: float = 0.5
    router_timeout_seconds: float = 5.0
    agent_timeout_seconds: float = 30.0

    @property
    def as_of_iso(self) -> str:
        """The date the read models treat as "now": the pinned demo date, or today in IST."""
        if self.demo_as_of_date:
            return self.demo_as_of_date
        return datetime.now(IST).date().isoformat()

    @property
    def share_domain_list(self) -> list[str]:
        return [
            d.strip().lower().lstrip("@")
            for d in self.share_allowed_domains.split(",")
            if d.strip()
        ]

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def snowflake_host(self) -> str:
        return f"{self.snowflake_account.lower()}.snowflakecomputing.com"

    @property
    def private_key_pem(self) -> bytes | None:
        """The service key, from the secret (deployed) or the local key file."""
        if self.snowflake_api_private_key_b64 is not None:
            return base64.b64decode(self.snowflake_api_private_key_b64.get_secret_value())
        if self.snowflake_api_private_key_path.exists():
            return self.snowflake_api_private_key_path.read_bytes()
        return None

    @property
    def snowflake_configured(self) -> bool:
        return bool(self.snowflake_account) and self.private_key_pem is not None

    def assert_safe_for_environment(self) -> None:
        """Fail fast when a deployed environment still has development defaults."""
        if self.app_env in ("staging", "production"):
            secret = self.session_secret.get_secret_value()
            if secret == DEV_SESSION_SECRET or len(secret) < 32:
                raise RuntimeError(
                    "SESSION_SECRET must be a random value of 32+ characters when deployed"
                )
            if not self.snowflake_configured:
                raise RuntimeError("Snowflake account and service key must be set")
            if self.login_otp_enabled and self.resend_api_key is None:
                raise RuntimeError("LOGIN_OTP_ENABLED needs RESEND_API_KEY, or nobody can sign in")


@lru_cache
def get_settings() -> Settings:
    return Settings()
