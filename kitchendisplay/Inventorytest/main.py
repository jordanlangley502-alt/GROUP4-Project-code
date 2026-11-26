
import sqlite3
from datetime import datetime, date
from Database import DatabaseManager
from lineitem import LineItem,Order,OrderService
from InventoryItem import InventoryItem
from MenuItems import MenuService
from InventoryManager import InventoryService



class JamrockBitez:

    def __init__(self):

        self.database = DatabaseManager()

        self.inventory = InventoryService(self.database)

        self.menu = MenuService(self.database)

        self.orders = OrderService(self.database)


    def inventory_menu(self):

        while True:

            print("\n===================================")
            print("       JAMROCK BITEZ")
            print("       INVENTORY MANAGEMENT")
            print("===================================")

            print("1. Add New Inventory Item")
            print("2. Receive Stock (Add Quantity)")
            print("3. Remove Stock")
            print("4. View Inventory")
            print("5. View Low Stock Items")
            print("6. Return to Main Program")

            choice = input("\nEnter your choice: ")


            if choice == "1":

                name = input("Enter item name: ")
                unit = input("Enter unit (kg, litres, pieces): ")

                try:
                    reorder_level = float(
                        input("Enter reorder level: ")
                    )

                    self.inventory.add_item(
                        name, unit, reorder_level
                    )

                    print("\nSUCCESS: Inventory item added.")
                    print("Item:", name)
                    print("Unit:", unit)
                    print("Reorder level:", reorder_level)

                except (ValueError, sqlite3.IntegrityError) as e:
                    print("\nERROR:", e)


            elif choice == "2":

                try:


                    item_id = int(input("Enter item ID: "))

                    quantity = float(
                        input("Enter quantity received: ")
                    )

                    expiry_date = input(
                        "Enter expiry date (YYYY-MM-DD): "
                    )

                    self.inventory.receive_stock(
                        item_id,
                        quantity,
                        expiry_date
                    )

                    print("\nSUCCESS: Stock received.")
                    print("Item ID:", item_id)
                    print("Quantity added:", quantity)
                    print("Expiry date:", expiry_date)

                except (ValueError, sqlite3.IntegrityError) as e:
                    print("\nERROR:", e)


            elif choice == "3":

                try:
                    item_id = int(input("Enter item ID: "))

                    quantity = float(
                        input("Enter quantity to remove: ")
                    )

                    reason = input(
                        "Enter reason for removal: "
                    )

                    self.inventory.adjust_quantity(
                        item_id,
                        quantity,
                        "decrease",
                        reason
                    )

                    print("\nSUCCESS: Stock removed.")
                    print("Item ID:", item_id)
                    print("Quantity removed:", quantity)
                    print("Reason:", reason)

                except (ValueError, sqlite3.IntegrityError) as e:
                    print("\nERROR:", e)


            elif choice == "4":

                print("\n========== CURRENT INVENTORY ==========")

                items = self.inventory.view_inventory()

                for item in items:

                    print("-----------------------------------")
                    print("Item ID:", item.item_id)
                    print("Name:", item.name)
                    print("Quantity:", item.quantity, item.unit)
                    print("Status:", item.get_status())

                if not items:
                    print("No inventory items found.")


            elif choice == "5":

                print("\n========== LOW STOCK ITEMS ==========")

                items = self.inventory.low_stock_items()

                if not items:
                    print("No low-stock items.")

                for item in items:

                    print("-----------------------------------")
                    print("Item:", item.name)
                    print("Quantity:", item.quantity, item.unit)
                    print("Status:", item.get_status())


            elif choice == "6":

                print("Returning to JamrockBitez...")
                break

            else:

                print("Invalid selection. Please try again.")


if __name__ == "__main__":

    print("\nWELCOME TO JAMROCK BITEZ")

    app = JamrockBitez()

    app.inventory_menu()
