from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class InputModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class LineItemInput(InputModel):
    menu_item_id: int = Field(gt=0)
    quantity: int = Field(gt=0, strict=True)
    special_request: str | None = None


class OrderCreate(InputModel):
    order_type: Literal["dine_in", "takeout", "delivery"]
    line_items: list[LineItemInput] = Field(min_length=1)
    delivery_address: str | None = None
    customer_phone: str | None = None
    idempotency_key: str | None = None


class MenuItemResponse(BaseModel):
    menu_item_id: int
    name: str
    unit_price: Decimal
    is_available: bool


class LineItemResponse(BaseModel):
    line_item_id: int
    menu_item_id: int
    name: str
    quantity: int
    unit_price: Decimal
    special_request: str | None = None
    subtotal: Decimal


class OrderResponse(BaseModel):
    order_id: int
    order_type: Literal["dine_in", "takeout", "delivery"]
    status: Literal["Confirmed", "Making", "Ready"]
    placed_at: str
    total: Decimal
    placed_by: str
    delivery_address: str | None = None
    customer_phone: str | None = None
    idempotency_key: str | None = None
    line_items: list[LineItemResponse]
