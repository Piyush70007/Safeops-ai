"""Orders HTTP API."""

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from app.services.orders import service

router = APIRouter(prefix="/orders", tags=["orders"])


class OrderRequest(BaseModel):
    customer_id: str = Field(pattern=r"^[A-Za-z0-9-]{3,64}$")
    sku: str = Field(pattern=r"^[A-Z0-9-]{3,32}$")
    quantity: int = Field(ge=1, le=1000)
    card_token: str = Field(pattern=r"^tok_[a-z0-9_]{3,40}$")
    note: str | None = Field(default=None, max_length=500)


@router.post("", status_code=201)
def create_order(body: OrderRequest, request: Request) -> dict:
    return service.place_order(
        request.app.state.engine,
        request.app.state.clients,
        body.customer_id,
        body.sku,
        body.quantity,
        body.card_token,
        body.note,
    )


@router.get("")
def list_orders(request: Request, limit: int = Query(default=20, ge=1, le=100)) -> list[dict]:
    return service.list_orders(request.app.state.engine, limit)


@router.get("/{order_id}")
def get_order(order_id: str, request: Request) -> dict:
    return service.get_order(request.app.state.engine, order_id)
