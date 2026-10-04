"""Payments HTTP API."""

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.services.payments import service

router = APIRouter(prefix="/payments", tags=["payments"])


class AuthorizeRequest(BaseModel):
    order_id: str = Field(pattern=r"^ORD-[A-F0-9]{12}$")
    amount_cents: int = Field(ge=1, le=10_000_000)
    card_token: str = Field(pattern=r"^tok_[a-z0-9_]{3,40}$")


@router.post("/authorize", status_code=201)
def authorize(body: AuthorizeRequest, request: Request) -> dict:
    settings = request.app.state.settings
    return service.authorize(
        request.app.state.engine,
        body.order_id,
        body.amount_cents,
        body.card_token,
        settings.payments_limit_cents,
    )


@router.get("/{payment_id}")
def get_payment(payment_id: str, request: Request) -> dict:
    return service.get_payment(request.app.state.engine, payment_id)
