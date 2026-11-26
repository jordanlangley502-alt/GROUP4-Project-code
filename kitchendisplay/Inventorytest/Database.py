import sqlite3
import os
from pathlib import Path
from datetime import datetime, date

class DatabaseManager:

    def __init__(self, folder="jamrock_data"):

        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)

        self.paths = {
            "inventory": self.folder / "inventory.db",
            "orders": self.folder / "orders.db",
            "menu": self.folder / "menu_items.db",
            "deliveries": self.folder / "deliveries.db"
        }

        self.create_databases()


    def connect(self):

        conn = sqlite3.connect(str(self.paths["orders"]), timeout=10, check_same_thread=False)

        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")

        databases = {
            "inventory": self.paths["inventory"],
            "menu": self.paths["menu"],
            "deliveries": self.paths["deliveries"],

        }

        for name, path in databases.items():
            conn.execute(
                f"ATTACH DATABASE ? AS {name}",
                (str(path),)
            )

        return conn


    def create_databases(self):

        conn = self.connect()

        try:

            conn.executescript("""
                CREATE TABLE IF NOT EXISTS inventory.inventory_items (
                    item_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    unit TEXT NOT NULL,
                    reorder_level REAL NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS inventory.stock_lots (
                    lot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id INTEGER NOT NULL,
                    quantity REAL NOT NULL CHECK(quantity >= 0),
                    expiry_date TEXT NOT NULL,
                    received_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS inventory.stock_movements (
                    movement_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id INTEGER NOT NULL,
                    movement_type TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    reason TEXT,
                    recorded_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS inventory.waste_records (
                    waste_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id INTEGER NOT NULL,
                    quantity REAL NOT NULL,
                    reason TEXT NOT NULL,
                    recorded_at TEXT NOT NULL
                );
            """)

            print("Attached databases:")

            for db in conn.execute("PRAGMA database_list"):
                print(dict(db))
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS main.orders (
                    order_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'Confirmed',
                    placed_at TEXT NOT NULL,
                    total REAL NOT NULL,
                    created_by TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS main.line_items (
                    line_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER NOT NULL,
                    menu_item_id INTEGER NOT NULL,
                    item_name TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    unit_price REAL NOT NULL,
                    special_request TEXT,
                    FOREIGN KEY(order_id)
                        REFERENCES orders(order_id)
                        ON DELETE CASCADE
                );
            """)

            conn.executescript("""
                CREATE TABLE IF NOT EXISTS menu.menu_items (
                    menu_item_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    price REAL NOT NULL CHECK(price >= 0),
                    available INTEGER NOT NULL DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS menu.recipes (
                    recipe_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    menu_item_id INTEGER NOT NULL,
                    inventory_item_id INTEGER NOT NULL,
                    quantity_required REAL NOT NULL
                        CHECK(quantity_required > 0)
                );
            """)


            conn.executescript("""
                CREATE TABLE IF NOT EXISTS deliveries.deliveries (
                    order_id INTEGER PRIMARY KEY,
                    address TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'Awaiting Pickup',
                    assigned_to INTEGER,
                    cash_cents INTEGER CHECK(cash_cents >= 0),
                    changed_at TEXT
                );
            """)
            conn.commit()

        finally:
            conn.close()

        print("Shared restaurant databases are ready.")
