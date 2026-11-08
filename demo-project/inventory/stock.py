"""In-memory stock keeping for the demo shop."""


class OutOfStockError(Exception):
    """Raised when removing more units than are available."""


class Inventory:
    def __init__(self) -> None:
        self.items: dict[str, int] = {}

    def add_item(self, sku: str, quantity: int) -> None:
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        self.items[sku] = self.items.get(sku, 0) + quantity

    def remove_item(self, sku: str, quantity: int) -> None:
        available = self.items.get(sku, 0)
        if quantity > available:
            raise OutOfStockError(f"only {available} units of {sku} left")
        self.items[sku] = available - quantity

    def find(self, sku: str):
        try:
            return self.items[sku]
        except:  # DELIBERATE DEFECT: bare except
            return None


def restock_all(inventory: Inventory, skus=[]):  # DELIBERATE DEFECT: mutable default
    skus.append("__audit__")
    for sku in skus:
        if sku != "__audit__":
            inventory.add_item(sku, 10)
    return skus


def is_low_stock(level, threshold: int = 5) -> bool:
    if level == None:  # DELIBERATE DEFECT: should be "is None"
        return True
    return level < threshold
