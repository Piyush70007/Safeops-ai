"""Control-plane settings (environment variables with the SAFEOPS_ prefix)."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class ControlSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SAFEOPS_", extra="ignore")

    admin_token: str = ""  # humans, Alertmanager and CI (Bearer); empty = refuse all
    signing_key: str = ""  # signs short-lived worker tokens
    opa_url: str = "http://127.0.0.1:8181"
    jev_url: str = ""  # empty = use the rule-based JEV-lite
    jev_rules: Path = ROOT / "automation" / "jev" / "rules.yaml"
    services_file: Path = ROOT / "automation" / "controlplane" / "services.yaml"
    catalog_file: Path = ROOT / "automation" / "policy-engine" / "data" / "catalog.json"
    repo_path: Path = ROOT
    base_ref: str = "HEAD"
    audit_path: Path = ROOT / "evidence" / "audit.jsonl"
    grant_ttl_minutes: int = 45
    max_denials: int = 5  # circuit breaker: denied requests per incident
    max_failed_verifications: int = 2  # circuit breaker: rejected patches per incident
    prometheus_url: str = ""
    loki_url: str = ""
    kubernetes: bool = False  # use the Kubernetes API (in-cluster or kubeconfig)
    launcher: str = "none"  # none | docker | kubernetes
    worker_image: str = "safeops-ai-worker:local"
    gateway_url_for_workers: str = "http://safeops-control.safeops.svc.cluster.local:8080"
    n8n_webhook_url: str = ""
    run_tests_in_verification: bool = True


@lru_cache
def get_control_settings() -> ControlSettings:
    return ControlSettings()
