"""Aggregate experiment evidence into the measurement report (spec section 15).

Input : evidence/<run>/reports/*.json (incident reports) + adversarial.json + audit.jsonl
Output: docs/experiments/results-<run>.md
  python evaluation/report.py evidence/offline-20261003T101500Z
"""

import json
import statistics
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fmt_seconds(values: list[float]) -> str:
    return f"{statistics.median(values):.1f} s" if values else "n/a"


def build(run: Path) -> str:
    reports = [json.loads(p.read_text()) for p in sorted((run / "reports").glob("*.json"))]
    attacks = (
        json.loads((run / "adversarial.json").read_text())
        if (run / "adversarial.json").exists()
        else []
    )
    audit = [json.loads(line) for line in (run / "audit.jsonl").read_text().splitlines()]
    meta = json.loads((run / "run.json").read_text()) if (run / "run.json").exists() else {}

    statuses = Counter(r["incident"]["status"] for r in reports)
    requests = [a for a in audit if a["kind"] == "tool.request"]
    denied = [a for a in requests if a["data"]["outcome"] == "DENY"]
    reviews = [a for a in requests if a["data"]["outcome"] == "REVIEW"]
    verifications = [a for a in audit if a["kind"] == "verification.result"]
    rejected = [v for v in verifications if not v["data"]["passed"]]
    gate_catches = Counter(g for v in rejected for g in v["data"]["failed_gates"])
    approvals = [a for a in audit if a["kind"] == "approval.granted"]
    breaker = [a for a in audit if a["kind"] == "circuit_breaker"]
    promoted = [r for r in reports if r["measures"]["time_to_recovery_seconds"] is not None
                and not r["measures"]["rolled_back"] and r["incident"].get("patch")]  # fmt: skip
    recovery = [r["measures"]["time_to_recovery_seconds"] for r in promoted]
    to_patch = [r["measures"]["time_to_patch_seconds"] for r in reports
                if r["measures"]["time_to_patch_seconds"] is not None]  # fmt: skip
    canaried = [r for r in reports if r["incident"].get("canary")]
    insecure_shipped = [r for r in canaried if r["incident"].get("verification", {}) and
                        not r["incident"]["verification"].get("passed")]  # fmt: skip
    cross = [a for a in denied if any("cross-service" in x or "outside the writable" in x
                                      for x in a["data"]["reasons"])]  # fmt: skip
    by_category = Counter(a["category"] for a in attacks)
    blocked_by_category = Counter(a["category"] for a in attacks if a["blocked"])

    lines = [
        f"# SafeOps AI - experiment results ({run.name})",
        "",
        f"Mode: {meta.get('mode', 'unknown')}.",
        f"Worker: {meta.get('worker', 'unknown')}. All numbers were measured in this run.",
        "",
        "## Overview",
        "",
        "| Measure | Value |",
        "|---|---|",
        f"| Incidents handled | {len(reports)} |",
        f"| Final status | {', '.join(f'{k} {v}' for k, v in sorted(statuses.items()))} |",
        f"| Successful remediations (verified, canary promoted) | {len(promoted)} |",
        f"| Human approvals given | {len(approvals)} |",
        f"| Automatic rollbacks | {sum(1 for r in reports if r['measures']['rolled_back'])} |",
        f"| Patches rejected by verification | {len(rejected)} of {len(verifications)} |",
        f"| Circuit breaker trips | {len(breaker)} |",
        f"| AI tool requests (allowed / parked / denied) | "
        f"{len(requests) - len(denied) - len(reviews)} / {len(reviews)} / {len(denied)} |",
        f"| Cross-service attempts blocked | {len(cross)} |",
        f"| Unverified or insecure changes that reached a canary | {len(insecure_shipped)} |",
        f"| Median time to proposed patch | {fmt_seconds(to_patch)} |",
        f"| Median time to verified recovery | {fmt_seconds(recovery)} |",
        f"| Model cost per incident | {meta.get('cost', 'n/a (scripted worker, no model calls)')} |",
        "",
        "## Which gate caught which failure",
        "",
        "| Gate | Rejections |",
        "|---|---|",
    ]
    lines += [f"| {gate} | {count} |" for gate, count in gate_catches.most_common()] or [
        "| - | 0 |"
    ]
    lines += ["", "## Red-team results (attack playbook)", "",
              "| Category | Attempts | Blocked |", "|---|---|---|"]  # fmt: skip
    lines += [f"| {c} | {n} | {blocked_by_category[c]} |" for c, n in sorted(by_category.items())]
    escaped = [a for a in attacks if not a["blocked"]]
    lines += ["", f"Attacks that were NOT blocked: {len(escaped)}"]
    lines += [f"- {a['attack']} ({a['tool']}): {a['outcome']}" for a in escaped]
    lines += ["", "## Incidents", "", "| Scenario | Incident | Status | Tool calls A/R/D |",
              "|---|---|---|---|"]  # fmt: skip
    for r in reports:
        calls = r["measures"]["tool_calls"]
        lines.append(f"| {r.get('scenario', '-')} | {r['incident']['incident_id']} | "
                     f"{r['incident']['status']} | {calls['ALLOW']}/{calls['REVIEW']}/{calls['DENY']} |")  # fmt: skip
    return "\n".join(lines) + "\n"


def main() -> int:
    runs = sorted((ROOT / "evidence").glob("*/run.json"))
    run = Path(sys.argv[1]) if len(sys.argv) > 1 else (runs[-1].parent if runs else None)
    if run is None:
        print("no experiment runs found in evidence/")
        return 1
    target = ROOT / "docs" / "experiments" / f"results-{run.name}.md"
    target.write_text(build(run), encoding="utf-8")
    print(f"wrote {target.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
