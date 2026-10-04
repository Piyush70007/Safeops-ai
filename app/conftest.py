import pytest
from fastapi.testclient import TestClient

from app.common.config import Settings
from app.common.db import make_engine
from app.main import create_app
from app.services.orders.clients import HttpClients


def settings(mode: str, **overrides) -> Settings:
    return Settings(
        service_mode=mode, database_url="sqlite+pysqlite:///:memory:", environment="test",
        faults_enabled=True, **overrides,
    )  # fmt: skip


@pytest.fixture
def monolith():
    app = create_app(settings("monolith"), engine=make_engine("sqlite+pysqlite:///:memory:"))
    with TestClient(app) as client:
        yield client


@pytest.fixture
def services():
    """Three separate apps, each with its own database, wired together over HTTP."""
    inventory = TestClient(
        create_app(settings("inventory"), engine=make_engine("sqlite+pysqlite:///:memory:")),
        base_url="http://inventory",
    )
    payments = TestClient(
        create_app(settings("payments"), engine=make_engine("sqlite+pysqlite:///:memory:")),
        base_url="http://payments",
    )
    with inventory, payments:
        orders_app = create_app(
            settings("orders"),
            engine=make_engine("sqlite+pysqlite:///:memory:"),
            http_clients=HttpClients(inventory, payments),
        )
        with TestClient(orders_app) as orders:
            yield {"orders": orders, "inventory": inventory, "payments": payments}


@pytest.fixture
def order_payload() -> dict:
    return {
        "customer_id": "CUST-1001",
        "sku": "GEAR-42",
        "quantity": 2,
        "card_token": "tok_visa_ok",
    }
