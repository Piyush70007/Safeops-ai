"""Scripted worker: replays a known fix through the real gateway.

It is the deterministic baseline for the evaluation (what a human with the right patch
would do) and it lets the whole pipeline be tested without calling a model.
"""

import time


class ScriptedWorker:
    def __init__(self, client, poll_seconds: float = 5, timeout_seconds: float = 900) -> None:
        self.client = client
        self.poll, self.timeout = poll_seconds, timeout_seconds
        self.trace: list[dict] = []

    def call(self, tool: str, **args) -> tuple[int, dict]:
        status, body = self.client.call(tool, **args)
        self.trace.append({"tool": tool, "status": status, "outcome": body.get("outcome")})
        return status, body

    def wait_for_verification(self) -> dict:
        deadline = time.monotonic() + self.timeout
        while True:
            _, brief = self.call("get_incident_brief")
            result = brief.get("result", {})
            if result.get("status") not in ("PATCH_PROPOSED",) or time.monotonic() > deadline:
                return result
            time.sleep(self.poll)

    def run(self, fix_diff: str, summary: str, request_canary: bool = True) -> dict:
        status, brief = self.call("get_incident_brief")
        if status != 200:
            return {"result": "no_access", "trace": self.trace}
        service = brief["result"]["service"]
        self.call("get_logs", service=service, minutes=30, contains="Error")
        self.call("get_metrics", service=service, query="error_ratio")
        status, body = self.call("submit_patch", diff=fix_diff, summary=summary)
        if status != 200:
            return {"result": "patch_denied", "reasons": body.get("reasons"), "trace": self.trace}
        state = self.wait_for_verification()
        if state.get("status") != "VERIFIED":
            return {"result": "rejected", "state": state, "trace": self.trace}
        if not request_canary:
            return {"result": "verified", "trace": self.trace}
        status, body = self.call("deploy_canary", service=service)
        result = {200: "canary_started", 202: "awaiting_approval"}.get(status, "canary_denied")
        return {"result": result, "body": body, "trace": self.trace}
