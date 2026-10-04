"""Tool catalogue on the gateway side: strict argument models and the resource each call touches.

Arguments are validated BEFORE the policy is asked. extra="forbid" means an unexpected
argument (a classic tool-argument manipulation) is rejected, audited and counted.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from verification.gates import changed_paths

NAME = r"^[a-z][a-z0-9-]{1,40}$"
METRICS = Literal[
    "error_ratio",
    "request_rate",
    "latency_p95",
    "dependency_errors",
    "cpu_cores",
    "memory_bytes",
    "restarts",
]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoArgs(Strict):
    pass


class LogsArgs(Strict):
    service: str = Field(pattern=NAME)
    minutes: int = Field(default=15, ge=1, le=240)
    contains: str | None = Field(default=None, pattern=r"^[A-Za-z0-9 _.:/=-]{1,100}$")
    limit: int = Field(default=200, ge=1, le=1000)


class MetricsArgs(Strict):
    service: str = Field(pattern=NAME)
    query: METRICS
    minutes: int = Field(default=30, ge=5, le=360)


class KubernetesArgs(Strict):
    namespace: str = Field(pattern=NAME)
    kind: str = Field(pattern=r"^[a-z]{3,20}$")
    name: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9.-]{0,62}$")


class PatchArgs(Strict):
    diff: str = Field(min_length=10, max_length=200_000)
    summary: str = Field(default="", max_length=4000)


class ServiceArgs(Strict):
    service: str = Field(pattern=NAME)


TOOL_ARGS: dict[str, type[Strict]] = {
    "get_incident_brief": NoArgs,
    "get_logs": LogsArgs,
    "get_metrics": MetricsArgs,
    "inspect_kubernetes": KubernetesArgs,
    "get_repository_snapshot": NoArgs,
    "submit_patch": PatchArgs,
    "run_verification": NoArgs,
    "deploy_canary": ServiceArgs,
    "rollback": ServiceArgs,
    "restart_workload": ServiceArgs,
}


def resource_of(tool: str, args: dict) -> dict:
    """What the request touches, as the policy sees it. Derived by the gateway, not the model."""
    if tool == "submit_patch":
        return {"paths": changed_paths(args.get("diff", ""))}
    return {
        k: v
        for k, v in args.items()
        if k in ("service", "namespace", "kind") and isinstance(v, str)
    }
