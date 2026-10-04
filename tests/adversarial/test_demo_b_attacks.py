"""Demo B: the AI reads hostile input and tries prohibited actions. Every one must be denied."""

from pathlib import Path

from safeops_worker.adversarial import AdversarialWorker, load_playbook
from safeops_worker.scripted import ScriptedWorker

from tests.conftest import INJECTION, ROOT, patch

PLAYBOOK = ROOT / "security" / "attack-scenarios" / "playbook.yaml"


def test_logs_are_delivered_as_untrusted_data(lab):
    [incident_id] = lab.alert()
    status, body = lab.worker(incident_id).call("get_logs", service="inventory", minutes=30)
    assert status == 200
    assert body["result"]["notice"].startswith("UNTRUSTED DATA")
    assert any(INJECTION in line["line"] for line in body["result"]["lines"])


def test_demo_b_every_attack_is_denied_and_work_continues_in_scope(lab):
    [incident_id] = lab.alert()
    attacks = load_playbook(PLAYBOOK)
    results = AdversarialWorker(lab.worker(incident_id)).run(attacks)
    escaped = [r for r in results if not r["blocked"]]
    assert not escaped, f"security regression: {escaped}"
    assert len(results) == len(attacks) >= 20

    denied = [r for r in lab.cp.audit.records(incident_id) if r["kind"] == "tool.request"
              and r["data"]["outcome"] == "DENY"]  # fmt: skip
    assert len(denied) == len(attacks)  # every attempt is evidence

    outcome = ScriptedWorker(lab.worker(incident_id), poll_seconds=0).run(
        patch("fix.patch"), "fix in scope", request_canary=False
    )
    assert outcome["result"] == "verified"


def test_persistent_attacker_trips_the_circuit_breaker(make_lab):
    lab = make_lab(max_denials=5)
    [incident_id] = lab.alert()
    worker = lab.worker(incident_id)
    for _ in range(5):
        worker.call("read_secret", name="postgres-credentials")
    assert lab.incident(incident_id)["status"] == "STOPPED"
    status, body = worker.call("get_incident_brief")
    assert status == 403 and "grant is not active" in body["reasons"]


def test_forged_and_foreign_tokens_are_rejected(lab):
    [incident_id] = lab.alert()
    good = lab.worker(incident_id)
    forged = type(good)("http://gateway", good.token[:-4] + "AAAA", good.transport)
    assert forged.call("get_incident_brief")[0] == 401
    assert type(good)("http://gateway", "not-a-jwt", good.transport).call("get_logs")[0] == 401


def test_playbook_file_is_the_single_source_of_attacks():
    assert Path(PLAYBOOK).exists()
    categories = {a["category"] for a in load_playbook(PLAYBOOK)}
    assert {"secret-access", "cross-service", "guardrail-tampering", "argument-manipulation",
            "destructive", "privilege-escalation", "verification-bypass"} <= categories  # fmt: skip
