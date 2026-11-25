"""POS validation and order-saving rules."""

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
import sqlite3


MONEY = Decimal("0.01")
TYPE_TO_DB = {"dine_in": "Dine-in", "takeout": "Takeout", "delivery": "Delivery"}
DB_TO_TYPE = {"Dine-in": "dine_in", "Takeout": "takeout", "Delivery": "delivery"}

SEED_ITEMS = [
    ("Jerk Chicken", "850.00"),
    ("Curry Goat", "950.00"),
    ("Oxtail", "1200.00"),
    ("Rice and Peas", "300.00"),
    ("Patty", "250.00"),
    ("Festival", "180.00"),
    ("Sorrel", "350.00"),
    ("Ting", "220.00"),
]


def quantize_money(value: Decimal) -> Decimal:
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


def calculate_total(line_items) -> Decimal:
    total = sum(
        (item.unit_price * item.quantity for item in line_items),
        Decimal("0.00"),
    )
    return quantize_money(total)


def ensure_pos_schema(database):
    """Add POS fields to existing shared tables without replacing them."""
    with database.connect() as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(orders)")}
        additions = {
            "placed_by": "TEXT",
            "delivery_address": "TEXT",
            "customer_phone": "TEXT",
            "idempotency_key": "TEXT",
        }
        for name, sql_type in additions.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE main.orders ADD COLUMN {name} {sql_type}")

        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_idempotency "
            "ON orders(idempotency_key) WHERE idempotency_key IS NOT NULL"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS pos_submissions "
            "(idempotency_key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, order_id INTEGER NOT NULL)"
        )
        count = conn.execute("SELECT COUNT(*) AS count FROM menu.menu_items").fetchone()["count"]
        if count == 0:
            conn.executemany(
                "INSERT INTO menu.menu_items (name, price, available) VALUES (?, ?, 1)",
                SEED_ITEMS,
            )


def notify_kitchen(order):
    """Kitchen Display (Anneka) can replace this placeholder later."""
    print(f"[Hook] notify_kitchen: order {order['order_id']} Confirmed")


def deduct_inventory(order):
    """Inventory (Jordan) can replace this placeholder later."""
    print(f"[Hook] deduct_inventory: order {order['order_id']} no stock change")


def validate_order(body):
    if not body.line_items:
        raise ValueError("Order must contain at least one line item.")
    for item in body.line_items:
        if item.quantity <= 0:
            raise ValueError("Line-item quantity must be greater than zero.")
    if body.order_type == "delivery":
        if not body.delivery_address or not body.delivery_address.strip():
            raise ValueError("A delivery address is required.")
        if not body.customer_phone or not body.customer_phone.strip():
            raise ValueError("A customer phone number is required.")


def get_menu(database):
    with database.connect() as conn:
        ensure_pos_schema(database)
        rows = conn.execute(
            "SELECT menu_item_id, name, price, available "
            "FROM menu.menu_items WHERE available=1 ORDER BY name"
        ).fetchall()
    return [
        {
            "menu_item_id": row["menu_item_id"],
            "name": row["name"],
            "unit_price": quantize_money(Decimal(str(row["price"]))),
            "is_available": bool(row["available"]),
        }
        for row in rows
    ]


def fingerprint(body):
    return hashlib.sha256(
        json.dumps(body.model_dump(mode="json"), sort_keys=True).encode()
    ).hexdigest()


def order_detail(database, order_id):
    with database.connect() as conn:
        row = conn.execute(
            "SELECT * FROM main.orders WHERE order_id=?", (order_id,)
        ).fetchone()
        if not row:
            return None
        items = conn.execute(
            "SELECT line_item_id, menu_item_id, item_name, quantity, unit_price, special_request "
            "FROM main.line_items WHERE order_id=? ORDER BY line_item_id",
            (order_id,),
        ).fetchall()

    line_items = []
    for item in items:
        unit_price = quantize_money(Decimal(str(item["unit_price"])))
        quantity = item["quantity"]
        line_items.append({
            "line_item_id": item["line_item_id"],
            "menu_item_id": item["menu_item_id"],
            "name": item["item_name"],
            "quantity": quantity,
            "unit_price": unit_price,
            "special_request": item["special_request"],
            "subtotal": quantize_money(unit_price * quantity),
        })

    return {
        "order_id": row["order_id"],
        "order_type": DB_TO_TYPE[row["order_type"]],
        "status": row["status"],
        "placed_at": row["placed_at"],
        "total": quantize_money(Decimal(str(row["total"]))),
        "placed_by": row["placed_by"] or row["created_by"],
        "delivery_address": row["delivery_address"],
        "customer_phone": row["customer_phone"],
        "idempotency_key": row["idempotency_key"],
        "line_items": line_items,
    }


def create_order(database, body, cashier):
    validate_order(body)
    ensure_pos_schema(database)

    if body.idempotency_key:
        with database.connect() as conn:
            existing = conn.execute(
                "SELECT order_id, fingerprint FROM pos_submissions WHERE idempotency_key=?",
                (body.idempotency_key,),
            ).fetchone()
        if existing:
            if existing["fingerprint"] != fingerprint(body):
                raise ValueError("Idempotency key was already used for a different order.")
            result = order_detail(database, existing["order_id"])
            return result, 200

    conn = database.connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        if body.idempotency_key:
            existing = conn.execute(
                "SELECT order_id, fingerprint FROM pos_submissions WHERE idempotency_key=?",
                (body.idempotency_key,),
            ).fetchone()
            if existing:
                if existing["fingerprint"] != fingerprint(body):
                    raise ValueError("Idempotency key was already used for a different order.")
                result = order_detail(database, existing["order_id"])
                conn.commit()
                return result, 200
        for item in body.line_items:
            menu = conn.execute(
                "SELECT menu_item_id, name, price, available "
                "FROM menu.menu_items WHERE menu_item_id=?",
                (item.menu_item_id,),
            ).fetchone()
            if not menu:
                raise ValueError("Unknown menu item.")
            if not menu["available"]:
                raise ValueError(f"{menu['name']} is unavailable.")

        priced_items = []
        for item in body.line_items:
            menu = conn.execute(
                "SELECT name, price FROM menu.menu_items WHERE menu_item_id=?",
                (item.menu_item_id,),
            ).fetchone()
            price = quantize_money(Decimal(str(menu["price"])))
            priced_items.append((item, menu["name"], price))

        total = quantize_money(sum(
            (price * item.quantity for item, _, price in priced_items),
            Decimal("0.00"),
        ))
        placed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        cursor = conn.execute(
            "INSERT INTO main.orders "
            "(order_type,status,placed_at,total,created_by,placed_by,"
            "delivery_address,customer_phone,idempotency_key) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                TYPE_TO_DB[body.order_type],
                "Confirmed",
                placed_at,
                str(total),
                cashier,
                cashier,
                body.delivery_address.strip() if body.delivery_address else None,
                body.customer_phone.strip() if body.customer_phone else None,
                body.idempotency_key,
            ),
        )
        order_id = cursor.lastrowid
        for item, name, price in priced_items:
            conn.execute(
                "INSERT INTO main.line_items "
                "(order_id,menu_item_id,item_name,quantity,unit_price,special_request) "
                "VALUES (?,?,?,?,?,?)",
                (order_id, item.menu_item_id, name, item.quantity, str(price),
                 item.special_request.strip() if item.special_request and item.special_request.strip() else None),
            )
        if body.order_type == "delivery":
            conn.execute(
                "INSERT OR REPLACE INTO deliveries.deliveries "
                "(order_id,address,phone,status) VALUES (?,?,?,?)",
                (order_id, body.delivery_address.strip(), body.customer_phone.strip(), "Awaiting Pickup"),
            )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS pos_submissions "
            "(idempotency_key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, order_id INTEGER NOT NULL)"
        )
        if body.idempotency_key:
            conn.execute(
                "INSERT OR IGNORE INTO pos_submissions "
                "(idempotency_key,fingerprint,order_id) VALUES (?,?,?)",
                (body.idempotency_key, fingerprint(body), order_id),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    result = order_detail(database, order_id)
    notify_kitchen(result)
    deduct_inventory(result)
    return result, 201


def list_orders(database, status=None, order_type=None):
    db_status = status
    db_type = TYPE_TO_DB.get(order_type) if order_type else None
    sql = "SELECT order_id FROM main.orders WHERE 1=1"
    params = []
    if db_status:
        sql += " AND status=?"
        params.append(db_status)
    if db_type:
        sql += " AND order_type=?"
        params.append(db_type)
    sql += " ORDER BY placed_at DESC, order_id DESC"
    with database.connect() as conn:
        ids = conn.execute(sql, params).fetchall()
    return [order_detail(database, row["order_id"]) for row in ids]
