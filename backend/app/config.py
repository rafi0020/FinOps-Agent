"""All configuration comes from environment variables; see .env.example."""

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LLM_PROVIDERS = ("openai_compat", "anthropic", "ollama", "stub")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://finops_app:finops_app@localhost:55432/finops"
    database_url_ro: str = "postgresql+psycopg://finops_ro:finops_ro@localhost:55432/finops"
    database_url_owner: str = "postgresql+psycopg://finops_owner:finops_owner@localhost:55432/finops"
    redis_url: str = "redis://localhost:56379/0"
    db_pool_size: int = 10

    secret_key: str = ""
    cors_origins: str = "http://localhost:3100"
    cookie_secure: bool = False
    session_hours: int = 12
    seed_demo: bool = True
    allow_signup: bool = True
    trusted_proxy: bool = False  # read the client address from X-Forwarded-For (set when behind nginx)
    scrypt_n: int = 2**15
    login_attempts_per_minute: int = 5  # per e-mail address
    login_ip_per_minute: int = 30
    signup_ip_per_hour: int = 10

    llm_provider: str = "stub"
    llm_model: str = ""
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_fallback_model: str = ""
    llm_price_input_per_mtok: float = 3.0  # USD per million tokens; set to your provider's real prices
    llm_price_output_per_mtok: float = 15.0
    llm_max_concurrency: int = 16  # model calls in flight per process
    llm_max_output_tokens: int = 4096
    allow_private_llm_urls: bool = True  # false on a shared deployment: refuse base URLs on private networks

    run_max_steps: int = 25
    run_max_tokens: int = 200_000
    run_max_seconds: int = 300
    run_max_cost_usd: float = 1.00
    org_daily_cost_usd: float = 20.00
    global_daily_cost_usd: float = 200.00  # all organisations together: bounds what open sign-up can spend
    org_max_concurrent_runs: int = 5
    org_max_queued_runs: int = 15  # runs waiting for a worker, per organisation, before new ones get 429
    runs_per_minute: int = 10  # new runs per user
    run_lease_seconds: int = 30  # a worker that stops renewing for this long loses the run to another worker
    run_max_attempts: int = 5  # times a run may be picked up before it is failed as unrecoverable
    worker_concurrency: int = 4
    stub_responder: str = "app.finance.stub_agent:demo_responder"  # behaviour of LLM_PROVIDER=stub

    otel_exporter_otlp_endpoint: str = ""
    # Off by default: spans then carry structure, timing, tokens and cost but no prompts, answers or tool
    # arguments. Turn on only when the receiver is trusted with that content; it is secret-masked first.
    otel_capture_content: bool = False
    app_version: str = "1.0.0"
    metrics_token: str = ""  # when set, /metrics requires "Authorization: Bearer <token>"
    log_level: str = "INFO"

    @field_validator("llm_provider")
    @classmethod
    def _known_provider(cls, value: str) -> str:
        if value not in LLM_PROVIDERS:
            raise ValueError(f"LLM_PROVIDER must be one of {', '.join(LLM_PROVIDERS)}; got {value!r}")
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
