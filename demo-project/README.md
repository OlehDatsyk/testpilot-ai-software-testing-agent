# TestPilot Demo Project — "Corner Shop Inventory"

**This is a demonstration project, not a real customer repository.** It was
written specifically for TestPilot AI and contains *deliberate* defects so the
analysis → generation → execution → failure-analysis workflow can be shown
without connecting GitHub or an AI provider.

Deliberate defects (do not "fix" them in this folder):

| Location | Defect | How TestPilot surfaces it |
|---|---|---|
| `inventory/pricing.py` `average_price` | divides by `len(prices)` — crashes on an empty list | static finding PY012 + generated edge-case test fails with `ZeroDivisionError` |
| `inventory/pricing.py` `bulk_price` | docstring says 100+ units get the bulk rate, code uses `> 100` | existing test `test_bulk_price_applies_at_100_units` fails |
| `inventory/stock.py` `restock_all` | mutable default argument | static finding PY002 / Ruff B006 |
| `inventory/stock.py` `find` | bare `except:` | static finding PY001 / Ruff E722 |
| `inventory/stock.py` `is_low_stock` | `== None` comparison | static finding PY003 / Ruff E711 |
| `web/cart.js` | `var`, loose equality, empty catch, `console.log` | JS rule findings |
