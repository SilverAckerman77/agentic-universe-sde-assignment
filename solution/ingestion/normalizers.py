import re
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def normalize_header(header: str) -> str:
    """Normalize CSV headers for schema alias matching."""
    return re.sub(r"[_\s]+", " ", header.strip().lower())


def normalize_phone(value: str) -> str:
    """Normalize an Indian mobile number to +91XXXXXXXXXX."""
    digits = re.sub(r"\D", "", str(value))

    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]

    if len(digits) != 10 or digits[0] not in "6789":
        raise ValueError("invalid_phone")

    return f"+91{digits}"


def normalize_date(value: str) -> str:
    """Parse supported day-first date formats and return ISO date."""
    value = value.strip()

    formats = [
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d-%b-%Y",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue

    raise ValueError("invalid_date")


def normalize_decimal(value: str) -> str:
    """Parse INR amounts and return a two-decimal string."""
    value = value.strip()

    value = re.sub(
        r"^(?:₹|Rs.?|INR)\s*",
        "",
        value,
        flags=re.IGNORECASE,
    )

    value = value.replace(",", "").strip()

    try:
        amount = Decimal(value)
    except InvalidOperation:
        raise ValueError("invalid_decimal")

    if not amount.is_finite() or amount < 0:
        raise ValueError("invalid_decimal")

    amount = amount.quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )

    return format(amount, ".2f")


def normalize_enum(value: str, allowed_values: list[str]) -> str:
    """Validate enum values case-insensitively."""
    normalized = value.strip().lower()
    allowed = {item.lower() for item in allowed_values}

    if normalized not in allowed:
        raise ValueError("invalid_enum")

    return normalized


def normalize_value(value: str, field: dict):
    """Normalize a value based on its workflow schema field."""
    if value is None or not str(value).strip():
        return None

    value = str(value).strip()
    field_type = field["type"]

    if field_type == "string":
        return value

    if field_type == "phone":
        return normalize_phone(value)

    if field_type == "date":
        return normalize_date(value)

    if field_type == "decimal":
        return normalize_decimal(value)

    if field_type == "enum":
        return normalize_enum(value, field["values"])

    raise ValueError(f"unsupported_field_type:{field_type}")