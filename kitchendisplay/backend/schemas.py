from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Quantity = Annotated[float, Field(gt=0, allow_inf_nan=False)]
Money = Annotated[Decimal, Field(ge=0, max_digits=10, decimal_places=2, allow_inf_nan=False)]
OrderType = Literal["Dine-in", "Takeout", "Delivery"]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(Input):
    username: Text
    password: Annotated[str, Field(min_length=1, max_length=256)]


class ItemInput(Input):
    name: Text
    unit: Text
    reorder_level: Annotated[float, Field(ge=0, allow_inf_nan=False)] = 0


class StockInput(Input):
    quantity: Quantity
    expiry_date: date


class Removal(Input):
    quantity: Quantity
    reason: Text


class Expiry(Input):
    expiry_date: date


class MenuInput(Input):
    name: Text
    price: Money


class RecipeInput(Input):
    inventory_item_id: Annotated[int, Field(gt=0)]
    quantity_required: Quantity


class OrderLine(Input):
    menu_item_id: Annotated[int, Field(gt=0)]
    quantity: Annotated[int, Field(gt=0, strict=True)]
    special_request: Annotated[str, Field(max_length=500)] = ""


class OrderInput(Input):
    order_type: OrderType
    items: Annotated[list[OrderLine], Field(min_length=1, max_length=100)]
    delivery_address: Text | None = None
    delivery_phone: Text | None = None


class KitchenStatus(Input):
    status: Literal["Making", "Ready"]


class DeliveryStatus(Input):
    status: Literal["Out for Delivery", "Delivered"]
    cash_collected: Money | None = None


class CashCorrection(Input):
    cash_collected: Money


class PaymentInput(Input):
    amount: Money
    method: Literal["Cash", "Card"]
