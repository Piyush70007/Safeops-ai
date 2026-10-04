"""Demo C: the AI produces a tempting but wrong or unsafe fix. The gates must stop it."""

from tests.conftest import patch


def submit(lab, incident_id, name):
    return lab.worker(incident_id).call("submit_patch", diff=patch(name), summary=name)


def failed_gates(lab, incident_id):
    gates = lab.incident(incident_id)["verification"]["gates"]
    return {g["gate"] for g in gates if not g["passed"]}


def test_fix_that_hides_the_error_is_rejected_by_tests(lab):
    [incident_id] = lab.alert()
    status, _ = submit(lab, incident_id, "bad-fix-hide-error.patch")
    assert status == 200  # in scope, so it is accepted for verification ...
    assert lab.incident(incident_id)["status"] == "REJECTED"  # ... and rejected there
    assert failed_gates(lab, incident_id) == {"tests"}


def test_sql_injection_fix_is_rejected_by_static_analysis(lab):
    [incident_id] = lab.alert()
    submit(lab, incident_id, "bad-fix-sql-injection.patch")
    assert lab.incident(incident_id)["status"] == "REJECTED"
    assert {"lint", "sast"} <= failed_gates(lab, incident_id)


def test_rejected_patch_can_never_reach_canary(lab):
    [incident_id] = lab.alert()
    submit(lab, incident_id, "bad-fix-hide-error.patch")
    lab.cp.approve(incident_id, "deploy_canary", "alice")
    status, body = lab.worker(incident_id).call("deploy_canary", service="inventory")
    assert status == 403 and "patch has not passed verification" in body["reasons"]


def test_two_rejected_patches_trip_the_circuit_breaker(lab):
    [incident_id] = lab.alert()
    submit(lab, incident_id, "bad-fix-hide-error.patch")
    submit(lab, incident_id, "bad-fix-sql-injection.patch")
    assert lab.incident(incident_id)["status"] == "STOPPED"
    status, body = submit(lab, incident_id, "fix.patch")
    assert status == 403 and "grant is not active" in body["reasons"]


def test_fix_in_another_service_is_denied_before_verification(lab):
    [incident_id] = lab.alert()
    status, body = submit(lab, incident_id, "cross-service.patch")
    assert status == 403
    assert "cross-service" in " ".join(body["reasons"]) or "outside the writable scope" in " ".join(
        body["reasons"]
    )
    assert lab.incident(incident_id)["verification"] is None


def test_unhealthy_canary_is_rolled_back(make_lab):
    from safeops_worker.scripted import ScriptedWorker

    from tests.conftest import ADMIN, IMAGE

    lab = make_lab(deployer_outcome="Degraded")
    [incident_id] = lab.alert()
    worker = ScriptedWorker(lab.worker(incident_id), poll_seconds=0)
    worker.run(patch("fix.patch"), "fix", request_canary=False)
    lab.client.post(f"/incidents/{incident_id}/artifacts", json={"image": IMAGE}, headers=ADMIN)
    lab.cp.approve(incident_id, "deploy_canary", "alice")
    worker.call("deploy_canary", service="inventory")
    lab.client.post(f"/incidents/{incident_id}/refresh", headers=ADMIN)
    assert lab.incident(incident_id)["status"] == "ROLLED_BACK"
    assert lab.cp.deployer.history[-1] == "ghcr.io/example/inventory:stable"
