
import os
import json
import hmac
import hashlib

from dotenv import load_dotenv
from cryptography.fernet import Fernet


load_dotenv()

FERNET_KEY = os.getenv("FERNET_KEY")
HMAC_KEY = os.getenv("PHONE_HMAC_KEY")

if not FERNET_KEY or not HMAC_KEY:
    raise RuntimeError(
        "Missing FERNET_KEY or PHONE_HMAC_KEY in .env"
    )

try:
    cipher = Fernet(FERNET_KEY.encode("utf-8"))
    hmac_key_bytes = bytes.fromhex(HMAC_KEY)
except (ValueError, TypeError) as exc:
    raise RuntimeError("Invalid encryption key configuration") from exc


def encrypt_text(value: str | None) -> str | None:
    """Encrypt a text value using Fernet."""
    if value is None:
        return None

    return cipher.encrypt(
        value.encode("utf-8")
    ).decode("utf-8")


def decrypt_text(token: str | None) -> str | None:
    """Decrypt a Fernet token."""
    if token is None:
        return None

    return cipher.decrypt(
        token.encode("utf-8")
    ).decode("utf-8")


def encrypt_pii(data: dict) -> str:
    """Encrypt a dictionary containing PII fields."""
    serialized = json.dumps(data, separators=(",", ":"))
    return encrypt_text(serialized)


def decrypt_pii(token: str) -> dict:
    """Decrypt PII dictionary."""
    serialized = decrypt_text(token)
    return json.loads(serialized)


def phone_digest(canonical_phone: str) -> str:
    """Generate deterministic HMAC-SHA256 phone key."""
    return hmac.new(
        hmac_key_bytes,
        canonical_phone.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
