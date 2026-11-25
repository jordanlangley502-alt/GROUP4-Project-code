"""Small Python enums for POS data."""

from enum import Enum


class OrderType(str, Enum):
    DINE_IN = "dine_in"
    TAKEOUT = "takeout"
    DELIVERY = "delivery"


class OrderStatus(str, Enum):
    CONFIRMED = "Confirmed"
    MAKING = "Making"
    READY = "Ready"
