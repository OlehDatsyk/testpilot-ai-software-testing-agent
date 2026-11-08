"""Pricing helpers for the demo shop."""


class PricingError(ValueError):
    """Raised for invalid pricing input."""


def apply_discount(price: float, percent: float) -> float:
    """Return ``price`` reduced by ``percent`` per cent, rounded to cents.

    >>> apply_discount(100.0, 25)
    75.0
    >>> apply_discount(19.99, 0)
    19.99
    """
    if percent < 0 or percent > 100:
        raise PricingError("percent must be between 0 and 100")
    if price < 0:
        raise ValueError("price cannot be negative")
    return round(price * (1 - percent / 100), 2)


def average_price(prices: list) -> float:
    """Return the mean of ``prices``."""
    # DELIBERATE DEFECT: no guard for an empty list (ZeroDivisionError).
    return sum(prices) / len(prices)


def bulk_price(unit_price: float, quantity: int) -> float:
    """Total price for ``quantity`` units. Orders of 100 units or more get 20% off.

    >>> bulk_price(2.0, 10)
    20.0
    """
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    total = unit_price * quantity
    # DELIBERATE DEFECT: should be ``quantity >= 100`` according to the docstring.
    if quantity > 100:
        total *= 0.8
    return round(total, 2)
