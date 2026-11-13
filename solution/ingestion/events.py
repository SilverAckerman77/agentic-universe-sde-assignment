
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from solution.ingestion.normalizers import normalize_phone
from solution.security.encryption import phone_digest


IST = timezone(timedelta(hours=5, minutes=30))


def normalize_timestamp(value: str) -> str:
    """Convert UTC, offset-aware or naive timestamps into IST ISO format."""

    value = str(value).strip()

    if value.endswith("Z"):
        value = value[:-1] + "+00:00"

    timestamp = datetime.fromisoformat(value)

    # The assignment defines naive timestamps as IST.
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=IST)

    timestamp = timestamp.astimezone(IST)

    timespec = "microseconds" if timestamp.microsecond else "seconds"

    return timestamp.isoformat(timespec=timespec)


def ingest_event_files(
    connection,
    drop_dir: Path,
    dispositions: dict,
) -> dict:
    """
    Ingest JSONL events into the append-only ledger.

    Orphans are retained with their phone hash so that they
    can become linkable when a later drop supplies the lead.
    """

    event_dir = Path(drop_dir) / "events"

    stats = {
        "events_total": 0,
        "malformed_events": 0,
        "duplicate_events_dropped": 0,
    }

    if not event_dir.exists():
        return stats

    for event_file in sorted(event_dir.glob("*.jsonl")):

        with event_file.open(
            "r",
            encoding="utf-8",
        ) as file:

            for line in file:

                line = line.strip()

                if not line:
                    continue

                stats["events_total"] += 1

                # 1. Parse JSON.
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    stats["malformed_events"] += 1
                    continue

                if not isinstance(event, dict):
                    stats["malformed_events"] += 1
                    continue

                # 2. Validate event identity.
                event_id = event.get("event_id")

                if not isinstance(event_id, str) or not event_id.strip():
                    stats["malformed_events"] += 1
                    continue

                event_id = event_id.strip()

                # 3. Dedupe globally across all ingested drops.
                exists = connection.execute(
                    """
                    SELECT 1
                    FROM events
                    WHERE event_id = ?
                    """,
                    (event_id,),
                ).fetchone()

                if exists:
                    stats["duplicate_events_dropped"] += 1
                    continue

                # 4. Validate event metadata.
                workflow_id = event.get("workflow_id")
                event_type = event.get("event_type")
                occurred_at = event.get("occurred_at")

                if not workflow_id or not event_type or not occurred_at:
                    stats["malformed_events"] += 1
                    continue

                try:
                    occurred_at_ist = normalize_timestamp(occurred_at)
                except (ValueError, TypeError, OverflowError):
                    stats["malformed_events"] += 1
                    continue

                workflow_id = str(workflow_id).strip()
                event_type = str(event_type).strip()

                call_id = event.get("call_id")

                if call_id is not None:
                    call_id = str(call_id).strip() or None

                # 5. Hash phone; never store it in plaintext.
                phone_hash = None
                raw_phone = event.get("phone")

                if raw_phone is not None:
                    try:
                        canonical_phone = normalize_phone(raw_phone)
                        phone_hash = phone_digest(canonical_phone)
                    except ValueError:
                        # It will remain an orphan unless it is
                        # a valid override linked by call_id.
                        phone_hash = None

                # 6. Check disposition catalogue.
                payload = event.get("payload") or {}

                if not isinstance(payload, dict):
                    payload = {}

                is_unknown = False

                if event_type.startswith("disposition."):
                    code = str(
                        payload.get("disposition_code", "")
                    ).strip().lower()

                    is_unknown = (
                        workflow_id,
                        code,
                    ) not in dispositions

                # 7. Store the original event without the raw phone.
                connection.execute(
                    """
                    INSERT INTO events (
                        event_id,
                        event_type,
                        workflow_id,
                        call_id,
                        occurred_at,
                        phone_hash,
                        payload_json,
                        source_drop,
                        is_unknown_disposition
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id,
                        event_type,
                        workflow_id,
                        call_id,
                        occurred_at_ist,
                        phone_hash,
                        json.dumps(payload, ensure_ascii=False),
                        Path(drop_dir).name,
                        int(is_unknown),
                    ),
                )

    return stats

