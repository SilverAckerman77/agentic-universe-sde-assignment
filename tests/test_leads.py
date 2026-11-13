
import csv

from solution.ingestion.leads import (
    ingest_lead_file,
    upsert_lead,
    apply_defaults,
)
from solution.ingestion.schema_loader import load_workflow_schemas


def test_lead_ingestion_and_rejections(tmp_path):
    schemas = load_workflow_schemas()
    schema = schemas["motor_renewal"]

    file_path = tmp_path / "batch_001.csv"

    headers = [
        "Name",
        "Mobile No",
        "Policy No",
        "Expiry Date",
        "Premium",
        "Language",
    ]

    rows = [
        ["Rahul", "9876543210", "POL001",
         "01-Dec-2026", "12000", "EN"],

        ["", "", "", "", "", ""],

        ["", "5123456789", "POL002",
         "10-Dec-2026", "15000", "HI"],

        ["Priya", "8765432109", "POL003",
         "soon", "twelve thousand", "Hindi"],
    ]

    with file_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(headers)
        writer.writerows(rows)

    result = ingest_lead_file(file_path, schema)

    assert result.rows_total == 3
    assert len(result.leads) == 2
    assert len(result.rejections) == 1

    assert result.rejections[0]["row_number"] == 2
    assert result.rejections[0]["reason"] == (
        "missing_required:customer_name"
    )

    assert result.field_warnings == 3


def test_duplicate_lead_merge():
    lead_index = {}

    first = {
        "workflow_id": "motor_renewal",
        "batch_id": "batch_001",
        "customer_name": "Rahul",
        "phone": "+919876543210",
        "premium_amount": "12000.00",
        "preferred_language": None,
    }

    second = {
        "workflow_id": "motor_renewal",
        "batch_id": "batch_003",
        "customer_name": "Rahul Kumar",
        "phone": "+919876543210",
        "premium_amount": None,
        "preferred_language": "hi",
    }

    assert upsert_lead(lead_index, first) is False
    assert upsert_lead(lead_index, second) is True

    merged = lead_index[
        ("motor_renewal", "+919876543210")
    ]

    assert merged["customer_name"] == "Rahul Kumar"
    assert merged["batch_id"] == "batch_001"
    assert merged["premium_amount"] == "12000.00"
    assert merged["preferred_language"] == "hi"


def test_defaults_applied_after_merge():
    schemas = load_workflow_schemas()
    schema = schemas["motor_renewal"]

    lead_index = {
        ("motor_renewal", "+919876543210"): {
            "workflow_id": "motor_renewal",
            "batch_id": "batch_001",
            "customer_name": "Rahul",
            "phone": "+919876543210",
            "policy_number": "POL001",
            "preferred_language": None,
        }
    }

    apply_defaults(lead_index, schema)

    lead = lead_index[
        ("motor_renewal", "+919876543210")
    ]

    assert lead["preferred_language"] == "en"
