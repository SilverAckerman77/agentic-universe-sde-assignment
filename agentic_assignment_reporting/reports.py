"""Generate the five Assignment A reports from the interaction ledger."""

from __future__ import annotations

import csv
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from solution.database.connection import get_connection
from solution.ingestion.schema_loader import (
    load_dispositions,
    load_workflow_schemas,
)
from solution.security.encryption import decrypt_pii


QUALITY_KEYS = (
    "lead_rows_total",
    "lead_rows_rejected",
    "duplicate_lead_rows_merged",
    "field_warnings",
    "events_total",
    "malformed_events",
    "duplicate_events_dropped",
)


def _timestamp(value: str) -> datetime:
    """Parse the IST-normalized timestamp stored by event ingestion."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f"Timestamp is not timezone-aware: {value}")
    return parsed


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(event.get("payload_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _apply_defaults(
    connection: sqlite3.Connection,
    schemas: dict[str, dict[str, Any]],
) -> None:
    """Apply workflow defaults after all drops have been merged."""
    rows = connection.execute(
        "SELECT lead_id, workflow_id, attributes_json FROM leads"
    ).fetchall()

    for row in rows:
        schema = schemas.get(row["workflow_id"])
        if schema is None:
            continue

        try:
            attributes = json.loads(row["attributes_json"] or "{}")
        except json.JSONDecodeError:
            attributes = {}

        changed = False
        for field in schema["fields"]:
            name = field["name"]
            if "default" in field and attributes.get(name) is None:
                attributes[name] = field["default"]
                changed = True

        if changed:
            connection.execute(
                "UPDATE leads SET attributes_json = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE lead_id = ?",
                (json.dumps(attributes, ensure_ascii=False), row["lead_id"]),
            )


def _load_leads(
    connection: sqlite3.Connection,
    schemas: dict[str, dict[str, Any]],
) -> tuple[dict[int, dict[str, Any]], dict[tuple[str, str], int]]:
    """Load lead metadata and the (workflow, HMAC phone) lookup index."""
    leads_by_id: dict[int, dict[str, Any]] = {}
    lead_index: dict[tuple[str, str], int] = {}

    rows = connection.execute("SELECT * FROM leads").fetchall()
    for row in rows:
        pii = decrypt_pii(row["pii_encrypted"])
        attributes = json.loads(row["attributes_json"] or "{}")
        phone = pii.get("phone")
        schema = schemas[row["workflow_id"]]
        reference_fields = [
            field["name"]
            for field in schema["fields"]
            if field.get("reference", False)
        ]
        if len(reference_fields) != 1:
            raise ValueError(
                f"Expected exactly one reference field for {row['workflow_id']}"
            )

        lead = {
            "lead_id": row["lead_id"],
            "workflow_id": row["workflow_id"],
            "phone": phone,
            "phone_hash": row["phone_hash"],
            "external_ref": row["external_ref"],
            "batch_id": row["batch_id"],
            "attributes": attributes,
        }
        leads_by_id[row["lead_id"]] = lead
        lead_index[(row["workflow_id"], row["phone_hash"])] = row["lead_id"]

    return leads_by_id, lead_index


def _link_events(
    events: list[dict[str, Any]],
    lead_index: dict[tuple[str, str], int],
) -> tuple[list[tuple[dict[str, Any], int]], int]:
    """Link ordinary events by phone and overrides through their call's events."""
    direct_links: dict[str, int] = {}
    call_leads: dict[tuple[str, str], set[int]] = defaultdict(set)

    # First pass: ordinary events link by (workflow_id, phone_hash).
    for event in events:
        if event["event_type"] == "disposition.override":
            continue

        phone_hash = event["phone_hash"]
        if phone_hash is None:
            continue

        lead_id = lead_index.get((event["workflow_id"], phone_hash))
        if lead_id is None:
            continue

        direct_links[event["event_id"]] = lead_id
        if event["call_id"]:
            call_leads[(event["workflow_id"], event["call_id"])].add(lead_id)

    # Second pass: overrides have no phone and inherit the unique lead
    # identified by the other phone-bearing events for the same call.
    linked: list[tuple[dict[str, Any], int]] = []
    for event in events:
        if event["event_type"] == "disposition.override":
            candidates = call_leads.get(
                (event["workflow_id"], event["call_id"]), set()
            )
            lead_id = next(iter(candidates)) if len(candidates) == 1 else None
        else:
            lead_id = direct_links.get(event["event_id"])

        if lead_id is not None:
            linked.append((event, lead_id))

    orphan_count = len(events) - len(linked)
    return linked, orphan_count


def _effective_disposition(
    events: list[dict[str, Any]],
    workflow_id: str,
    dispositions: dict[tuple[str, str], dict[str, Any]],
) -> tuple[str | None, dict[str, Any] | None]:
    """Latest known override wins; otherwise latest known disposition.set."""
    overrides: list[tuple[dict[str, Any], str]] = []
    sets: list[tuple[dict[str, Any], str]] = []

    for event in events:
        event_type = event["event_type"]
        if event_type not in {"disposition.set", "disposition.override"}:
            continue

        code = str(_payload(event).get("disposition_code", "")).strip().lower()
        definition = dispositions.get((workflow_id, code))
        if definition is None:
            # Unknown dispositions are counted in data_quality and ignored here.
            continue

        target = overrides if event_type == "disposition.override" else sets
        target.append((event, code))

    candidates = overrides if overrides else sets
    if not candidates:
        return None, None

    event, code = max(
        candidates,
        key=lambda item: (_timestamp(item[0]["occurred_at"]), item[0]["event_id"]),
    )
    return code, dispositions[(workflow_id, code)]


def _derive_calls(
    linked_events: list[tuple[dict[str, Any], int]],
    dispositions: dict[tuple[str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build calls only from linked call.initiated events."""
    grouped: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for event, lead_id in linked_events:
        call_id = event["call_id"]
        if call_id:
            group_call_id = call_id
        elif event["event_type"] == "call.initiated":
            # A linked initiation still counts as a call even if a malformed
            # upstream record omitted call_id; it cannot be joined to later events.
            group_call_id = f"__missing_call_id__:{event['event_id']}"
        else:
            continue
        grouped[(event["workflow_id"], group_call_id, lead_id)].append(event)

    calls: list[dict[str, Any]] = []
    for (workflow_id, call_id, lead_id), call_events in grouped.items():
        initiated = [e for e in call_events if e["event_type"] == "call.initiated"]
        if not initiated:
            continue

        first_initiated = min(
            initiated,
            key=lambda e: (_timestamp(e["occurred_at"]), e["event_id"]),
        )
        disposition_code, disposition = _effective_disposition(
            call_events, workflow_id, dispositions
        )
        initiated_at = first_initiated["occurred_at"]
        calls.append(
            {
                "workflow_id": workflow_id,
                "call_id": call_id,
                "lead_id": lead_id,
                "initiated_at": initiated_at,
                "date": _timestamp(initiated_at).date().isoformat(),
                "connected": any(
                    e["event_type"] == "call.connected" for e in call_events
                ),
                "telephony_failed": any(
                    e["event_type"] == "call.telephony_failed" for e in call_events
                ),
                "current_disposition": disposition_code,
                "is_terminal": bool(disposition and disposition["is_terminal"]),
                "is_success": bool(disposition and disposition["is_success"]),
            }
        )

    return calls


def _csv_write(path: Path, columns: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=columns,
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def generate_reports(
    db_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Generate all five reports according to Assignment A's output contract."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    schemas = load_workflow_schemas()
    dispositions = load_dispositions()
    connection = get_connection(db_path)

    try:
        with connection:
            _apply_defaults(connection, schemas)

        leads_by_id, lead_index = _load_leads(connection, schemas)
        event_rows = [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM events ORDER BY occurred_at, event_id"
            ).fetchall()
        ]

        linked_events, orphan_count = _link_events(event_rows, lead_index)
        calls = _derive_calls(linked_events, dispositions)

        # Count unknown dispositions only after event-to-lead linking.
        unknown_disposition_count = 0
        for event, _lead_id in linked_events:
            if not event["event_type"].startswith("disposition."):
                continue
            code = str(_payload(event).get("disposition_code", "")).strip().lower()
            if (event["workflow_id"], code) not in dispositions:
                unknown_disposition_count += 1

        calls_by_lead: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for call in calls:
            calls_by_lead[call["lead_id"]].append(call)

        # Per-lead report and batch summary.
        lead_report_rows: list[dict[str, Any]] = []
        batch_counts: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)

        for lead_id, lead in leads_by_id.items():
            lead_calls = calls_by_lead.get(lead_id, [])
            lead_calls_sorted = sorted(
                lead_calls,
                key=lambda c: (_timestamp(c["initiated_at"]), c["call_id"]),
            )

            if not lead_calls:
                bucket = "yet_to_reach_out"
            elif any(call["is_terminal"] for call in lead_calls):
                bucket = "completed"
            elif all(call["telephony_failed"] for call in lead_calls):
                bucket = "in_progress_telephony_failed"
            else:
                bucket = "in_progress_dialed"

            latest_disposition_call = next(
                (
                    call
                    for call in reversed(lead_calls_sorted)
                    if call["current_disposition"] is not None
                ),
                None,
            )
            last_call = lead_calls_sorted[-1] if lead_calls_sorted else None
            phone = lead["phone"] or ""
            phone_masked = "+91******" + phone[-4:] if phone else ""

            lead_report_rows.append(
                {
                    "workflow_id": lead["workflow_id"],
                    "external_ref": lead["external_ref"],
                    "batch_id": lead["batch_id"],
                    "phone_masked": phone_masked,
                    "bucket": bucket,
                    "total_calls": len(lead_calls),
                    "connected_calls": sum(bool(c["connected"]) for c in lead_calls),
                    "last_call_at": last_call["initiated_at"] if last_call else "",
                    "current_disposition": (
                        latest_disposition_call["current_disposition"]
                        if latest_disposition_call else ""
                    ),
                    "ever_success": str(
                        any(call["is_success"] for call in lead_calls)
                    ).lower(),
                }
            )

            counter = batch_counts[(lead["workflow_id"], lead["batch_id"])]
            counter["total_leads"] += 1
            counter[bucket] += 1

        lead_report_rows.sort(key=lambda r: (r["workflow_id"], r["external_ref"]))

        batch_summary_rows = []
        for (workflow_id, batch_id), counter in sorted(batch_counts.items()):
            batch_summary_rows.append(
                {
                    "workflow_id": workflow_id,
                    "batch_id": batch_id,
                    "total_leads": counter["total_leads"],
                    "yet_to_reach_out": counter["yet_to_reach_out"],
                    "in_progress_telephony_failed": counter[
                        "in_progress_telephony_failed"
                    ],
                    "in_progress_dialed": counter["in_progress_dialed"],
                    "completed": counter["completed"],
                }
            )

        # Daily overview: only dates with at least one initiated call.
        daily: dict[tuple[str, str], dict[str, Any]] = {}
        for call in calls:
            key = (call["workflow_id"], call["date"])
            item = daily.setdefault(
                key,
                {"total_calls": 0, "connected_calls": 0, "success_leads": set()},
            )
            item["total_calls"] += 1
            item["connected_calls"] += int(call["connected"])
            if call["is_success"]:
                item["success_leads"].add(call["lead_id"])

        daily_rows = []
        for (workflow_id, date), item in sorted(daily.items()):
            total = item["total_calls"]
            connected = item["connected_calls"]
            daily_rows.append(
                {
                    "workflow_id": workflow_id,
                    "date": date,
                    "total_calls": total,
                    "connected_calls": connected,
                    "connectivity_rate": f"{connected / total:.4f}",
                    "success_leads": len(item["success_leads"]),
                }
            )

        # Rejections: deliberately contains no PII.
        rejection_rows = [
            dict(row)
            for row in connection.execute(
                "SELECT workflow_id, batch_id, row_number, reason "
                "FROM lead_rejections "
                "ORDER BY workflow_id, batch_id, row_number"
            ).fetchall()
        ]
        rejection_counts = Counter(row["reason"] for row in rejection_rows)

        # Aggregate ingestion counters recorded atomically per drop.
        quality_totals = {key: 0 for key in QUALITY_KEYS}
        for row in connection.execute(
            "SELECT stats_json FROM ingested_drops"
        ).fetchall():
            stats = json.loads(row["stats_json"] or "{}")
            for key in QUALITY_KEYS:
                quality_totals[key] += int(stats.get(key, 0))

        data_quality = {
            "lead_rows_total": quality_totals["lead_rows_total"],
            "lead_rows_rejected": quality_totals["lead_rows_rejected"],
            "rejections_by_reason": dict(sorted(rejection_counts.items())),
            "duplicate_lead_rows_merged": quality_totals[
                "duplicate_lead_rows_merged"
            ],
            "field_warnings": quality_totals["field_warnings"],
            "events_total": quality_totals["events_total"],
            "malformed_events": quality_totals["malformed_events"],
            "duplicate_events_dropped": quality_totals[
                "duplicate_events_dropped"
            ],
            "orphan_events": orphan_count,
            "unknown_disposition_events": unknown_disposition_count,
        }

        _csv_write(
            output_dir / "batch_summary.csv",
            [
                "workflow_id", "batch_id", "total_leads", "yet_to_reach_out",
                "in_progress_telephony_failed", "in_progress_dialed", "completed",
            ],
            batch_summary_rows,
        )
        _csv_write(
            output_dir / "daily_overview.csv",
            [
                "workflow_id", "date", "total_calls", "connected_calls",
                "connectivity_rate", "success_leads",
            ],
            daily_rows,
        )
        _csv_write(
            output_dir / "lead_report.csv",
            [
                "workflow_id", "external_ref", "batch_id", "phone_masked", "bucket",
                "total_calls", "connected_calls", "last_call_at",
                "current_disposition", "ever_success",
            ],
            lead_report_rows,
        )
        _csv_write(
            output_dir / "rejections.csv",
            ["workflow_id", "batch_id", "row_number", "reason"],
            rejection_rows,
        )
        with (output_dir / "data_quality.json").open(
            "w", encoding="utf-8", newline="\n"
        ) as file:
            json.dump(data_quality, file, indent=2, ensure_ascii=False)
            file.write("\n")

        return {
            "output_dir": str(output_dir),
            "lead_count": len(leads_by_id),
            "linked_event_count": len(linked_events),
            "orphan_events": orphan_count,
            "call_count": len(calls),
            "files": [
                "batch_summary.csv",
                "daily_overview.csv",
                "lead_report.csv",
                "rejections.csv",
                "data_quality.json",
            ],
        }
    finally:
        connection.close()
