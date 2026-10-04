"""Database access with SQLAlchemy Core.

Each service owns its own tables. In monolith mode one database holds all of them;
in microservice mode every service gets its own database (DATABASE_URL per service).
"""

from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import StaticPool

from app.common.errors import DependencyUnavailable

metadata = MetaData()

products = Table(
    "products",
    metadata,
    Column("sku", String(32), primary_key=True),
    Column("name", String(100), nullable=False),
    Column("stock", Integer, nullable=False),
    Column("price_cents", Integer, nullable=False),
)
orders = Table(
    "orders",
    metadata,
    Column("order_id", String(32), primary_key=True),
    Column("customer_id", String(64), nullable=False),
    Column("sku", String(32), nullable=False),
    Column("quantity", Integer, nullable=False),
    Column("amount_cents", Integer, nullable=False),
    Column("status", String(16), nullable=False),
    Column("payment_id", String(32)),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
payments = Table(
    "payments",
    metadata,
    Column("payment_id", String(32), primary_key=True),
    Column("order_id", String(32), nullable=False),
    Column("amount_cents", Integer, nullable=False),
    Column("status", String(16), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
OWNED_TABLES = {"inventory": [products], "orders": [orders], "payments": [payments]}


def make_engine(url: str) -> Engine:
    if url.startswith("sqlite") and ":memory:" in url:
        # one shared in-memory database for the whole test process
        return create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)


def create_tables(engine: Engine, domains: list[str]) -> None:
    tables = [table for domain in domains for table in OWNED_TABLES[domain]]
    metadata.create_all(engine, tables=tables)


def ping(engine: Engine) -> None:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise DependencyUnavailable("database", type(exc).__name__) from exc
