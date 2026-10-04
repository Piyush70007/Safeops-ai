"""Client for the policy engine (OPA). Fails CLOSED: no answer means DENY."""

import httpx


class PolicyClient:
    def __init__(self, opa_url: str, http: httpx.Client | None = None) -> None:
        self.url = opa_url.rstrip("/") + "/v1/data/safeops/authz/decision"
        self.http = http or httpx.Client(timeout=3.0)

    def decide(self, policy_input: dict) -> dict:
        try:
            response = self.http.post(self.url, json={"input": policy_input})
            response.raise_for_status()
            result = response.json().get("result")
        except (httpx.HTTPError, ValueError) as exc:
            return {
                "outcome": "DENY",
                "reasons": [f"policy engine unavailable: {type(exc).__name__}"],
            }
        if not isinstance(result, dict) or result.get("outcome") not in {"ALLOW", "REVIEW", "DENY"}:
            return {"outcome": "DENY", "reasons": ["policy engine returned no valid decision"]}
        return result
