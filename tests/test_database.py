
import sqlite3

from solution.security.encryption import (
    encrypt_pii,
    decrypt_pii,
    phone_digest,
)
from solution.database.initialize import initialize_database
from solution.database.connection import get_connection


def test_pii_encryption_round_trip():
    original = {
        "customer_name": "Rahul Sharma",
        "phone": "+919876543210",
    }

    encrypted = encrypt_pii(original)

    assert "Rahul Sharma" not in encrypted
    assert "+919876543210" not in encrypted
    assert decrypt_pii(encrypted) == original


def test_phone_digest_is_deterministic():
    phone = "+919876543210"

    first = phone_digest(phone)
    second = phone_digest(phone)

    assert first == second
    assert len(first) == 64
    assert phone not in first


def test_database_initialization(tmp_path):
    db_path = tmp_path / "test.db"

    initialize_database(db_path)

    connection = get_connection(db_path)

    try:
        tables = {
            row["name"]
            for row in connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                """
            )
        }

        assert {
            "leads",
            "events",
            "lead_rejections",
            "ingested_drops",
        }.issubset(tables)

    finally:
        connection.close()


def test_event_ledger_is_append_only(tmp_path):
    db_path = tmp_path / "ledger.db"

    initialize_database(db_path)
    connection = get_connection(db_path)

    try:
        connection.execute(
            """
            INSERT INTO events (
                event_id,
                event_type,
                workflow_id,
                occurred_at,
                payload_json,
                source_drop
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "evt_test_001",
                "call.initiated",
                "motor_renewal",
                "2026-10-01T10:00:00+05:30",
                "{}",
                "drop_1",
            ),
        )
        connection.commit()

        with __import__("pytest").raises(
            sqlite3.IntegrityError,
            match="append-only",
        ):
            connection.execute(
                """
                UPDATE events
                SET event_type = 'call.connected'
                WHERE event_id = 'evt_test_001'
                """
            )

        with __import__("pytest").raises(
            sqlite3.IntegrityError,
            match="append-only",
        ):
            connection.execute(
                "DELETE FROM events WHERE event_id = 'evt_test_001'"
            )

    finally:
        connection.close()
