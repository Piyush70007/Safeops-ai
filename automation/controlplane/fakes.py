"""In-memory stand-ins for Prometheus, Loki, Kubernetes and Argo Rollouts.

Used by the test suite and by the offline lab (evaluation without a cluster). They behave
like the real adapters from the control plane's point of view.
"""


class FakeMetrics:
    def __init__(self, values: dict[str, float] | None = None) -> None:
        self.values = values or {"error_ratio": 0.42, "request_rate": 12.0}

    def query(self, name: str, service: str, namespace: str, minutes: int) -> dict:
        value = self.values.get(name, 0.0)
        return {
            "query": name,
            "series": [{"labels": {"service": service}, "values": [[0, str(value)]]}],
        }


class FakeLogs:
    def __init__(self, lines: list[str] | None = None) -> None:
        self.lines = lines or []

    def logs(self, namespace: str, minutes: int, contains: str | None, limit: int) -> list[dict]:
        hits = [line for line in self.lines if not contains or contains in line]
        return [{"at": "2026-10-01T09:00:00+00:00", "line": line} for line in hits[-limit:]]


class FakeCluster:
    def __init__(self) -> None:
        self.restarts: list[tuple[str, str]] = []

    def inspect(self, namespace: str, kind: str, name: str | None = None) -> list[dict]:
        return [
            {"name": f"{namespace}-7d9f-abcde", "phase": "Running", "ready": True, "restarts": 0}
        ]

    def restart(self, namespace: str, workload: str) -> dict:
        self.restarts.append((namespace, workload))
        return {"restarted": workload}


class FakeDeployer:
    """outcome: the phase Argo Rollouts would report after analysis (Healthy or Degraded)."""

    def __init__(self, outcome: str = "Healthy") -> None:
        self.images: dict[tuple[str, str], str] = {}
        self.outcome = outcome
        self.history: list[str] = []

    def current_image(self, namespace: str, workload: str) -> str:
        return self.images.get((namespace, workload), f"ghcr.io/example/{workload}:stable")

    def set_image(self, namespace: str, workload: str, image: str) -> None:
        self.images[(namespace, workload)] = image
        self.history.append(image)

    def phase(self, namespace: str, workload: str) -> str:
        return self.outcome


class RecordingNotifier:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def send(self, event: dict) -> None:
        self.events.append(event)
