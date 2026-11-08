import pytest

from inventory.stock import Inventory, OutOfStockError, is_low_stock


def test_add_and_find():
    inv = Inventory()
    inv.add_item("apple", 3)
    assert inv.find("apple") == 3


def test_remove_too_many_raises():
    inv = Inventory()
    inv.add_item("pear", 1)
    with pytest.raises(OutOfStockError):
        inv.remove_item("pear", 2)


def test_low_stock_threshold():
    assert is_low_stock(2) is True
    assert is_low_stock(9) is False
