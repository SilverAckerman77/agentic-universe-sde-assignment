import csv
import json

from solution.database.connection import get_connection
from solution.database.initialize import initialize_database
from solution.database.repository import upsert_lead_record
from solution.ingestion.schema_loader import load_workflow_schemas
from agentic_assignment_reporting.reports import generate_reports
from solution.security.encryption import phone_digest


def _insert_event(connection, event_id, event_type, call_id, occurred_at,
                  phone_hash=None, payload=None, unknown=False):
    connection.execute(
        """
        INSERT INTO events (
            event_id, event_type, workflow_id, call_id, occurred_at,
            phone_hash, payload_json, source_drop, is_unknown_disposition
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id, event_type, "motor_renewal", call_id, occurred_at,
            phone_hash, json.dumps(payload or {}), "drop_1", int(unknown),
        ),
    )


def test_reports_override_orphan_unknown_and_exact_columns(tmp_path):
    db_path = tmp_path / "report_test.sqlite3"
    out_dir = tmp_path / "reports"
    initialize_database(db_path)
    schemas = load_workflow_schemas()
    schema = schemas["motor_renewal"]
    phone = "+919876543210"
    digest = phone_digest(phone)

    lead = {
        "workflow_id": "motor_renewal",
        "batch_id": "batch_001",
        "customer_name": "Rahul Sharma",
        "phone": phone,
        "policy_number": "POL001",
        "policy_expiry": "2026-12-01",
        "premium_amount": "12000.00",
        "preferred_language": None,
    }

    connection = get_connection(db_path)
    try:
        with connection:
            assert upsert_lead_record(connection, lead, schema) is False
            _insert_event(
                connection, "e1", "call.initiated", "c1",
                "2026-10-01T10:00:00+05:30", digest,
            )
            _insert_event(
                connection, "e2", "call.connected", "c1",
                "2026-10-01T10:01:00+05:30", digest,
            )
            _insert_event(
                connection, "e3", "disposition.set", "c1",
                "2026-10-01T10:02:00+05:30", digest,
                {"disposition_code": "callback_requested"},
            )
            # Override is phone-less and must link via call_id.
            _insert_event(
                connection, "e4", "disposition.override", "c1",
                "2026-10-01T10:03:00+05:30", None,
                {"disposition_code": "renewed", "overridden_by": "supervisor"},
            )
            # Unknown disposition is linked, counted, and ignored.
            _insert_event(
                connection, "e5", "disposition.set", "c1",
                "2026-10-01T10:04:00+05:30", digest,
                {"disposition_code": "not_a_real_code"}, True,
            )
            # This event has no matching lead and must be quarantined from reports.
            _insert_event(
                connection, "e6", "call.initiated", "c_orphan",
                "2026-10-01T11:00:00+05:30",
                phone_digest("+919999999999"),
            )
            connection.execute(
                """INSERT INTO ingested_drops
                   (drop_key, drop_name, source_path, stats_json)
                   VALUES (?, ?, ?, ?)""",
                (
                    "drop_1", "drop_1", "drop_1",
                    json.dumps({
                        "lead_rows_total": 1,
                        "lead_rows_rejected": 0,
                        "duplicate_lead_rows_merged": 0,
                        "field_warnings": 0,
                        "events_total": 6,
                        "malformed_events": 0,
                        "duplicate_events_dropped": 0,
                    }),
                ),
            )
    finally:
        connection.close()

    result = generate_reports(db_path, out_dir)
    assert result["lead_count"] == 1
    assert result["linked_event_count"] == 5
    assert result["orphan_events"] == 1
    assert result["call_count"] == 1

    with (out_dir / "lead_report.csv").open(encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    assert rows[0]["phone_masked"] == "+91******3210"
    assert rows[0]["bucket"] == "completed"
    assert rows[0]["total_calls"] == "1"
    assert rows[0]["connected_calls"] == "1"
    assert rows[0]["current_disposition"] == "renewed"
    assert rows[0]["ever_success"] == "true"

    with (out_dir / "daily_overview.csv").open(encoding="utf-8", newline="") as file:
        daily = list(csv.DictReader(file))
    assert daily[0]["connectivity_rate"] == "1.0000"
    assert daily[0]["success_leads"] == "1"

    with (out_dir / "batch_summary.csv").open(encoding="utf-8", newline="") as file:
        batch = list(csv.DictReader(file))
    assert batch[0]["total_leads"] == "1"
    assert batch[0]["completed"] == "1"

    quality = json.loads((out_dir / "data_quality.json").read_text(encoding="utf-8"))
    assert quality["orphan_events"] == 1
    assert quality["unknown_disposition_events"] == 1
    assert quality["events_total"] == 6

    with (out_dir / "rejections.csv").open(encoding="utf-8", newline="") as file:
        assert list(csv.DictReader(file)) == []


def test_report_files_are_written_with_headers_for_empty_database(tmp_path):
    db_path = tmp_path / "empty.sqlite3"
    out_dir = tmp_path / "empty_reports"
    initialize_database(db_path)

    generate_reports(db_path, out_dir)

    expected_headers = {
        "batch_summary.csv": "workflow_id,batch_id,total_leads,yet_to_reach_out,in_progress_telephony_failed,in_progress_dialed,completed",
        "daily_overview.csv": "workflow_id,date,total_calls,connected_calls,connectivity_rate,success_leads",
        "lead_report.csv": "workflow_id,external_ref,batch_id,phone_masked,bucket,total_calls,connected_calls,last_call_at,current_disposition,ever_success",
        "rejections.csv": "workflow_id,batch_id,row_number,reason",
    }
    for filename, header in expected_headers.items():
        first_line = (out_dir / filename).read_text(encoding="utf-8").splitlines()[0]
        assert first_line == header
