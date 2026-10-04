"""CLI for the verification gates, used by GitHub Actions on patch branches.

  python -m verification.run_gates --base origin/main --allowed 'app/services/inventory/**'
Exit code 0 = all gates passed, 1 = at least one failed. Writes verification-report.json.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from verification.gates import verify_patch

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run SafeOps verification gates on a branch")
    parser.add_argument("--base", required=True, help="base ref, e.g. origin/main")
    parser.add_argument("--allowed", nargs="+", required=True, help="writable path patterns")
    parser.add_argument("--report", default="verification-report.json")
    args = parser.parse_args()

    diff = subprocess.run(
        ["git", "diff", f"{args.base}...HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    catalog = json.loads((ROOT / "automation/policy-engine/data/catalog.json").read_text())
    result = verify_patch(ROOT, args.base, diff, args.allowed, catalog["catalog"]["never_writable"])
    Path(args.report).write_text(json.dumps(result, indent=2), encoding="utf-8")
    for item in result["gates"]:
        print(f"[{'PASS' if item['passed'] else 'FAIL'}] {item['gate']}: {item['details'][:200]}")
    print("ALL GATES PASSED" if result["passed"] else "VERIFICATION FAILED")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
