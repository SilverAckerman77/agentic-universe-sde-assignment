import pytest

from solution.ingestion.normalizers import (
    normalize_header,
    normalize_phone,
    normalize_date,
    normalize_decimal,
    normalize_enum,
)


def test_header_normalization():
    assert normalize_header(" Mobile_No ") == "mobile no"
    assert normalize_header("Customer Name") == "customer name"


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("9876543210", "+919876543210"),
        ("+91 98765 43210", "+919876543210"),
        ("91-98765-43210", "+919876543210"),
        ("09876543210", "+919876543210"),
    ],
)
def test_valid_phones(raw, expected):
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["5123456789", "123456789", "N/A", "+1 415 555 0134"],
)
def test_invalid_phones(raw):
    with pytest.raises(ValueError, match="invalid_phone"):
        normalize_phone(raw)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("2026-12-01", "2026-12-01"),
        ("01/12/2026", "2026-12-01"),
        ("01-12-2026", "2026-12-01"),
        ("01-Dec-2026", "2026-12-01"),
    ],
)
def test_valid_dates(raw, expected):
    assert normalize_date(raw) == expected


def test_impossible_date():
    with pytest.raises(ValueError):
        normalize_date("31/02/2026")


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("12000", "12000.00"),
        ("₹12,000", "12000.00"),
        ("Rs. 12,500", "12500.00"),
        ("INR 1500.5", "1500.50"),
    ],
)
def test_valid_decimals(raw, expected):
    assert normalize_decimal(raw) == expected


def test_negative_decimal():
    with pytest.raises(ValueError):
        normalize_decimal("-100")


def test_enum():
    assert normalize_enum("EN", ["en", "hi", "ta"]) == "en"
    with pytest.raises(ValueError):
        normalize_enum("French", ["en", "hi", "ta"])