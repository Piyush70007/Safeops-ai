"""Inventory domain: product catalogue and atomic stock reservations."""

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.common.db import products
from app.common.errors import Conflict, DependencyUnavailable, NotFound

SEED_PRODUCTS = [
    {"sku": "GEAR-42", "name": "Gear wheel 42T", "stock": 500, "price_cents": 1999},
    {"sku": "BOLT-M8", "name": "Bolt M8 x 40", "stock": 10000, "price_cents": 12},
    {"sku": "PUMP-7", "name": "Hydraulic pump P7", "stock": 25, "price_cents": 45900},
]


def _db_error(exc: SQLAlchemyError) -> DependencyUnavailable:
    return DependencyUnavailable("database", type(exc).__name__)


def seed(engine: Engine) -> None:
    try:
        with engine.begin() as conn:
            if conn.execute(select(products.c.sku).limit(1)).first() is None:
                conn.execute(insert(products), SEED_PRODUCTS)
    except SQLAlchemyError as exc:
        raise _db_error(exc) from exc


def get_product(engine: Engine, sku: str) -> dict:
    try:
        with engine.connect() as conn:
            row = conn.execute(select(products).where(products.c.sku == sku)).mappings().first()
    except SQLAlchemyError as exc:
        raise _db_error(exc) from exc
    if row is None:
        raise NotFound(f"unknown product {sku}")
    return dict(row)


def reserve(engine: Engine, sku: str, quantity: int) -> dict:
    """Atomically take `quantity` items. The WHERE clause makes overselling impossible."""
    try:
        with engine.begin() as conn:
            result = conn.execute(
                update(products)
                .where(products.c.sku == sku, products.c.stock >= quantity)
                .values(stock=products.c.stock - quantity)
            )
            row = conn.execute(select(products).where(products.c.sku == sku)).mappings().first()
    except SQLAlchemyError as exc:
        raise _db_error(exc) from exc
    if row is None:
        raise NotFound(f"unknown product {sku}")
    if result.rowcount == 0:
        raise Conflict(f"only {row['stock']} items of {sku} in stock")
    return {
        "sku": sku,
        "reserved": quantity,
        "remaining": row["stock"],
        "unit_price_cents": row["price_cents"],
    }


def release(engine: Engine, sku: str, quantity: int) -> dict:
    try:
        with engine.begin() as conn:
            result = conn.execute(
                update(products)
                .where(products.c.sku == sku)
                .values(stock=products.c.stock + quantity)
            )
    except SQLAlchemyError as exc:
        raise _db_error(exc) from exc
    if result.rowcount == 0:
        raise NotFound(f"unknown product {sku}")
    return {"sku": sku, "released": quantity}
