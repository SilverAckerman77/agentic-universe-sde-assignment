
import json
import pytest

from solution.ingestion.events import (
    normalize_timestamp,
    ingest_event_files,
)
from solution.database.initialize import initialize_database
from solution.database.connection import get_connection
from solution.security.encryption import phone_digest


@pytest.mark.parametrize(
    "raw, expected",
    [
        (
            "2026-10-03T04:31:00Z",
            "2026-10-03T10:01:00+05:30",
        ),
        (
            "2026-10-03T10:01:00+05:30",
            "2026-10-03T10:01:00+05:30",
        ),
        (
            "2026-10-03 10:01:00",
            "2026-10-03T10:01:00+05:30",
        ),
    ],
)
def test_timestamp_normalization(raw, expected):
    assert normalize_timestamp(raw) == expected


def test_event_ingestion_deduplication(tmp_path):
    drop_dir = tmp_path / "drop_1"
    event_dir = drop_dir / "events"
    event_dir.mkdir(parents=True)

    db_path = tmp_path / "test.db"
    initialize_database(db_path)

    event = {
        "event_id": "evt_001",
        "event_type": "call.initiated",
        "workflow_id": "motor_renewal",
        "call_id": "call_001",
        "occurred_at": "2026-10-03T04:31:00Z",
        "phone": "9876543210",
        "payload": {},
    }

    with (event_dir / "events_0001.jsonl").open(
        "w", encoding="utf-8"
    ) as file:
        file.write(json.dumps(event) + "\n")
        file.write(json.dumps(event) + "\n")
        file.write("{invalid json\n")
        file.write("\n")

    connection = get_connection(db_path)

    try:
        stats = ingest_event_files(
            connection,
            drop_dir,
            {},
        )
        connection.commit()

        assert stats["events_total"] == 3
        assert stats["malformed_events"] == 1
        assert stats["duplicate_events_dropped"] == 1

        stored = connection.execute(
            "SELECT * FROM events"
        ).fetchall()

        assert len(stored) == 1

        assert stored[0]["phone_hash"] == phone_digest(
            "+919876543210"
        )

        assert "+919876543210" not in str(
            dict(stored[0])
        )

    finally:
        connection.close()
