
from datetime import datetime, date
if __package__:
    from .InventoryItem import InventoryItem
else:
    from InventoryItem import InventoryItem

class InventoryService:

    def __init__(self, database):

        self.database = database


    def add_item(self, name, unit, reorder_level):

        with self.database.connect() as conn:

            conn.execute("""
                INSERT INTO inventory.inventory_items
                (name, unit, reorder_level)
                VALUES (?, ?, ?)
            """, (name, unit, reorder_level))

        print(f"{name} added to inventory.")


    def receive_stock(self, item_id, quantity, expiry_date):

        if quantity <= 0:
            raise ValueError("Quantity must be positive.")

        expiry = date.fromisoformat(expiry_date)

        if expiry < date.today():
            raise ValueError("Cannot receive already-expired stock.")

        with self.database.connect() as conn:

            item = conn.execute("""
                SELECT item_id
                FROM inventory.inventory_items
                WHERE item_id = ?
            """, (item_id,)).fetchone()

            if not item:
                raise ValueError("Inventory item not found.")

            now = datetime.now().isoformat(timespec="seconds")

            conn.execute("""
                INSERT INTO inventory.stock_lots
                (item_id, quantity, expiry_date, received_at)
                VALUES (?, ?, ?, ?)
            """, (item_id, quantity, expiry_date, now))

            conn.execute("""
                INSERT INTO inventory.stock_movements
                (item_id, movement_type, quantity, reason, recorded_at)
                VALUES (?, 'INCREASE', ?, 'New stock received', ?)
            """, (item_id, quantity, now))

        print("Stock successfully received.")



    def get_quantity(self, conn, item_id):

        result = conn.execute("""
            SELECT COALESCE(SUM(quantity), 0) AS total
            FROM inventory.stock_lots
            WHERE item_id = ?
        """, (item_id,)).fetchone()

        return result["total"]

 

    def adjust_quantity(self, item_id, quantity,
                        adjustment_type, reason):

        if quantity <= 0:
            raise ValueError("Quantity must be positive.")

        if adjustment_type not in ["increase", "decrease"]:
            raise ValueError("Use increase or decrease.")

        with self.database.connect() as conn:

            now = datetime.now().isoformat(timespec="seconds")

            if adjustment_type == "increase":

                # Manual increases require an expiry date.
                raise ValueError(
                    "Use receive_stock() for increases "
                    "so that an expiry date is recorded."
                )

            else:

                current = self.get_quantity(conn, item_id)

                if quantity > current:
                    raise ValueError("Insufficient stock.")

                self._consume_stock(
                    conn, item_id, quantity
                )

            conn.execute("""
                INSERT INTO inventory.stock_movements
                (item_id, movement_type, quantity, reason, recorded_at)
                VALUES (?, ?, ?, ?, ?)
            """, (
                item_id,
                adjustment_type.upper(),
                quantity,
                reason,
                now
            ))

        print("Inventory quantity updated.")



    def _consume_stock(self, conn, item_id, quantity):

        remaining = quantity

        lots = conn.execute("""
            SELECT lot_id, quantity, expiry_date
            FROM inventory.stock_lots
            WHERE item_id = ?
              AND quantity > 0
              AND expiry_date >= ?
            ORDER BY expiry_date ASC, lot_id ASC
        """, (item_id, date.today().isoformat())).fetchall()

        available = sum(lot["quantity"] for lot in lots)

        if available < quantity:
            raise ValueError(
                f"Insufficient unexpired stock for item {item_id}."
            )

        for lot in lots:

            if remaining <= 0:
                break

            deduction = min(lot["quantity"], remaining)

            conn.execute("""
                UPDATE inventory.stock_lots
                SET quantity = quantity - ?
                WHERE lot_id = ?
            """, (deduction, lot["lot_id"]))

            remaining -= deduction


    def view_inventory(self):

        with self.database.connect() as conn:

            items = conn.execute("""
                SELECT
                    i.item_id,
                    i.name,
                    i.unit,
                    i.reorder_level,
                    COALESCE(SUM(l.quantity), 0) AS quantity
                FROM inventory.inventory_items i
                LEFT JOIN inventory.stock_lots l
                    ON i.item_id = l.item_id
                GROUP BY i.item_id
                ORDER BY i.name
            """).fetchall()

            results = []

            for item in items:

                inventory_item = InventoryItem(
                    item["item_id"],
                    item["name"],
                    item["quantity"],
                    item["unit"],
                    item["reorder_level"]
                )

                results.append(inventory_item)

            return results



    def low_stock_items(self):

        items = self.view_inventory()

        return sorted(
            [item for item in items if item.is_low_stock()],
            key=lambda item: item.quantity
        )


    def update_expiry_date(self, lot_id, new_expiry):

        expiry = date.fromisoformat(new_expiry)

        with self.database.connect() as conn:

            result = conn.execute("""
                SELECT lot_id
                FROM inventory.stock_lots
                WHERE lot_id = ?
            """, (lot_id,)).fetchone()

            if not result:
                raise ValueError("Stock lot not found.")

            conn.execute("""
                UPDATE inventory.stock_lots
                SET expiry_date = ?
                WHERE lot_id = ?
            """, (new_expiry, lot_id))

        print("Expiry date successfully updated.")


    def expiry_information(self):

        with self.database.connect() as conn:

            lots = conn.execute("""
                SELECT
                    l.lot_id,
                    i.name,
                    l.quantity,
                    i.unit,
                    l.expiry_date
                FROM inventory.stock_lots l
                JOIN inventory.inventory_items i
                    ON l.item_id = i.item_id
                WHERE l.quantity > 0
                ORDER BY l.expiry_date ASC
            """).fetchall()

            results = []

            for lot in lots:

                expiry = date.fromisoformat(
                    lot["expiry_date"]
                )

                days_left = (expiry - date.today()).days

                if days_left < 0:
                    status = "EXPIRED"

                elif days_left == 0:
                    status = "EXPIRES TODAY"

                elif days_left <= 3:
                    status = "EXPIRING SOON"

                else:
                    status = "FRESH"

                results.append({
                    "lot_id": lot["lot_id"],
                    "name": lot["name"],
                    "quantity": lot["quantity"],
                    "unit": lot["unit"],
                    "expiry_date": lot["expiry_date"],
                    "days_left": days_left,
                    "status": status
                })

            return results

   
    def soonest_expiring_items(self):

        items = self.expiry_information()

        return sorted(
            items,
            key=lambda item: item["days_left"]
        )

  
    def record_waste(self, item_id, quantity, reason):

        if quantity <= 0:
            raise ValueError("Waste quantity must be positive.")

        if not reason.strip():
            raise ValueError("A waste reason is required.")

        with self.database.connect() as conn:

            now = datetime.now().isoformat(timespec="seconds")

            self._consume_stock(
                conn, item_id, quantity
            )

            conn.execute("""
                INSERT INTO inventory.waste_records
                (item_id, quantity, reason, recorded_at)
                VALUES (?, ?, ?, ?)
            """, (item_id, quantity, reason, now))

            conn.execute("""
                INSERT INTO inventory.stock_movements
                (item_id, movement_type, quantity, reason, recorded_at)
                VALUES (?, 'WASTE', ?, ?, ?)
            """, (item_id, quantity, reason, now))

        print("Waste successfully recorded.")

  
    def view_waste_records(self):

        with self.database.connect() as conn:

            return conn.execute("""
                SELECT
                    w.waste_id,
                    i.name,
                    w.quantity,
                    i.unit,
                    w.reason,
                    w.recorded_at
                FROM inventory.waste_records w
                JOIN inventory.inventory_items i
                    ON w.item_id = i.item_id
                ORDER BY w.recorded_at DESC
            """).fetchall()
