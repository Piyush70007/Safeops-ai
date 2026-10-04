"""HTTP API of the SafeOps control plane.

POST /webhooks/alertmanager        alerts in (admin token)
GET  /incidents[/{id}[/report]]    state and evidence (admin token)
POST /incidents/{id}/approvals     human approval of a parked action (admin token)
POST /incidents/{id}/artifacts     CI registers the verified image digest (admin token)
POST /incidents/{id}/stop          kill switch (admin token)
POST /incidents/{id}/worker-token  token for a manually started worker (admin token)
POST /v1/tools/{tool}              THE GATEWAY: every AI tool call (worker token)
GET  /audit/verify, /health, /metrics
"""

import hmac
import json
import threading
from contextlib import asynccontextmanager

import yaml
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field

from automation.controlplane import adapters
from automation.controlplane.audit import AuditLog, verify
from automation.controlplane.config import ControlSettings, get_control_settings
from automation.controlplane.jev import HttpJev, JevLite
from automation.controlplane.models import Status
from automation.controlplane.policy import PolicyClient
from automation.controlplane.service import ControlPlane


class Unavailable:
    """Placeholder for an adapter that is not configured: every call fails loudly."""

    def __init__(self, name: str) -> None:
        self.name = name

    def __getattr__(self, _):
        def fail(*args, **kwargs):
            raise RuntimeError(f"{self.name} is not configured")

        return fail


def build_control_plane(settings: ControlSettings) -> ControlPlane:
    catalog = json.loads(settings.catalog_file.read_text(encoding="utf-8"))["catalog"]
    services = yaml.safe_load(settings.services_file.read_text(encoding="utf-8"))["services"]
    kube = settings.kubernetes
    launchers = {
        "none": adapters.NoLauncher,
        "docker": lambda: adapters.DockerLauncher(settings.worker_image,
                                                  settings.gateway_url_for_workers),
        "kubernetes": lambda: adapters.KubernetesJobLauncher(settings.worker_image,
                                                             settings.gateway_url_for_workers),
    }  # fmt: skip
    return ControlPlane(
        settings,
        policy=PolicyClient(settings.opa_url),
        jev=HttpJev(settings.jev_url) if settings.jev_url else JevLite(settings.jev_rules),
        audit=AuditLog(settings.audit_path),
        services=services,
        catalog=catalog,
        metrics=adapters.PrometheusMetrics(settings.prometheus_url)
        if settings.prometheus_url
        else Unavailable("prometheus"),
        logs=adapters.LokiLogs(settings.loki_url) if settings.loki_url else Unavailable("loki"),
        cluster=adapters.KubernetesCluster() if kube else Unavailable("kubernetes"),
        deployer=adapters.ArgoDeployer() if kube else Unavailable("argo rollouts"),
        repo=adapters.GitRepository(settings.repo_path, settings.base_ref),
        launcher=launchers[settings.launcher](),
        notifier=adapters.N8nNotifier(settings.n8n_webhook_url),
    )


class ToolRequest(BaseModel):
    args: dict = Field(default_factory=dict)


class Approval(BaseModel):
    action: str = Field(pattern=r"^[a-z_]{3,40}$")
    approver: str = Field(min_length=2, max_length=80)


class Artifact(BaseModel):
    image: str = Field(max_length=300)


class StopRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)
    actor: str = Field(default="operator", max_length=80)


def create_control_app(cp: ControlPlane | None = None, settings: ControlSettings | None = None):
    settings = settings or get_control_settings()
    stop_event = threading.Event()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.cp = cp or build_control_plane(settings)
        if settings.kubernetes:  # poll Argo Rollouts for canary verdicts

            def loop():
                while not stop_event.wait(15):
                    for incident in list(app.state.cp.incidents.values()):
                        if incident.status == Status.CANARY:
                            app.state.cp.refresh_canary(incident.incident_id)

            threading.Thread(target=loop, daemon=True).start()
        yield
        stop_event.set()

    app = FastAPI(title="SafeOps AI control plane", lifespan=lifespan)

    def admin(authorization: str = Header(default="")) -> None:
        expected = settings.admin_token
        if not expected or not hmac.compare_digest(authorization, f"Bearer {expected}"):
            raise HTTPException(status_code=401, detail="admin token required")

    def incident_or_404(incident_id: str):
        incident = app.state.cp.incidents.get(incident_id)
        if not incident:
            raise HTTPException(status_code=404, detail="unknown incident")
        return incident

    @app.post("/webhooks/alertmanager", dependencies=[Depends(admin)])
    def alertmanager(payload: dict) -> dict:
        return {"incidents": app.state.cp.handle_alerts(payload)}

    @app.get("/incidents", dependencies=[Depends(admin)])
    def list_incidents() -> list[dict]:
        return [
            {"incident_id": i.incident_id, "service": i.service, "status": i.status,
             "title": i.title, "alerts": i.seen_alerts, "tool_calls": i.tool_calls}
            for i in app.state.cp.incidents.values()
        ]  # fmt: skip

    @app.get("/incidents/{incident_id}", dependencies=[Depends(admin)])
    def get_incident(incident_id: str) -> dict:
        data = incident_or_404(incident_id).model_dump(mode="json")
        if data.get("patch"):
            data["patch"] = {k: v for k, v in data["patch"].items() if k != "diff"}
        return data

    @app.get("/incidents/{incident_id}/report", dependencies=[Depends(admin)])
    def report(incident_id: str) -> dict:
        incident_or_404(incident_id)
        return app.state.cp.report(incident_id)

    @app.get("/incidents/{incident_id}/patch", dependencies=[Depends(admin)])
    def get_patch(incident_id: str) -> Response:
        incident = incident_or_404(incident_id)
        if not incident.patch:
            raise HTTPException(status_code=404, detail="no patch submitted")
        return Response(incident.patch["diff"], media_type="text/x-diff")

    @app.post("/incidents/{incident_id}/approvals", dependencies=[Depends(admin)])
    def approve(incident_id: str, body: Approval) -> dict:
        incident_or_404(incident_id)
        try:
            return {"status": app.state.cp.approve(incident_id, body.action, body.approver).status}
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/incidents/{incident_id}/artifacts", dependencies=[Depends(admin)])
    def artifact(incident_id: str, body: Artifact) -> dict:
        incident_or_404(incident_id)
        try:
            app.state.cp.register_artifact(incident_id, body.image)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"registered": body.image}

    @app.post("/incidents/{incident_id}/stop", dependencies=[Depends(admin)])
    def stop(incident_id: str, body: StopRequest) -> dict:
        incident_or_404(incident_id)
        return {"status": app.state.cp.stop(incident_id, body.reason, body.actor).status}

    @app.post("/incidents/{incident_id}/refresh", dependencies=[Depends(admin)])
    def refresh(incident_id: str) -> dict:
        incident_or_404(incident_id)
        return {"status": app.state.cp.refresh_canary(incident_id).status}

    @app.post("/incidents/{incident_id}/worker-token", dependencies=[Depends(admin)])
    def worker_token(incident_id: str) -> dict:
        incident = incident_or_404(incident_id)
        if not incident.grant_id:
            raise HTTPException(status_code=409, detail="no grant: incident is not AI-eligible")
        return {"token": app.state.cp.issue_token(incident_id)}

    @app.post("/v1/tools/{tool}")
    def gateway(tool: str, body: ToolRequest, authorization: str = Header(default="")):
        token = authorization.removeprefix("Bearer ").strip()
        status, payload = app.state.cp.tool_call(token, tool[:64], body.args)
        return JSONResponse(payload, status_code=status)

    @app.get("/audit/verify", dependencies=[Depends(admin)])
    def audit_verify() -> dict:
        problems = verify(app.state.cp.audit.path) if app.state.cp.audit.path.exists() else []
        return {"intact": not problems, "problems": problems}

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


def build():
    """uvicorn --factory automation.controlplane.main:build"""
    return create_control_app()
