"""Configuration from environment variables: the same image runs in every mode and environment."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

MODES = ("monolith", "orders", "inventory", "payments")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    service_mode: str = "monolith"  # monolith | orders | inventory | payments
    environment: str = "local"
    app_version: str = "0.1.0"
    git_sha: str = "unknown"
    database_url: str = "sqlite+pysqlite:///./shop.db"
    inventory_url: str = "http://inventory.inventory.svc.cluster.local:8000"
    payments_url: str = "http://payments.payments.svc.cluster.local:8000"
    http_timeout_seconds: float = 2.0
    payments_limit_cents: int = 100_000  # payments above 1,000.00 EUR are declined
    faults_enabled: bool = False  # lab-only fault injection; never true outside the lab
    seed_products: bool = True
    log_level: str = "INFO"

    @property
    def service_name(self) -> str:
        return "shop-monolith" if self.service_mode == "monolith" else self.service_mode

    def owns(self, domain: str) -> bool:
        return self.service_mode in ("monolith", domain)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.service_mode not in MODES:
        raise ValueError(f"SERVICE_MODE must be one of {MODES}")
    return settings
