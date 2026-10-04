"""Data model of the control plane: incidents, JEV decisions, grants, tool results."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

AUTONOMY = ["observe", "diagnose", "patch", "sandbox_test", "canary", "low_risk_auto"]


def now() -> datetime:
    return datetime.now(UTC)


class Status(StrEnum):
    DETECTED = "DETECTED"
    TRIAGED = "TRIAGED"
    ESCALATED = "ESCALATED"  # handed to humans, no AI action
    INVESTIGATING = "INVESTIGATING"
    PATCH_PROPOSED = "PATCH_PROPOSED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"  # patch failed verification (worker may retry)
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    CANARY = "CANARY"
    PROMOTED = "PROMOTED"
    ROLLED_BACK = "ROLLED_BACK"
    STOPPED = "STOPPED"  # circuit breaker or kill switch
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


TERMINAL = {Status.STOPPED, Status.RESOLVED, Status.CLOSED, Status.ESCALATED}


class Decision(BaseModel):
    """The JEV decision schema (spec section 5). Validated whatever JEV returns."""

    incident_type: Literal["reliability", "security", "deployment", "configuration", "unknown"]
    affected_component: str
    severity: Literal["low", "medium", "high", "critical"]
    confidence: float = Field(ge=0, le=1)
    ai_suitability: Literal["yes", "review", "no"]
    autonomy: Literal["observe", "diagnose", "patch", "sandbox_test", "canary", "low_risk_auto"]
    approval: Literal["none", "engineer", "security_owner"]
    remediation_class: Literal["restart", "code_patch", "config_patch", "none"]
    escalation: Literal["none", "human", "stop_automation"] = "none"
    rationale: str = ""
    source: str = "jev-lite"


class Grant(BaseModel):
    grant_id: str
    incident_id: str
    service: str
    namespace: str
    workload: str
    writable_paths: list[str]
    autonomy: str
    remediation_class: str
    approvals: list[str] = []
    verified: bool = False
    artifact: str = ""
    status: Literal["ACTIVE", "STOPPED", "REVOKED"] = "ACTIVE"
    expires_at: int
    denials: int = 0
    failed_verifications: int = 0

    def policy_view(self) -> dict:
        return self.model_dump(exclude={"grant_id", "denials", "failed_verifications"})


class Event(BaseModel):
    at: datetime = Field(default_factory=now)
    actor: str
    event: str


class Incident(BaseModel):
    incident_id: str
    title: str
    service: str
    severity: str
    status: Status = Status.DETECTED
    category: str = "reliability"
    detected_at: datetime = Field(default_factory=now)
    active_alerts: dict[str, dict] = {}  # fingerprint -> labels (deduplication)
    seen_alerts: list[str] = []
    decision: Decision | None = None
    grant_id: str | None = None
    base_commit: str = ""  # the exact code under investigation, pinned at triage
    patch: dict | None = None
    verification: dict | None = None
    canary: dict | None = None
    milestones: dict[str, datetime] = {}
    tool_calls: dict[str, int] = {"ALLOW": 0, "REVIEW": 0, "DENY": 0}
    timeline: list[Event] = []

    def log(self, actor: str, event: str) -> None:
        self.timeline.append(Event(actor=actor, event=event))

    def mark(self, milestone: str) -> None:
        self.milestones.setdefault(milestone, now())
