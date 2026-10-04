"""JEV adapter: turns an incident into a structured routing decision.

Two implementations with one contract (models.Decision):
  JevLite - rule-based stand-in (automation/jev/rules.yaml), deterministic and testable
  HttpJev - calls the real JEV at SAFEOPS_JEV_URL; any invalid or missing answer falls
            back to a safe 'observe + escalate to human' decision
JEV routes work. It never authorizes anything: the policy engine does that.
"""

from pathlib import Path

import httpx
import yaml
from pydantic import ValidationError

from automation.controlplane.models import AUTONOMY, Decision

SAFE_FALLBACK = {
    "incident_type": "unknown",
    "ai_suitability": "no",
    "autonomy": "observe",
    "approval": "engineer",
    "remediation_class": "none",
    "escalation": "human",
    "confidence": 0.0,
}


def clamp(autonomy: str, ceiling: str) -> str:
    return AUTONOMY[min(AUTONOMY.index(autonomy), AUTONOMY.index(ceiling))]


class JevLite:
    def __init__(self, rules_file: Path) -> None:
        self.config = yaml.safe_load(rules_file.read_text(encoding="utf-8"))

    def decide(self, labels: dict, known_service: bool) -> Decision:
        chosen = self.config["default"]
        for rule in self.config["rules"]:
            if all(labels.get(k) == v for k, v in rule["match"].items()):
                chosen = rule
                break
        values = {k: v for k, v in chosen.items() if k != "match"}
        values.setdefault("escalation", "none")
        values["autonomy"] = clamp(values["autonomy"], self.config["autonomy_ceiling"])
        if values["confidence"] < self.config["min_confidence_for_patch"]:
            values["autonomy"] = clamp(values["autonomy"], "diagnose")
        if not known_service:
            values.update(ai_suitability="no", escalation="human", autonomy="observe")
            values["rationale"] = "Unknown service: no blast-radius definition exists."
        severity = labels.get("severity", "medium")
        return Decision(
            affected_component=labels.get("service", "unknown"),
            severity=severity if severity in {"low", "medium", "high", "critical"} else "medium",
            source="jev-lite",
            **values,
        )


class HttpJev:
    def __init__(self, url: str, http: httpx.Client | None = None) -> None:
        self.url = url
        self.http = http or httpx.Client(timeout=5.0)

    def decide(self, labels: dict, known_service: bool) -> Decision:
        component = labels.get("service", "unknown")
        try:
            response = self.http.post(self.url, json={"labels": labels})
            response.raise_for_status()
            decision = Decision(**{**response.json(), "source": "jev"})
        except (httpx.HTTPError, ValueError, ValidationError, TypeError):
            return Decision(
                affected_component=component,
                severity="medium",
                rationale="JEV unavailable or returned an invalid decision: fail safe.",
                source="jev-fallback",
                **SAFE_FALLBACK,
            )
        if not known_service:
            decision.ai_suitability, decision.escalation, decision.autonomy = (
                "no",
                "human",
                "observe",
            )
        return decision
