"""Demo A (spec section 18): the AI actually fixes an incident, and only the controller ships it."""

from safeops_worker.scripted import ScriptedWorker

from automation.controlplane.audit import verify
from tests.conftest import ADMIN, IMAGE, patch


def test_demo_a_alert_to_verified_fix_to_promoted_canary(lab):
    [incident_id] = lab.alert()
    incident = lab.incident(incident_id)
    assert incident["status"] == "INVESTIGATING"
    assert incident["decision"]["affected_component"] == "inventory"
    assert incident["decision"]["autonomy"] == "canary"

    worker = ScriptedWorker(lab.worker(incident_id), poll_seconds=0)
    result = worker.run(patch("fix.patch"), "Use the SKU as price cache key", request_canary=False)
    assert result["result"] == "verified"
    gates = {g["gate"]: g["passed"] for g in lab.incident(incident_id)["verification"]["gates"]}
    assert gates == {"scope": True, "dependencies": True, "secrets": True, "apply": True,
                     "lint": True, "sast": True, "tests": True}  # fmt: skip

    # CI builds the verified patch and registers the image digest
    response = lab.client.post(f"/incidents/{incident_id}/artifacts", json={"image": IMAGE},
                               headers=ADMIN)  # fmt: skip
    assert response.status_code == 200

    # the worker asks for a canary: parked until an engineer approves (JEV said approval=engineer)
    status, body = worker.call("deploy_canary", service="inventory")
    assert status == 202 and body["outcome"] == "REVIEW"
    assert lab.incident(incident_id)["status"] == "AWAITING_APPROVAL"
    lab.client.post(f"/incidents/{incident_id}/approvals",
                    json={"action": "deploy_canary", "approver": "alice"}, headers=ADMIN)  # fmt: skip
    status, body = worker.call("deploy_canary", service="inventory")
    assert status == 200 and body["result"]["image"] == IMAGE

    # Argo Rollouts' analysis decides; the AI cannot declare its own work successful
    lab.client.post(f"/incidents/{incident_id}/refresh", headers=ADMIN)
    assert lab.incident(incident_id)["status"] == "PROMOTED"
    lab.alert(status="resolved")
    assert lab.incident(incident_id)["status"] == "RESOLVED"

    report = lab.client.get(f"/incidents/{incident_id}/report", headers=ADMIN).json()
    assert report["measures"]["time_to_recovery_seconds"] is not None
    assert report["measures"]["rolled_back"] is False
    assert not verify(lab.cp.audit.path), "audit chain must be intact"
    kinds = [event["type"] for event in lab.cp.notifier.events]
    assert "incident.promoted" in kinds and "incident.resolved" in kinds


def test_canary_needs_verified_artifact_even_with_approval(lab):
    [incident_id] = lab.alert()
    worker = lab.worker(incident_id)
    lab.cp.approve(incident_id, "deploy_canary", "alice")
    status, body = worker.call("deploy_canary", service="inventory")
    assert status == 403
    assert "patch has not passed verification" in body["reasons"]


def test_artifact_must_be_digest_pinned_and_verified(lab):
    [incident_id] = lab.alert()
    unverified = lab.client.post(f"/incidents/{incident_id}/artifacts", json={"image": IMAGE},
                                 headers=ADMIN)  # fmt: skip
    assert unverified.status_code == 409
    ScriptedWorker(lab.worker(incident_id), poll_seconds=0).run(
        patch("fix.patch"), "fix", request_canary=False
    )
    by_tag = lab.client.post(f"/incidents/{incident_id}/artifacts",
                             json={"image": "ghcr.io/example/inventory:latest"}, headers=ADMIN)  # fmt: skip
    assert by_tag.status_code == 409
