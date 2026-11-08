import pytest

from inventory.pricing import PricingError, apply_discount, bulk_price


def test_apply_discount_basic():
    assert apply_discount(80.0, 50) == 40.0


def test_apply_discount_rejects_over_100():
    with pytest.raises(PricingError):
        apply_discount(10.0, 150)


def test_bulk_price_small_order():
    assert bulk_price(1.5, 4) == 6.0


def test_bulk_price_applies_at_100_units():
    # The docstring promises the bulk rate from 100 units. This test exposes the defect.
    assert bulk_price(1.0, 100) == 80.0
