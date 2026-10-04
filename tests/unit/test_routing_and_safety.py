"""JEV routing, escalation, deduplication, autonomy ceilings, fail-closed behaviour, audit."""

import json

import httpx

from automation.controlplane.audit import AuditLog, verify
from automation.controlplane.config import ControlSettings
from automation.controlplane.jev import HttpJev, JevLite
from automation.controlplane.policy import PolicyClient
from tests.conftest import ADMIN

RULES = ControlSettings().jev_rules


def test_jev_lite_routes_error_rate_to_canary_with_engineer_approval():
    decision = JevLite(RULES).decide({"alertname": "ShopHighErrorRate", "service": "inventory",
                                      "severity": "high"}, known_service=True)  # fmt: skip
    assert (decision.autonomy, decision.approval, decision.remediation_class) == (
        "canary", "engineer", "code_patch")  # fmt: skip


def test_low_confidence_limits_autonomy_to_diagnosis():
    decision = JevLite(RULES).decide({"alertname": "SomethingNew", "service": "inventory"}, True)
    assert decision.autonomy == "diagnose" and decision.incident_type == "unknown"


def test_unknown_service_is_never_automated():
    decision = JevLite(RULES).decide({"alertname": "ShopHighErrorRate", "service": "x"}, False)
    assert (decision.autonomy, decision.escalation) == ("observe", "human")


def test_real_jev_with_invalid_answer_falls_back_to_human():
    bad = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"x": 1})))
    decision = HttpJev("http://jev", bad).decide({"service": "inventory"}, True)
    assert (decision.source, decision.autonomy, decision.escalation) == (
        "jev-fallback", "observe", "human")  # fmt: skip


def test_policy_engine_outage_fails_closed():
    def down(request):
        raise httpx.ConnectError("refused", request=request)

    client = PolicyClient("http://opa", httpx.Client(transport=httpx.MockTransport(down)))
    assert client.decide({"tool": "get_logs"})["outcome"] == "DENY"


def test_security_incident_is_escalated_without_any_grant(lab):
    [incident_id] = lab.alert(name="SecretDetected", category="security")
    incident = lab.incident(incident_id)
    assert incident["status"] == "ESCALATED" and incident["grant_id"] is None
    assert (
        lab.client.post(f"/incidents/{incident_id}/worker-token", headers=ADMIN).status_code == 409
    )


def test_database_outage_allows_diagnosis_only(lab):
    [incident_id] = lab.alert(name="ShopDependencyDown")
    worker = lab.worker(incident_id)
    assert worker.call("get_logs", service="inventory")[0] == 200
    status, body = worker.call("submit_patch", diff="diff --git a/app/services/inventory/x.py "
                               "b/app/services/inventory/x.py\n+x")  # fmt: skip
    assert status == 403 and "below the 'patch' required" in body["reasons"][0]


def test_payments_is_capped_at_patch_by_the_service_catalogue(lab):
    [incident_id] = lab.alert(service="payments")
    assert lab.cp.grants[lab.incident(incident_id)["grant_id"]].autonomy == "patch"


def test_alerts_for_one_service_are_correlated_into_one_incident(lab):
    [first] = lab.alert(name="ShopHighErrorRate", fp="a")
    [second] = lab.alert(name="ShopErrorBudgetFastBurn", fp="b")
    assert first == second
    lab.alert(name="ShopHighErrorRate", fp="a", status="resolved")
    assert lab.incident(first)["status"] == "INVESTIGATING"  # one alert still firing
    lab.alert(name="ShopErrorBudgetFastBurn", fp="b", status="resolved")
    assert lab.incident(first)["status"] == "RESOLVED"


def test_kill_switch_stops_automation_immediately(lab):
    [incident_id] = lab.alert()
    worker = lab.worker(incident_id)
    lab.client.post(f"/incidents/{incident_id}/stop", json={"reason": "drill"}, headers=ADMIN)
    assert worker.call("get_incident_brief")[0] == 403


def test_admin_endpoints_require_the_admin_token(lab):
    assert lab.client.get("/incidents").status_code == 401
    assert (
        lab.client.get("/incidents", headers={"Authorization": "Bearer wrong"}).status_code == 401
    )


def test_tool_label_cardinality_is_bounded(lab):
    [incident_id] = lab.alert()
    lab.worker(incident_id).call("totally_random_tool_name_123")
    metrics = lab.client.get("/metrics").text
    assert 'tool="unknown"' in metrics and "totally_random_tool_name_123" not in metrics


def test_audit_log_detects_tampering(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    for n in range(3):
        log.append("tool.request", "INC-1", n=n)
    assert verify(log.path) == []
    lines = log.path.read_text().splitlines()
    record = json.loads(lines[1])
    record["data"]["n"] = 99
    lines[1] = json.dumps(record)
    log.path.write_text("\n".join(lines[:1] + lines[1:]) + "\n")
    assert any("content modified" in p for p in verify(log.path))
    log.path.write_text("\n".join([lines[0], lines[2]]) + "\n")
    assert any("chain broken" in p for p in verify(log.path))
