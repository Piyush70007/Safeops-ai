"""Inventory HTTP API."""

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.services.inventory import service

router = APIRouter(prefix="/inventory", tags=["inventory"])
SKU = r"^[A-Z0-9-]{3,32}$"


class StockChange(BaseModel):
    sku: str = Field(pattern=SKU)
    quantity: int = Field(ge=1, le=1000)


@router.get("/{sku}")
def get_product(sku: str, request: Request) -> dict:
    return service.get_product(request.app.state.engine, sku)


@router.post("/reserve")
def reserve(body: StockChange, request: Request) -> dict:
    return service.reserve(request.app.state.engine, body.sku, body.quantity)


@router.post("/release")
def release(body: StockChange, request: Request) -> dict:
    return service.release(request.app.state.engine, body.sku, body.quantity)
