import asyncio
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from Inventorytest.InventoryManager import InventoryService
from Inventorytest.MenuItems import MenuService
from Inventorytest.lineitem import LineItem, Order, OrderService
from .database import Transaction, contextmanager_connection, initialize, now
from .security import bearer, current_user, lookup_user, require, token_hash, verify_password
from .schemas import (
    CashCorrection, DeliveryStatus, Expiry, ItemInput, KitchenStatus, Login,
    MenuInput, OrderInput, OrderType, PaymentInput, RecipeInput, Removal, StockInput,
)


def rows(conn, sql, params=()):
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def must_exist(conn, table, key, value):
    # Table and key are internal constants, never client-provided SQL.
    record = conn.execute(f"SELECT * FROM {table} WHERE {key}=?", (value,)).fetchone()
    if record is None:
        raise HTTPException(404, "Record not found.")
    return dict(record)


def cents(value):
    return int(Decimal(str(value)).quantize(Decimal("0.01")) * 100)


def order_detail(conn, order_id):
    result = must_exist(conn, "main.orders", "order_id", order_id)
    result["items"] = rows(conn, "SELECT * FROM line_items WHERE order_id=? ORDER BY line_item_id", (order_id,))
    return result


def delivery_list(conn):
    deliveries = rows(conn, """
        SELECT d.*,u.display_name AS delivery_person,o.total,
               CASE WHEN d.cash_cents IS NULL THEN NULL
                    ELSE d.cash_cents / 100.0 END AS cash_collected
        FROM deliveries.deliveries d JOIN orders o ON o.order_id=d.order_id
        LEFT JOIN users u ON u.user_id=d.assigned_to ORDER BY o.placed_at DESC,o.order_id DESC
    """)
    for item in deliveries:
        item["cash_display"] = "Not collected" if item["cash_cents"] is None else f'{item["cash_cents"] / 100:.2f}'
        item["cash_mismatch"] = item["cash_cents"] is not None and item["cash_cents"] != cents(item["total"])
        item["history"] = rows(conn, """
            SELECT h.status,h.recorded_at,u.display_name AS delivery_person
            FROM delivery_history h JOIN users u ON u.user_id=h.user_id
            WHERE h.order_id=? ORDER BY h.change_id
        """, (item["order_id"],))
    return deliveries


def transaction(request: Request):
    conn = request.app.state.database.connect()
    try:
        conn.execute("BEGIN IMMEDIATE" if request.method in {"POST", "PATCH", "DELETE", "PUT"} else "BEGIN")
        yield Transaction(conn)
        conn.commit()
    except ValueError as exc:
        conn.rollback()
        raise HTTPException(400, str(exc)) from exc
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise HTTPException(409, "This change conflicts with an existing record or data constraint.") from exc
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def change_batch(database, token, after):
    user = lookup_user(database, token)
    if not user:
        return None
    allowed = {
        "Owner": {"orders", "deliveries", "inventory", "menu", "payments"},
        "Supervisor": {"orders", "deliveries", "payments"},
        "Cashier": {"orders", "deliveries", "menu", "payments"},
        "Kitchen": {"orders", "inventory", "menu"},
        "Delivery Person": {"deliveries"},
    }[user["role"]]
    with contextmanager_connection(database) as conn:
        latest = conn.execute("SELECT COALESCE(MAX(event_id),0) FROM change_events").fetchone()[0]
        changes = rows(conn, "SELECT * FROM change_events WHERE event_id>? ORDER BY event_id LIMIT 200", (after,))
    cursor = changes[-1]["event_id"] if changes else after
    return latest, cursor, [event for event in changes if event["topic"] in allowed]


def create_app(data_dir=None):
    @asynccontextmanager
    async def lifespan(app):
        folder = data_dir or os.environ.get("JAMROCK_DATA_DIR") or str(Path(__file__).resolve().parents[1] / "jamrock_data")
        app.state.database = initialize(folder)
        yield

    app = FastAPI(title="Jamrock Bitez Shared Backend", version="0.1.0", lifespan=lifespan)
    origins = [origin.strip() for origin in os.environ.get("JAMROCK_ALLOWED_ORIGINS", "http://localhost:5500,http://127.0.0.1:5500").split(",") if origin.strip()]
    app.state.allowed_origins = origins
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST", "PATCH"], allow_headers=["Authorization", "Content-Type", "Idempotency-Key"])

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/auth/login")
    def login(body: Login, tx=Depends(transaction)):
        user = tx.conn.execute("SELECT * FROM users WHERE username=?", (body.username,)).fetchone()
        # Perform the same password work for unknown names to reduce username timing leaks.
        dummy = "scrypt$" + "00" * 16 + "$" + "00" * 64
        valid = verify_password(body.password, user["password_hash"] if user else dummy)
        if not user or not valid:
            raise HTTPException(401, "Incorrect username or password.")
        token = secrets.token_urlsafe(32)
        tx.conn.execute("DELETE FROM sessions WHERE expires_at<=?", (time.time(),))
        tx.conn.execute("INSERT INTO sessions VALUES (?,?,?)", (token_hash(token), user["user_id"], time.time() + 8 * 3600))
        tx.record(user, "login", user["user_id"], "auth")
        return {"access_token": token, "token_type": "bearer", "expires_in": 28800,
                "user": {k: user[k] for k in ("user_id", "username", "display_name", "role")}}

    @app.get("/auth/me")
    def me(user=Depends(current_user)):
        return user

    @app.post("/auth/logout")
    def logout(user=Depends(current_user), credentials=Depends(bearer), tx=Depends(transaction)):
        tx.conn.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(credentials.credentials),))
        tx.record(user, "logout", user["user_id"], "auth")
        return {"message": "Signed out."}

    @app.get("/menu")
    def menu(user=Depends(require("Cashier", "Kitchen", "Owner")), tx=Depends(transaction)):
        return [dict(item) for item in MenuService(tx).view_menu()]

    @app.post("/menu", status_code=201)
    def add_menu(body: MenuInput, user=Depends(require("Kitchen")), tx=Depends(transaction)):
        MenuService(tx).add_menu_item(body.name, float(body.price))
        item = tx.conn.execute("SELECT * FROM menu.menu_items WHERE name=?", (body.name,)).fetchone()
        tx.record(user, "create_menu_item", item["menu_item_id"], "menu")
        return dict(item)

    @app.post("/menu/{menu_id}/recipe", status_code=201)
    def recipe(menu_id: int, body: RecipeInput, user=Depends(require("Kitchen")), tx=Depends(transaction)):
        must_exist(tx.conn, "menu.menu_items", "menu_item_id", menu_id)
        must_exist(tx.conn, "inventory.inventory_items", "item_id", body.inventory_item_id)
        if tx.conn.execute("SELECT 1 FROM menu.recipes WHERE menu_item_id=? AND inventory_item_id=?", (menu_id, body.inventory_item_id)).fetchone():
            raise HTTPException(409, "Ingredient already exists in this recipe.")
        MenuService(tx).add_recipe(menu_id, body.inventory_item_id, body.quantity_required)
        tx.record(user, "create_recipe", menu_id, "menu")
        return {"menu_item_id": menu_id, **body.model_dump()}

    @app.get("/inventory")
    def inventory(sort: str = Query("name", pattern="^(name|quantity)$"), user=Depends(require("Kitchen", "Owner")), tx=Depends(transaction)):
        items = [{**vars(item), "status": item.get_status()} for item in InventoryService(tx).view_inventory()]
        return sorted(items, key=lambda item: (item[sort], item["item_id"]))

    @app.post("/inventory", status_code=201)
    def add_inventory(body: ItemInput, user=Depends(require("Kitchen")), tx=Depends(transaction)):
        InventoryService(tx).add_item(body.name, body.unit, body.reorder_level)
        item_id = tx.conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        tx.record(user, "create_inventory_item", item_id, "inventory")
        return {"item_id": item_id, **body.model_dump()}

    @app.get("/inventory/expiry")
    def expiry(user=Depends(require("Kitchen", "Owner")), tx=Depends(transaction)):
        return InventoryService(tx).expiry_information()

    @app.post("/inventory/{item_id}/stock", status_code=201)
    def receive(item_id: int, body: StockInput, user=Depends(require("Kitchen")), tx=Depends(transaction)):
        InventoryService(tx).receive_stock(item_id, body.quantity, body.expiry_date.isoformat())
        lot_id = tx.conn.execute("SELECT MAX(lot_id) FROM inventory.stock_lots WHERE item_id=?", (item_id,)).fetchone()[0]
        tx.record(user, "receive_stock", lot_id, "inventory")
        return {"lot_id": lot_id, "item_id": item_id}

    @app.post("/inventory/{item_id}/remove")
    def remove(item_id: int, body: Removal, user=Depends(require("Kitchen")), tx=Depends(transaction)):
        must_exist(tx.conn, "inventory.inventory_items", "item_id", item_id)
        InventoryService(tx).adjust_quantity(item_id, body.quantity, "decrease", body.reason)
        tx.record(user, "remove_stock", item_id, "inventory")
        return {"message": "Stock removed."}

    @app.patch("/inventory/lots/{lot_id}/expiry")
    def edit_expiry(lot_id: int, body: Expiry, user=Depends(require("Kitchen")), tx=Depends(transaction)):
        InventoryService(tx).update_expiry_date(lot_id, body.expiry_date.isoformat())
        tx.record(user, "edit_expiry", lot_id, "inventory")
        return {"lot_id": lot_id, **body.model_dump()}

    @app.get("/orders")
    def orders(order_type: OrderType | None = None, sequence: str = Query("newest", pattern="^(newest|oldest)$"), user=Depends(require("Cashier", "Kitchen", "Owner", "Supervisor")), tx=Depends(transaction)):
        sql = "SELECT order_id FROM orders" + (" WHERE order_type=?" if order_type else "")
        direction = "ASC" if sequence == "oldest" else "DESC"
        ids = tx.conn.execute(sql + f" ORDER BY placed_at {direction},order_id {direction}", (order_type,) if order_type else ()).fetchall()
        return [order_detail(tx.conn, row[0]) for row in ids]

    @app.post("/orders", status_code=201)
    def place(body: OrderInput, request_key: str = Header(..., alias="Idempotency-Key", min_length=1, max_length=128), user=Depends(require("Cashier")), tx=Depends(transaction)):
        fingerprint = hashlib.sha256(json.dumps(body.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()
        saved = tx.conn.execute("SELECT * FROM submissions WHERE user_id=? AND request_key=?", (user["user_id"], request_key)).fetchone()
        if saved:
            if saved["fingerprint"] != fingerprint:
                raise HTTPException(409, "Idempotency-Key was already used for different order data.")
            return order_detail(tx.conn, saved["order_id"])
        order = Order(body.order_type, user["username"])
        for item in body.items:
            order.add_item(LineItem(item.menu_item_id, "", item.quantity, 0, item.special_request))
        order_id = OrderService(tx).place_order(order, body.delivery_address, body.delivery_phone)
        tx.conn.execute("INSERT INTO submissions VALUES (?,?,?,?)", (user["user_id"], request_key, fingerprint, order_id))
        tx.record(user, "place_order", order_id, "orders")
        tx.record(user, "consume_order_stock", order_id, "inventory")
        if body.order_type == "Delivery":
            tx.record(user, "create_delivery", order_id, "deliveries")
        return order_detail(tx.conn, order_id)

    @app.patch("/orders/{order_id}/status")
    def kitchen_status(order_id: int, body: KitchenStatus, user=Depends(require("Kitchen")), tx=Depends(transaction)):
        must_exist(tx.conn, "orders", "order_id", order_id)
        OrderService(tx).update_order_status(order_id, body.status)
        tx.record(user, "update_kitchen_status", order_id, "orders")
        return order_detail(tx.conn, order_id)

    @app.get("/deliveries")
    def deliveries(user=Depends(require("Delivery Person", "Cashier", "Owner", "Supervisor")), tx=Depends(transaction)):
        return delivery_list(tx.conn)

    @app.patch("/deliveries/{order_id}/status")
    def delivery_status(order_id: int, body: DeliveryStatus, user=Depends(require("Delivery Person")), tx=Depends(transaction)):
        item = must_exist(tx.conn, "deliveries.deliveries", "order_id", order_id)
        if item["assigned_to"] is not None and item["assigned_to"] != user["user_id"]:
            raise HTTPException(409, "Another delivery person has this order.")
        if {"Awaiting Pickup": "Out for Delivery", "Out for Delivery": "Delivered"}.get(item["status"]) != body.status:
            raise HTTPException(409, "Delivery steps cannot be skipped or reversed.")
        if body.status == "Delivered" and body.cash_collected is None:
            raise HTTPException(400, "Cash collected is required when marking Delivered.")
        if body.status != "Delivered" and body.cash_collected is not None:
            raise HTTPException(400, "Record cash when marking Delivered.")
        stamp = now()
        tx.conn.execute("UPDATE deliveries.deliveries SET status=?,assigned_to=?,cash_cents=?,changed_at=? WHERE order_id=?",
                        (body.status, user["user_id"], cents(body.cash_collected) if body.cash_collected is not None else None, stamp, order_id))
        tx.conn.execute("INSERT INTO delivery_history(order_id,user_id,status,recorded_at) VALUES (?,?,?,?)", (order_id, user["user_id"], body.status, stamp))
        tx.record(user, "update_delivery_status", order_id, "deliveries")
        return next(item for item in delivery_list(tx.conn) if item["order_id"] == order_id)

    @app.patch("/deliveries/{order_id}/cash")
    def correct_cash(order_id: int, body: CashCorrection, user=Depends(require("Delivery Person")), tx=Depends(transaction)):
        item = must_exist(tx.conn, "deliveries.deliveries", "order_id", order_id)
        if item["assigned_to"] != user["user_id"] or item["status"] != "Delivered":
            raise HTTPException(403, "Only the assigned delivery person can correct cash on a Delivered order.")
        tx.conn.execute("UPDATE deliveries.deliveries SET cash_cents=? WHERE order_id=?", (cents(body.cash_collected), order_id))
        tx.record(user, "correct_delivery_cash", order_id, "deliveries")
        return next(item for item in delivery_list(tx.conn) if item["order_id"] == order_id)

    @app.post("/orders/{order_id}/payment", status_code=201)
    def payment(order_id: int, body: PaymentInput, user=Depends(require("Cashier")), tx=Depends(transaction)):
        order = must_exist(tx.conn, "orders", "order_id", order_id)
        if cents(body.amount) != cents(order["total"]):
            raise HTTPException(400, "Payment must equal the order total.")
        # Jamaica is UTC-5 throughout the year. Payment date controls sales reporting.
        trading_date = datetime.now(timezone(timedelta(hours=-5))).date().isoformat()
        tx.conn.execute("INSERT INTO payments(order_id,amount_cents,method,paid_at,trading_date) VALUES (?,?,?,?,?)",
                        (order_id, cents(body.amount), body.method, now(), trading_date))
        tx.record(user, "record_payment", order_id, "payments")
        return {"order_id": order_id, "amount": body.amount, "trading_date": trading_date}

    @app.get("/reports/daily-sales")
    def report(day: date, user=Depends(require("Owner")), tx=Depends(transaction)):
        totals = {"in_store_cents": 0, "delivery_cents": 0}
        for item in rows(tx.conn, "SELECT p.amount_cents,o.order_type FROM payments p JOIN orders o ON o.order_id=p.order_id WHERE p.trading_date=?", (day.isoformat(),)):
            totals["delivery_cents" if item["order_type"] == "Delivery" else "in_store_cents"] += item["amount_cents"]
        return {"date": day.isoformat(), "in_store": totals["in_store_cents"] / 100,
                "delivery": totals["delivery_cents"] / 100, "total": sum(totals.values()) / 100}

    @app.get("/dashboard")
    def dashboard(order_type: OrderType | None = None, user=Depends(require("Owner", "Supervisor")), tx=Depends(transaction)):
        return {"orders": orders(order_type, "newest", user, tx), "deliveries": delivery_list(tx.conn)}

    @app.get("/audit-log")
    def audit(limit: int = Query(100, ge=1, le=500), user=Depends(require("Owner", "Supervisor")), tx=Depends(transaction)):
        return rows(tx.conn, "SELECT a.*,u.username FROM audit_log a LEFT JOIN users u ON u.user_id=a.user_id ORDER BY audit_id DESC LIMIT ?", (limit,))

    @app.websocket("/ws/changes")
    async def changes(socket: WebSocket):
        # Authenticate in the first frame, keeping tokens out of URLs/access logs.
        origin = socket.headers.get("origin")
        if origin and origin not in app.state.allowed_origins:
            await socket.close(code=1008)
            return
        await socket.accept()
        try:
            message = await asyncio.wait_for(socket.receive_json(), timeout=5)
            token = message.get("token", "")
            if not isinstance(token, str):
                await socket.close(code=1008)
                return
            batch = await asyncio.to_thread(change_batch, app.state.database, token, 0)
            if batch is None:
                await socket.close(code=1008)
                return
            cursor = batch[0]
            # Always refetch permitted views, including updates missed while disconnected.
            await socket.send_json({"type": "resync", "cursor": cursor})
            ticks = 0
            while True:
                batch = await asyncio.to_thread(change_batch, app.state.database, token, cursor)
                if batch is None:
                    await socket.close(code=1008)
                    return
                _, cursor, events = batch
                for event in events:
                    await socket.send_json({"type": "changed", **event})
                ticks += 1
                if ticks % 20 == 0:
                    await socket.send_json({"type": "heartbeat", "cursor": cursor})
                await asyncio.sleep(0.5)
        except (WebSocketDisconnect, asyncio.TimeoutError, ValueError, TypeError, AttributeError):
            await socket.close(code=1008)

    return app


app = create_app()
