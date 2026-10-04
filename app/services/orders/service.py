"""Orders domain: reserve stock, authorize payment, compensate on decline."""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import insert, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.common.db import orders
from app.common.errors import DependencyUnavailable, NotFound

logger = logging.getLogger("orders")


def place_order(engine: Engine, clients, customer_id, sku, quantity, card_token, note=None):
    order_id = "ORD-" + uuid.uuid4().hex[:12].upper()
    # The note is customer-controlled text. It is logged as a data field, never executed.
    logger.info("order received", extra={"order_id": order_id, "sku": sku, "note": note})
    reservation = clients.reserve(sku, quantity)
    amount = reservation["unit_price_cents"] * quantity
    try:
        payment = clients.authorize(order_id, amount, card_token)
    except Exception:
        clients.release(sku, quantity)  # compensation: never keep stock for a failed payment
        raise
    status = "CONFIRMED" if payment["status"] == "APPROVED" else "REJECTED"
    if status == "REJECTED":
        clients.release(sku, quantity)
    record = {
        "order_id": order_id,
        "customer_id": customer_id,
        "sku": sku,
        "quantity": quantity,
        "amount_cents": amount,
        "status": status,
        "payment_id": payment["payment_id"],
        "created_at": datetime.now(UTC),
    }
    try:
        with engine.begin() as conn:
            conn.execute(insert(orders).values(**record))
    except SQLAlchemyError as exc:
        raise DependencyUnavailable("database", type(exc).__name__) from exc
    logger.info("order completed", extra={"order_id": order_id, "status": status})
    return record


def get_order(engine: Engine, order_id: str) -> dict:
    try:
        with engine.connect() as conn:
            row = conn.execute(select(orders).where(orders.c.order_id == order_id)).mappings()
            found = row.first()
    except SQLAlchemyError as exc:
        raise DependencyUnavailable("database", type(exc).__name__) from exc
    if found is None:
        raise NotFound(f"unknown order {order_id}")
    return dict(found)


def list_orders(engine: Engine, limit: int = 20) -> list[dict]:
    try:
        with engine.connect() as conn:
            query = select(orders).order_by(orders.c.created_at.desc()).limit(limit)
            return [dict(row) for row in conn.execute(query).mappings()]
    except SQLAlchemyError as exc:
        raise DependencyUnavailable("database", type(exc).__name__) from exc
