import pytest

from app.domain.money import Money, to_decimal_str, to_minor


@pytest.mark.parametrize("value,cur,minor", [("12.34", "USD", 1234), ("0.10", "EUR", 10), ("1000", "JPY", 1000), ("19.995", "USD", 2000), ("-5.00", "USD", -500)])
def test_to_minor(value, cur, minor):
    assert to_minor(value, cur) == minor


@pytest.mark.parametrize("minor,cur,s", [(1234, "USD", "12.34"), (5, "USD", "0.05"), (1000, "JPY", "1000"), (-500, "USD", "-5.00")])
def test_to_decimal_str(minor, cur, s):
    assert to_decimal_str(minor, cur) == s


def test_roundtrip_paypal_shape():
    m = Money.from_paypal({"currency_code": "USD", "value": "129.00"})
    assert m == Money(12900, "USD")
    assert m.to_paypal() == {"currency_code": "USD", "value": "129.00"}


def test_currency_mismatch_refused():
    with pytest.raises(ValueError):
        Money(1, "USD") + Money(1, "EUR")
