from __future__ import annotations
import math


def finite_values(**values):
    for name, value in values.items():
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
            raise ValueError(f"{name} must be a finite number")


def valid_currency(currency):
    if currency not in {"USD", "INR", "EUR", "GBP", "JPY", "CAD", "AUD", "SGD", "AED"}:
        raise ValueError("Unsupported currency code")
