"""safeops-tool: the command Codex uses to call the gateway.

  safeops-tool get_incident_brief
  safeops-tool get_logs service=inventory minutes=30 contains=KeyError
  safeops-tool get_metrics service=inventory query=error_ratio
  safeops-tool submit_patch diff=@/workspace/fix.diff summary="fix cache key"

Exit codes: 0 allowed, 2 denied, 3 waiting for human approval, 1 other error.
"""

import json
import sys
from pathlib import Path

from safeops_worker.client import GatewayClient


def parse(pairs: list[str]) -> dict:
    args = {}
    for pair in pairs:
        key, _, value = pair.partition("=")
        if value.startswith("@"):
            args[key] = Path(value[1:]).read_text(encoding="utf-8")
            continue
        try:
            args[key] = json.loads(value)
        except json.JSONDecodeError:
            args[key] = value
    return args


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    status, body = GatewayClient().call(argv[0], **parse(argv[1:]))
    print(json.dumps(body, indent=2))
    return {200: 0, 403: 2, 202: 3}.get(status, 1)


if __name__ == "__main__":
    sys.exit(main())
