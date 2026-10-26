"""The only place that converts PayPal's string amounts to integers and back.

PayPal sends ``{"currency_code": "USD", "value": "12.34"}``. We store minor units
(cents) as integers. Floats never touch money.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

# Currencies PayPal supports with zero minor units.
_ZERO_DECIMAL = {"HUF", "JPY", "TWD"}


def minor_units(currency: str) -> int:
    return 0 if currency.upper() in _ZERO_DECIMAL else 2


def to_minor(value: str | Decimal | float, currency: str) -> int:
    """'12.34', 'USD' -> 1234. Raises ValueError on garbage."""
    try:
        dec = Decimal(str(value))
    except InvalidOperation as exc:  # pragma: no cover - defensive
        raise ValueError(f"bad amount {value!r}") from exc
    scale = Decimal(10) ** minor_units(currency)
    return int((dec * scale).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def to_decimal_str(minor: int, currency: str) -> str:
    """1234, 'USD' -> '12.34' (PayPal's wire format)."""
    places = minor_units(currency)
    if places == 0:
        return str(minor)
    sign = "-" if minor < 0 else ""
    minor = abs(minor)
    return f"{sign}{minor // 10**places}.{minor % 10**places:0{places}d}"


@dataclass(frozen=True, slots=True)
class Money:
    minor: int
    currency: str

    @classmethod
    def from_paypal(cls, obj: dict | None) -> Money | None:
        if not obj:
            return None
        cur = obj.get("currency_code") or obj.get("currency")
        val = obj.get("value") or obj.get("amount")
        if cur is None or val is None:
            return None
        return cls(to_minor(val, cur), cur.upper())

    def to_paypal(self) -> dict:
        return {"currency_code": self.currency, "value": to_decimal_str(self.minor, self.currency)}

    def __add__(self, other: Money) -> Money:
        self._same(other)
        return Money(self.minor + other.minor, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._same(other)
        return Money(self.minor - other.minor, self.currency)

    def _same(self, other: Money) -> None:
        if other.currency != self.currency:
            raise ValueError(f"currency mismatch {self.currency} vs {other.currency}")

    def __str__(self) -> str:
        return f"{to_decimal_str(self.minor, self.currency)} {self.currency}"
