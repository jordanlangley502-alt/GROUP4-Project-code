
from datetime import datetime, date
from decimal import Decimal
if __package__:
    from .InventoryManager import InventoryService
else:
    from InventoryManager import InventoryService

class LineItem:

    def __init__(self, menu_item_id, item_name,
                 quantity, unit_price, special_request=""):

        if quantity <= 0:
            raise ValueError("Quantity must be greater than zero.")

        self.menu_item_id = menu_item_id
        self.item_name = item_name
        self.quantity = quantity
        self.unit_price = unit_price
        self.special_request = special_request

    def get_subtotal(self):

        return self.quantity * self.unit_price


class Order:

    VALID_TYPES = ["Dine-in", "Takeout", "Delivery"]

    def __init__(self, order_type, created_by):

        if order_type not in self.VALID_TYPES:
            raise ValueError("Invalid order type.")

        self.order_type = order_type
        self.created_by = created_by
        self.line_items = []
        self.status = "Confirmed"

    def add_item(self, line_item):

        self.line_items.append(line_item)

    def calculate_total(self):

        total = sum(
            (Decimal(str(item.unit_price)) * item.quantity for item in self.line_items),
            Decimal("0.00"),
        )
        return float(total.quantize(Decimal("0.01")))

    def validate_order(self):

        if not self.line_items:
            raise ValueError("Order must contain at least one item.")

        for item in self.line_items:

            if item.quantity <= 0 or item.unit_price < 0:
                raise ValueError("Invalid order line.")

        return True

    def update_status(self, new_status):

        allowed = {
            "Confirmed": "Making",
            "Making": "Ready",
            "Ready": "Completed"
        }

        if allowed.get(self.status) != new_status:
            raise ValueError("Invalid order status transition.")

        self.status = new_status

class OrderService:

    def __init__(self, database):

        self.database = database
        self.inventory = InventoryService(database)

    def place_order(self, order, delivery_address=None,
                    delivery_phone=None):

        order.validate_order()

        if order.order_type == "Delivery":

            if not delivery_address or not delivery_phone:
                raise ValueError(
                    "Delivery address and phone are required."
                )

        total = order.calculate_total()

        with self.database.connect() as conn:

            for item in order.line_items:

                menu_item = conn.execute("""
                    SELECT menu_item_id, name, price, available
                    FROM menu.menu_items
                    WHERE menu_item_id = ?
                """, (item.menu_item_id,)).fetchone()

                if not menu_item or not menu_item["available"]:
                    raise ValueError(
                        f"{item.item_name} is unavailable."
                    )

                item.unit_price = menu_item["price"]
                item.item_name = menu_item["name"]

            total = order.calculate_total()

            requirements = {}

            for item in order.line_items:

                recipes = conn.execute("""
                    SELECT inventory_item_id, quantity_required
                    FROM menu.recipes
                    WHERE menu_item_id = ?
                """, (item.menu_item_id,)).fetchall()

                if not recipes:
                    raise ValueError(
                        f"No recipe configured for {item.item_name}."
                    )

                for recipe in recipes:

                    ingredient_id = recipe["inventory_item_id"]

                    required = (
                        recipe["quantity_required"] * item.quantity
                    )

                    requirements[ingredient_id] = (
                        requirements.get(ingredient_id, 0) + required
                    )

            for ingredient_id, quantity in requirements.items():

                available = self.inventory.get_quantity(
                    conn, ingredient_id
                )

                usable = conn.execute("""
                    SELECT COALESCE(SUM(quantity), 0) AS total
                    FROM inventory.stock_lots
                    WHERE item_id = ?
                    AND expiry_date >= ?
                """, (
                    ingredient_id,
                    date.today().isoformat()
                )).fetchone()["total"]

                if usable < quantity:

                    raise ValueError(
                        f"Insufficient stock for ingredient "
                        f"{ingredient_id}. Available: {usable}, "
                        f"required: {quantity}"
                    )

            now = datetime.now().isoformat(timespec="seconds")

            cursor = conn.execute("""
                INSERT INTO main.orders
                (order_type, status, placed_at, total, created_by)
                VALUES (?, ?, ?, ?, ?)
            """, (
                order.order_type,
                order.status,
                now,
                total,
                order.created_by
            ))

            order_id = cursor.lastrowid

            for item in order.line_items:

                conn.execute("""
                    INSERT INTO main.line_items
                    (order_id, menu_item_id, item_name,
                     quantity, unit_price, special_request)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    order_id,
                    item.menu_item_id,
                    item.item_name,
                    item.quantity,
                    item.unit_price,
                    item.special_request
                ))

            for ingredient_id, quantity in requirements.items():

                self.inventory._consume_stock(
                    conn, ingredient_id, quantity
                )

                conn.execute("""
                    INSERT INTO inventory.stock_movements
                    (item_id, movement_type, quantity,
                     reason, recorded_at)
                    VALUES (?, 'ORDER', ?, ?, ?)
                """, (
                    ingredient_id,
                    quantity,
                    f"Used for order {order_id}",
                    now
                ))

            if order.order_type == "Delivery":

                conn.execute("""
                    INSERT INTO deliveries.deliveries
                    (order_id, address, phone)
                    VALUES (?, ?, ?)
                """, (
                    order_id,
                    delivery_address,
                    delivery_phone
                ))

        print(f"Order #{order_id} successfully placed.")
        print(f"Order total: ${total:,.2f}")

        return order_id


    def view_orders(self):

        with self.database.connect() as conn:

            orders = conn.execute("""
                SELECT * FROM main.orders
                ORDER BY placed_at DESC
            """).fetchall()

            return orders


    def update_order_status(self, order_id, new_status):

        with self.database.connect() as conn:

            result = conn.execute("""
                SELECT status
                FROM main.orders
                WHERE order_id = ?
            """, (order_id,)).fetchone()

            if not result:
                raise ValueError("Order not found.")

            current = result["status"]

            order = Order("Takeout", "Kitchen")
            order.status = current
            order.update_status(new_status)

            conn.execute("""
                UPDATE main.orders
                SET status = ?
                WHERE order_id = ?
            """, (new_status, order_id))

        print("Order status updated.")
