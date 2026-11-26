class InventoryItem:

    def __init__(self, item_id, name, quantity,
                 unit, reorder_level):

        self.item_id = item_id
        self.name = name
        self.quantity = quantity
        self.unit = unit
        self.reorder_level = reorder_level

    def is_low_stock(self):

        return self.quantity <= self.reorder_level

    def get_status(self):

        if self.quantity <= 0:
            return "OUT OF STOCK"

        elif self.is_low_stock():
            return "LOW STOCK"

        return "IN STOCK"
