"""Adapters to the outside world. Each exposes narrow, named operations only:
no free-form PromQL/LogQL, no shell, no kubectl passthrough.

Real implementations: Prometheus, Loki, Kubernetes API, Argo Rollouts, Git, worker launchers,
n8n notifications. Fakes for tests and the offline lab live in fakes.py.
"""

import base64
import json
import logging
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

log = logging.getLogger("safeops.adapters")

NAMED_QUERIES = {
    "error_ratio": 'sum(rate(shop_http_requests_total{{service="{svc}",status=~"5.."}}[5m]))'
    ' / clamp_min(sum(rate(shop_http_requests_total{{service="{svc}"}}[5m])), 1e-9)',
    "request_rate": 'sum(rate(shop_http_requests_total{{service="{svc}"}}[5m]))',
    "latency_p95": "histogram_quantile(0.95, sum by (le) "
    '(rate(shop_http_request_duration_seconds_bucket{{service="{svc}"}}[5m])))',
    "dependency_errors": "sum by (dependency, reason) "
    '(rate(shop_dependency_errors_total{{service="{svc}"}}[5m]))',
    "cpu_cores": "sum(rate(container_cpu_usage_seconds_total"
    '{{namespace="{ns}",container!=""}}[5m]))',
    "memory_bytes": 'sum(container_memory_working_set_bytes{{namespace="{ns}",container!=""}})',
    "restarts": 'sum(kube_pod_container_status_restarts_total{{namespace="{ns}"}})',
}


class PrometheusMetrics:
    def __init__(self, url: str, http: httpx.Client | None = None) -> None:
        self.url = url.rstrip("/")
        self.http = http or httpx.Client(timeout=10.0)

    def query(self, name: str, service: str, namespace: str, minutes: int) -> dict:
        expr = NAMED_QUERIES[name].format(svc=service, ns=namespace)
        end = time.time()
        params = {
            "query": expr,
            "start": end - minutes * 60,
            "end": end,
            "step": max(15, minutes // 2),
        }
        data = self.http.get(f"{self.url}/api/v1/query_range", params=params).json()
        series = [
            {"labels": s["metric"], "values": [[float(t), v] for t, v in s["values"][-60:]]}
            for s in data.get("data", {}).get("result", [])
        ]
        return {"query": name, "expr": expr, "series": series}


class LokiLogs:
    def __init__(self, url: str, http: httpx.Client | None = None) -> None:
        self.url = url.rstrip("/")
        self.http = http or httpx.Client(timeout=10.0)

    def logs(self, namespace: str, minutes: int, contains: str | None, limit: int) -> list[dict]:
        query = f'{{namespace="{namespace}"}}'
        if contains:  # validated by the argument model: no quotes or backslashes possible
            query += f' |= "{contains}"'
        end = time.time_ns()
        params = {"query": query, "start": end - minutes * 60 * 10**9, "end": end,
                  "limit": limit, "direction": "backward"}  # fmt: skip
        data = self.http.get(f"{self.url}/loki/api/v1/query_range", params=params).json()
        lines = [
            {"at": datetime.fromtimestamp(int(ts) / 1e9, UTC).isoformat(), "line": line}
            for stream in data.get("data", {}).get("result", [])
            for ts, line in stream["values"]
        ]
        return sorted(lines, key=lambda entry: entry["at"])


def _kube_clients():
    from kubernetes import client, config

    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()
    return client


class KubernetesCluster:
    """Read-only inspection plus one reversible action (restart). Namespaced only."""

    def __init__(self) -> None:
        client = _kube_clients()
        self.core = client.CoreV1Api()
        self.apps = client.AppsV1Api()
        self.custom = client.CustomObjectsApi()

    def inspect(self, namespace: str, kind: str, name: str | None = None) -> list[dict]:
        if kind == "pods":
            pods = self.core.list_namespaced_pod(namespace).items
            return [
                {
                    "name": p.metadata.name,
                    "phase": p.status.phase,
                    "ready": all(c.ready for c in (p.status.container_statuses or [])),
                    "restarts": sum(c.restart_count for c in (p.status.container_statuses or [])),
                    "waiting": [
                        c.state.waiting.reason
                        for c in (p.status.container_statuses or [])
                        if c.state and c.state.waiting
                    ],
                }
                for p in pods
                if name is None or p.metadata.name == name
            ]
        if kind == "events":
            events = self.core.list_namespaced_event(namespace).items[-30:]
            return [{"type": e.type, "reason": e.reason, "object": e.involved_object.name,
                     "message": e.message} for e in events]  # fmt: skip
        if kind == "rollouts":
            items = self.custom.list_namespaced_custom_object(
                "argoproj.io", "v1alpha1", namespace, "rollouts"
            )["items"]
            return [{"name": r["metadata"]["name"], "phase": r.get("status", {}).get("phase"),
                     "message": r.get("status", {}).get("message")} for r in items]  # fmt: skip
        if kind == "services":
            return [{"name": s.metadata.name, "ports": [p.port for p in s.spec.ports]}
                    for s in self.core.list_namespaced_service(namespace).items]  # fmt: skip
        if kind in ("deployments", "replicasets"):
            lister = (self.apps.list_namespaced_deployment if kind == "deployments"
                      else self.apps.list_namespaced_replica_set)  # fmt: skip
            items = lister(namespace).items
            return [
                {
                    "name": d.metadata.name,
                    "replicas": d.status.replicas,
                    "ready": d.status.ready_replicas,
                }
                for d in items
            ]
        return []

    def restart(self, namespace: str, workload: str) -> dict:
        stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.custom.patch_namespaced_custom_object(
            "argoproj.io",
            "v1alpha1",
            namespace,
            "rollouts",
            workload,
            {"spec": {"restartAt": stamp}},
        )
        return {"restarted": workload, "at": stamp}


class ArgoDeployer:
    """Argo Rollouts owns canary analysis, promotion and abort. We only set the image."""

    def __init__(self) -> None:
        self.custom = _kube_clients().CustomObjectsApi()

    def _get(self, namespace: str, workload: str) -> dict:
        return self.custom.get_namespaced_custom_object(
            "argoproj.io", "v1alpha1", namespace, "rollouts", workload
        )

    def current_image(self, namespace: str, workload: str) -> str:
        return self._get(namespace, workload)["spec"]["template"]["spec"]["containers"][0]["image"]

    def set_image(self, namespace: str, workload: str, image: str) -> None:
        rollout = self._get(namespace, workload)
        containers = rollout["spec"]["template"]["spec"]["containers"]
        containers[0]["image"] = image
        patch = {"spec": {"template": {"spec": {"containers": containers}}}}
        self.custom.patch_namespaced_custom_object(
            "argoproj.io", "v1alpha1", namespace, "rollouts", workload, patch
        )

    def phase(self, namespace: str, workload: str) -> str:
        status = self._get(namespace, workload).get("status", {})
        return "Aborted" if status.get("abort") else status.get("phase", "Unknown")


class GitRepository:
    def __init__(self, path: Path, base_ref: str) -> None:
        self.path, self.base_ref = path, base_ref

    def refresh(self) -> None:
        """Fetch the latest commits if the checkout has a remote (in-cluster clone)."""
        remotes = subprocess.run(["git", "remote"], cwd=self.path, capture_output=True, text=True)
        if "origin" in remotes.stdout.split():
            subprocess.run(["git", "fetch", "--quiet", "origin"], cwd=self.path, timeout=60,
                           capture_output=True, check=False)  # fmt: skip

    def commit(self) -> str:
        return subprocess.run(
            ["git", "rev-parse", self.base_ref], cwd=self.path, capture_output=True, text=True,
            check=True,
        ).stdout.strip()  # fmt: skip

    def snapshot(self, commit: str, max_bytes: int = 25_000_000) -> dict:
        """The pinned commit as a tar.gz: the worker never gets Git credentials."""
        archive = subprocess.run(
            ["git", "archive", "--format=tar.gz", commit], cwd=self.path,
            capture_output=True, check=True,
        ).stdout  # fmt: skip
        if len(archive) > max_bytes:
            raise ValueError("repository snapshot too large")
        return {"commit": commit, "format": "tar.gz",
                "archive_b64": base64.b64encode(archive).decode()}  # fmt: skip


class NoLauncher:
    """Manual mode: the operator starts the worker with the printed command."""

    def launch(self, incident_id: str, token: str) -> dict:
        log.info("worker not started automatically", extra={"incident_id": incident_id})
        return {
            "launcher": "manual",
            "hint": "start ai-worker with SAFEOPS_TOKEN for " + incident_id,
        }


class DockerLauncher:
    def __init__(self, image: str, gateway_url: str, network: str = "safeops-workers") -> None:
        self.image, self.gateway_url, self.network = image, gateway_url, network

    def launch(self, incident_id: str, token: str) -> dict:
        name = f"safeops-worker-{incident_id.lower()}"
        # /tmp and /workspace below are tmpfs mounts INSIDE the worker container (Bandit B108 n/a)
        cmd = [
            "docker", "run", "-d", "--rm", "--name", name, "--network", self.network,
            "--read-only",
            "--tmpfs", "/tmp:size=512m",  # noqa: S108  # nosec B108
            "--tmpfs", "/workspace:size=1g,uid=10001",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
            "--memory", "2g", "--cpus", "2", "--pids-limit", "512",
            "-e", f"SAFEOPS_GATEWAY_URL={self.gateway_url}", "-e", f"INCIDENT_ID={incident_id}",
            "-e", "SAFEOPS_TOKEN", "-e", "CODEX_API_KEY", self.image,
        ]  # fmt: skip
        env = {"SAFEOPS_TOKEN": token, "PATH": "/usr/bin:/bin:/usr/local/bin"}
        import os

        if os.environ.get("CODEX_API_KEY"):
            env["CODEX_API_KEY"] = os.environ["CODEX_API_KEY"]
        result = subprocess.run(cmd, capture_output=True, text=True, env=env, check=False)
        return {"launcher": "docker", "container": name, "ok": result.returncode == 0,
                "error": result.stderr[-300:]}  # fmt: skip


class KubernetesJobLauncher:
    """Ephemeral Job in the safeops-workers namespace; NetworkPolicy limits its egress."""

    def __init__(self, image: str, gateway_url: str, namespace: str = "safeops-workers") -> None:
        self.image, self.gateway_url, self.namespace = image, gateway_url, namespace
        client = _kube_clients()
        self.client, self.batch, self.core = client, client.BatchV1Api(), client.CoreV1Api()

    def launch(self, incident_id: str, token: str) -> dict:
        c = self.client
        name = f"worker-{incident_id.lower()}"
        self.core.create_namespaced_secret(
            self.namespace,
            c.V1Secret(metadata=c.V1ObjectMeta(name=name), string_data={"token": token}),
        )
        env = [
            c.V1EnvVar(name="INCIDENT_ID", value=incident_id),
            c.V1EnvVar(name="SAFEOPS_GATEWAY_URL", value=self.gateway_url),
            c.V1EnvVar(name="SAFEOPS_TOKEN", value_from=c.V1EnvVarSource(
                secret_key_ref=c.V1SecretKeySelector(name=name, key="token"))),
            c.V1EnvVar(name="CODEX_API_KEY", value_from=c.V1EnvVarSource(
                secret_key_ref=c.V1SecretKeySelector(name="codex-api-key", key="key"))),
        ]  # fmt: skip
        container = c.V1Container(
            name="worker", image=self.image, env=env,
            resources=c.V1ResourceRequirements(limits={"cpu": "2", "memory": "2Gi"}),
            security_context=c.V1SecurityContext(
                run_as_non_root=True, run_as_user=10001, allow_privilege_escalation=False,
                read_only_root_filesystem=True, capabilities=c.V1Capabilities(drop=["ALL"])),
            volume_mounts=[c.V1VolumeMount(name="work", mount_path="/workspace"),
                           c.V1VolumeMount(name="tmp", mount_path="/tmp")],  # noqa: S108  # nosec B108
        )  # fmt: skip
        spec = c.V1JobSpec(
            backoff_limit=0, active_deadline_seconds=1800, ttl_seconds_after_finished=3600,
            template=c.V1PodTemplateSpec(
                metadata=c.V1ObjectMeta(labels={"app": "safeops-worker", "incident": name}),
                spec=c.V1PodSpec(
                    restart_policy="Never", automount_service_account_token=False,
                    containers=[container],
                    volumes=[c.V1Volume(name="work", empty_dir=c.V1EmptyDirVolumeSource()),
                             c.V1Volume(name="tmp", empty_dir=c.V1EmptyDirVolumeSource())],
                ),
            ),
        )  # fmt: skip
        job = c.V1Job(metadata=c.V1ObjectMeta(name=name), spec=spec)
        self.batch.create_namespaced_job(self.namespace, job)
        return {"launcher": "kubernetes", "job": name}


class N8nNotifier:
    """Human-facing notifications only. n8n never authorizes anything."""

    def __init__(self, url: str, http: httpx.Client | None = None) -> None:
        self.url = url
        self.http = http or httpx.Client(timeout=5.0)

    def send(self, event: dict) -> None:
        if not self.url:
            return
        try:
            self.http.post(self.url, content=json.dumps(event, default=str),
                           headers={"Content-Type": "application/json"})  # fmt: skip
        except httpx.HTTPError as exc:
            log.warning("n8n notification failed", extra={"reason": type(exc).__name__})
