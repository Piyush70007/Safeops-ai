"""Adversarial worker: behaves like a model that has been successfully prompt-injected.

It replays the attack playbook (security/attack-scenarios/playbook.yaml) through the real
gateway. Every attack must come back DENY; anything else is a security regression.
"""

from pathlib import Path

import yaml


def fake_diff(path: str) -> str:
    return (
        f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n-x = 1\n+x = 2\n"
    )


def load_playbook(path: Path) -> list[dict]:
    attacks = yaml.safe_load(path.read_text(encoding="utf-8"))["attacks"]
    for attack in attacks:
        if "patch_path" in attack:
            attack.setdefault("args", {})["diff"] = fake_diff(attack.pop("patch_path"))
    return attacks


class AdversarialWorker:
    def __init__(self, client) -> None:
        self.client = client

    def run(self, attacks: list[dict]) -> list[dict]:
        results = []
        for attack in attacks:
            status, body = self.client.call(attack["tool"], **attack.get("args", {}))
            results.append({
                "attack": attack["name"],
                "category": attack["category"],
                "tool": attack["tool"],
                "outcome": body.get("outcome"),
                "blocked": body.get("outcome") == "DENY" or status in (401, 403),
                "reasons": body.get("reasons", []),
            })  # fmt: skip
        return results
