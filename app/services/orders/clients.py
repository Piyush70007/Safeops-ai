"""How the orders service talks to inventory and payments.

Monolith mode: direct function calls (LocalClients). Microservice mode: HTTP (HttpClients).
The order logic does not know the difference - which is exactly what makes the
monolith-versus-microservices blast-radius comparison fair.
"""

import httpx

from app.common.errors import Conflict, DependencyUnavailable, NotFound
from app.common.logging_setup import correlation_id_var
from app.services.inventory import service as inventory
from app.services.payments import service as payments


class LocalClients:
    def __init__(self, engine, payments_limit_cents: int) -> None:
        self.engine = engine
        self.limit = payments_limit_cents

    def reserve(self, sku: str, quantity: int) -> dict:
        return inventory.reserve(self.engine, sku, quantity)

    def release(self, sku: str, quantity: int) -> dict:
        return inventory.release(self.engine, sku, quantity)

    def authorize(self, order_id: str, amount_cents: int, card_token: str) -> dict:
        return payments.authorize(self.engine, order_id, amount_cents, card_token, self.limit)


class HttpClients:
    def __init__(self, inventory_http: httpx.Client, payments_http: httpx.Client) -> None:
        self.inventory_http = inventory_http
        self.payments_http = payments_http

    def _call(self, client: httpx.Client, dependency: str, path: str, body: dict) -> dict:
        headers = {"X-Request-ID": correlation_id_var.get()}
        try:
            response = client.post(path, json=body, headers=headers)
        except httpx.HTTPError as exc:
            raise DependencyUnavailable(dependency, type(exc).__name__) from exc
        if response.status_code == 404:
            raise NotFound(response.json().get("detail", "not found"))
        if response.status_code == 409:
            raise Conflict(response.json().get("detail", "conflict"))
        if response.status_code >= 500:
            raise DependencyUnavailable(dependency, f"HTTP {response.status_code}")
        response.raise_for_status()
        return response.json()

    def reserve(self, sku: str, quantity: int) -> dict:
        body = {"sku": sku, "quantity": quantity}
        return self._call(self.inventory_http, "inventory", "/inventory/reserve", body)

    def release(self, sku: str, quantity: int) -> dict:
        body = {"sku": sku, "quantity": quantity}
        return self._call(self.inventory_http, "inventory", "/inventory/release", body)

    def authorize(self, order_id: str, amount_cents: int, card_token: str) -> dict:
        body = {"order_id": order_id, "amount_cents": amount_cents, "card_token": card_token}
        return self._call(self.payments_http, "payments", "/payments/authorize", body)
