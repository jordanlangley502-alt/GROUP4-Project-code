class MenuItem:

    def __init__(self, menu_item_id, name, price,
                 available=True):

        self.menu_item_id = menu_item_id
        self.name = name
        self.price = price
        self.available = available

class MenuService:

    def __init__(self, database):

        self.database = database

    def add_menu_item(self, name, price):

        if price < 0:
            raise ValueError("Price cannot be negative.")

        with self.database.connect() as conn:

            conn.execute("""
                INSERT INTO menu.menu_items
                (name, price, available)
                VALUES (?, ?, 1)
            """, (name, price))

        print("Menu item added.")


    def add_recipe(self, menu_item_id,
                   inventory_item_id, quantity_required):

        if quantity_required <= 0:
            raise ValueError("Ingredient quantity must be positive.")

        with self.database.connect() as conn:

            conn.execute("""
                INSERT INTO menu.recipes
                (menu_item_id, inventory_item_id, quantity_required)
                VALUES (?, ?, ?)
            """, (
                menu_item_id,
                inventory_item_id,
                quantity_required
            ))

        print("Recipe ingredient added.")

    def view_menu(self):

        with self.database.connect() as conn:

            return conn.execute("""
                SELECT *
                FROM menu.menu_items
                ORDER BY name
            """).fetchall()

    def set_availability(self, menu_item_id, available):

        with self.database.connect() as conn:

            conn.execute("""
                UPDATE menu.menu_items
                SET available = ?
                WHERE menu_item_id = ?
            """, (int(available), menu_item_id))
