"""Gateway client (standard library only). The worker's ONLY way to act on the world."""

import json
import os
import urllib.error
import urllib.request


class GatewayClient:
    def __init__(self, base_url: str | None = None, token: str | None = None, transport=None):
        self.base_url = (base_url or os.environ["SAFEOPS_GATEWAY_URL"]).rstrip("/")
        if not self.base_url.startswith(("http://", "https://")):
            raise ValueError("SAFEOPS_GATEWAY_URL must be an http(s) URL")
        self.token = token or os.environ["SAFEOPS_TOKEN"]
        self.transport = transport or self._urllib

    def call(self, tool: str, **args) -> tuple[int, dict]:
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        return self.transport(f"/v1/tools/{tool}", {"args": args}, headers)

    def _urllib(self, path: str, body: dict, headers: dict) -> tuple[int, dict]:
        request = urllib.request.Request(
            self.base_url + path, data=json.dumps(body).encode(), headers=headers, method="POST"
        )
        try:
            # The scheme is restricted to http(s) in __init__, so Bandit B310 does not apply.
            with urllib.request.urlopen(request, timeout=300) as response:  # nosec B310
                return response.status, json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read() or b"{}")
