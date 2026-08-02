from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_env: str = "dev"
    database_url: str
    api_port: int = 8100
    mcp_http_port: int = 8110
    session_secret: str = "dev-only-not-a-secret"

    google_client_id: str = ""
    google_client_secret: str = ""
    allowed_email_domain: str = "swandigitals.com"

    target_country: str = "IN"
    target_agents_min: int = 5
    target_agents_max: int = 200
    signal_recency_days: int = 180
    monthly_spend_cap_usd: float = 35.0

    anthropic_api_key: str = ""
    builtwith_api_key: str = ""
    apify_token: str = ""
    apollo_api_key: str = ""
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_user_agent: str = "swan-intent-desk/0.1"

    @property
    def is_dev(self) -> bool:
        return self.app_env == "dev"

    @property
    def allowed_email_domains(self) -> list[str]:
        """ALLOWED_EMAIL_DOMAIN accepts a comma-separated list, so the desk can
        be shared across more than one company domain without a code change."""
        return [
            d.strip().lower().lstrip("@")
            for d in self.allowed_email_domain.split(",")
            if d.strip()
        ]


settings = Settings()
