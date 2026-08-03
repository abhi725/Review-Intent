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

    # Apollo `people/*`. **False because it was measured, not assumed**: every
    # person endpoint answers 403 on the free plan, so a reviewer can never be
    # resolved no matter how complete their name looks. Left False, the per-row
    # button renders disabled with that reason instead of spending a click to be
    # told. Flip it to true after upgrading the Apollo plan.
    apollo_people_enabled: bool = False

    # Google Sheets push. The service account JSON key, base64-encoded — one
    # opaque value rather than separate email and key fields, because a PEM
    # private key spread across a .env file is where newline handling goes wrong,
    # and one value cannot be half-configured.
    google_sheets_sa_json: str = ""
    google_sheets_id: str = ""

    # Unguessable path segment for the public CSV export that Google Sheets'
    # IMPORTDATA reads. **Anyone holding the URL can read the lead queue** —
    # IMPORTDATA cannot send an Authorization header, so the secret has to be in
    # the URL and there is no way to make this both readable by Sheets and
    # private. Empty disables the route entirely, which is the default: a public
    # data path must be switched on deliberately, never inherited.
    sheet_export_token: str = ""

    # Apify residential proxy. Needs a PAID Apify plan — measured 2026-08-03, a
    # free account authenticates and then gets 403 on every proxy group, so this
    # cannot be switched on by accident and cannot be tested without the upgrade.
    # Off by default because turning it on is what makes Capterra, TrustRadius
    # and SoftwareSuggest billable instead of blocked.
    apify_residential_proxy: bool = False
    # NOT the API token: Apify issues a separate proxy password, readable at
    # GET /v2/users/me -> data.proxy.password. Using the token gets 407.
    apify_proxy_password: str = ""

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
