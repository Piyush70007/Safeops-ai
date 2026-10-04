"""Payments domain: a simulated payment provider (no real card data is ever handled).

A card_token is an opaque reference such as tok_visa_ok. Tokens starting with tok_decline
and amounts above the configured limit are declined.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import insert, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.common.db import payments
from app.common.errors import DependencyUnavailable, NotFound


def authorize(engine: Engine, order_id: str, amount_cents: int, card_token: str, limit: int):
    declined = card_token.startswith("tok_decline") or amount_cents > limit
    record = {
        "payment_id": "PAY-" + uuid.uuid4().hex[:12].upper(),
        "order_id": order_id,
        "amount_cents": amount_cents,
        "status": "DECLINED" if declined else "APPROVED",
        "created_at": datetime.now(UTC),
    }
    try:
        with engine.begin() as conn:
            conn.execute(insert(payments).values(**record))
    except SQLAlchemyError as exc:
        raise DependencyUnavailable("database", type(exc).__name__) from exc
    return record


def get_payment(engine: Engine, payment_id: str) -> dict:
    try:
        with engine.connect() as conn:
            row = (
                conn.execute(select(payments).where(payments.c.payment_id == payment_id))
                .mappings()
                .first()
            )
    except SQLAlchemyError as exc:
        raise DependencyUnavailable("database", type(exc).__name__) from exc
    if row is None:
        raise NotFound(f"unknown payment {payment_id}")
    return dict(row)
