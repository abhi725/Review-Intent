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
    mcp_bearer_token: str = ""
    session_secret: str = "dev-only-not-a-secret"

    google_client_id: str = ""
    google_client_secret: str = ""
    # Empty on purpose. Anyone can sign in, so there is no domain to name — and
    # a default here would be a restriction nobody asked for, silently waiting
    # for someone to switch access_mode and discover it.
    allowed_email_domain: str = ""
    # Seeds the runtime `access_mode` preference on a fresh database; the stored
    # setting wins after that, so changing access does not need a redeploy.
    access_mode: str = "open"

    # --- outbound mail ---
    # Absolute base for links we email. Deliberately not derived from the
    # request's Host header: an attacker who can set that header could otherwise
    # get a password-reset link pointed at their own domain.
    public_base_url: str = "http://localhost:8100"
    mautic_url: str = ""
    mautic_user: str = ""
    mautic_pass: str = ""
    mautic_tpl_verify: int = 0
    mautic_tpl_reset: int = 0
    # Fallback sender, used whenever Mautic is unreachable or refuses. Keeping
    # both configured is not redundancy for its own sake — Mautic's API auth has
    # broken before without anyone noticing, because mail kept arriving.
    resend_api_key: str = ""
    email_from: str = "Intent Desk <noreply@updates.swandigitals.com>"

    target_country: str = "IN"
    target_agents_min: int = 5
    target_agents_max: int = 200
    signal_recency_days: int = 180
    monthly_spend_cap_usd: float = 35.0

    # --- LLM providers ---
    llm_provider: str = "openai"
    llm_fallback_provider: str = "gemini"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    anthropic_api_key: str = ""
    claude_model: str = "claude-opus-5"

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
        """Seed value only. Access is decided at runtime by
        `services.users.check_allowed`, which reads the stored setting — nothing
        in the request path reads this."""
        return [
            d.strip().lower().lstrip("@")
            for d in self.allowed_email_domain.split(",")
            if d.strip()
        ]


settings = Settings()
