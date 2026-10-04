from fastapi.testclient import TestClient

from app.common.config import Settings
from app.common.db import make_engine
from app.conftest import settings
from app.main import create_app


def test_liveness_and_readiness(monolith):
    assert monolith.get("/health/live").json() == {"status": "ok"}
    assert monolith.get("/health/ready").json() == {"status": "ready", "database": "ok"}


def test_readiness_fails_when_database_is_unreachable():
    broken = make_engine("sqlite+pysqlite:////nonexistent-dir/shop.db")
    with TestClient(create_app(settings("inventory"), engine=broken)) as client:
        assert client.get("/health/live").status_code == 200
        response = client.get("/health/ready")
        assert response.status_code == 503
        assert response.json()["status"] == "not_ready"


def test_version_reports_mode_and_build(monolith):
    body = monolith.get("/version").json()
    assert body["mode"] == "monolith"
    assert set(body) == {"service", "mode", "version", "git_sha"}


def test_metrics_use_route_templates(monolith, order_payload):
    order_id = monolith.post("/orders", json=order_payload).json()["order_id"]
    monolith.get(f"/orders/{order_id}")
    text = monolith.get("/metrics").text
    assert 'route="/orders/{order_id}"' in text
    assert order_id not in text  # no IDs in labels: no cardinality explosion


def test_each_mode_exposes_only_its_own_api():
    with TestClient(
        create_app(settings("inventory"), engine=make_engine("sqlite+pysqlite:///:memory:"))
    ) as c:  # noqa: E501
        assert c.get("/inventory/GEAR-42").status_code == 200
        assert c.post("/orders", json={}).status_code == 404
        assert c.post("/payments/authorize", json={}).status_code == 404


def test_faults_are_disabled_by_default():
    disabled = Settings(service_mode="monolith", database_url="sqlite+pysqlite:///:memory:")
    with TestClient(create_app(disabled, engine=make_engine("sqlite+pysqlite:///:memory:"))) as c:
        assert c.get("/faults").status_code == 404
        assert c.post("/faults", json={"error_rate": 1}).status_code == 404


def test_error_fault_hits_business_routes_only(monolith, order_payload):
    monolith.post("/faults", json={"error_rate": 1.0})
    assert monolith.post("/orders", json=order_payload).status_code == 500
    assert monolith.get("/health/ready").status_code == 200
    assert monolith.delete("/faults").json()["error_rate"] == 0
    assert monolith.post("/orders", json=order_payload).status_code == 201


def test_correlation_id_is_echoed_or_replaced(monolith):
    assert (
        monolith.get("/version", headers={"X-Request-ID": "abc-123"}).headers["x-request-id"]
        == "abc-123"
    )  # noqa: E501
    replaced = monolith.get("/version", headers={"X-Request-ID": "bad id <script>"})
    assert replaced.headers["x-request-id"] != "bad id <script>"
