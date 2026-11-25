"""Jamrock Bitez delivery tracking. Run setup_demo.py before starting."""
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field

app = FastAPI(title="Jamrock Bitez Delivery Tracking")
basic = HTTPBasic()
ROOT = Path(__file__).resolve().parent


@contextmanager
def database():
    db = sqlite3.connect(os.getenv("DELIVERY_DB", str(ROOT / "delivery.sqlite3")))
    db.row_factory = sqlite3.Row
    try:
        with db:
            yield db
    finally:
        db.close()


def user(credentials: HTTPBasicCredentials = Depends(basic)):
    from accounts import authenticate
    role = authenticate(credentials.username, credentials.password)
    if role is None:
        raise HTTPException(401, "Invalid login", headers={"WWW-Authenticate": "Basic"})
    return credentials.username, role


class Confirmation(BaseModel):
    order_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    order_type: Literal["delivery", "takeout", "dine-in"]
    address: str = Field(default="", max_length=500)
    phone: str = Field(default="", max_length=50)
    total_cents: int = Field(strict=True, ge=0, le=999999999)


class Payment(BaseModel):
    cash_cents: int = Field(strict=True, ge=0, le=999999999)


@app.get("/")
def dashboard(actor=Depends(user)):
    return FileResponse(ROOT / "dashboard.html")


@app.get("/api/me")
def current_user(actor=Depends(user)):
    return {"name": actor[0], "role": actor[1]}


@app.post("/api/confirm")
def confirm(order: Confirmation, actor=Depends(user)):
    if actor[1] != "cashier":
        raise HTTPException(403, "Cashier login required")
    if order.order_type != "delivery":
        return {"tracked": False}
    address, phone = order.address.strip(), order.phone.strip()
    if not address or not phone:
        raise HTTPException(422, "Enter a delivery address and phone number")
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        fields = (address, phone, order.total_cents)
        existing = db.execute("SELECT address, phone, total_cents FROM deliveries WHERE id=?", (order.order_id,)).fetchone()
        if existing and tuple(existing) != fields:
            raise HTTPException(409, "Order ID already has different details")
        if not existing:
            db.execute("INSERT INTO deliveries(id,address,phone,total_cents,confirmed_at,confirmed_by) VALUES(?,?,?,?,?,?)",
                       (order.order_id, *fields, now(), actor[0]))
    return {"tracked": True}


def now():
    return datetime.now(timezone.utc).isoformat()


@app.get("/api/deliveries")
def deliveries(actor=Depends(user)):
    with database() as db:
        rows = db.execute("SELECT *, cash_cents != total_cents AS mismatch FROM deliveries ORDER BY confirmed_at DESC")
        return [dict(row) for row in rows]


@app.post("/api/deliveries/{order_id}/pickup")
def pickup(order_id: str, actor=Depends(user)):
    if actor[1] != "driver":
        raise HTTPException(403, "Driver login required")
    with database() as db:
        changed = db.execute("""UPDATE deliveries SET status='Out for Delivery', driver=?, picked_at=?
                                WHERE id=? AND status='Awaiting Pickup'""", (actor[0], now(), order_id))
        if not changed.rowcount:
            raise HTTPException(409, "Order unavailable for pickup")
    return {"status": "Out for Delivery"}


@app.post("/api/deliveries/{order_id}/complete")
def complete(order_id: str, payment: Payment, actor=Depends(user)):
    if actor[1] != "driver":
        raise HTTPException(403, "Driver login required")
    with database() as db:
        changed = db.execute("""UPDATE deliveries SET status='Delivered', delivered_at=?, cash_cents=?
                                WHERE id=? AND driver=? AND status='Out for Delivery'""",
                             (now(), payment.cash_cents, order_id, actor[0]))
        if not changed.rowcount:
            raise HTTPException(409, "Only the assigned driver can complete an active delivery")
    return {"status": "Delivered"}
