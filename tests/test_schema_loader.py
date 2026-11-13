
from solution.ingestion.schema_loader import (
    load_workflow_schemas,
    load_dispositions,
    build_header_mapping,
)


def test_load_workflows():
    schemas = load_workflow_schemas()

    assert "motor_renewal" in schemas
    assert "policy_feedback" in schemas


def test_motor_renewal_fields():
    schemas = load_workflow_schemas()

    fields = schemas["motor_renewal"]["fields"]
    names = [field["name"] for field in fields]

    assert "customer_name" in names
    assert "phone" in names
    assert "policy_number" in names


def test_policy_feedback_fields():
    schemas = load_workflow_schemas()

    fields = schemas["policy_feedback"]["fields"]
    names = [field["name"] for field in fields]

    assert "order_id" in names
    assert "product" in names


def test_load_dispositions():
    dispositions = load_dispositions()

    assert ("motor_renewal", "renewed") in dispositions
    assert ("policy_feedback", "feedback_captured") in dispositions


def test_disposition_flags():
    dispositions = load_dispositions()

    renewed = dispositions[("motor_renewal", "renewed")]

    assert renewed["is_terminal"] is True
    assert renewed["is_success"] is True


def test_header_mapping():
    schemas = load_workflow_schemas()
    fields = schemas["motor_renewal"]["fields"]

    headers = ["Name", "Mobile_No", "Policy No", "Premium"]

    mapping = build_header_mapping(headers, fields)

    assert mapping == {
        0: "customer_name",
        1: "phone",
        2: "policy_number",
        3: "premium_amount",
    }


def test_unknown_headers_ignored():
    schemas = load_workflow_schemas()
    fields = schemas["motor_renewal"]["fields"]

    mapping = build_header_mapping(
        ["Name", "Unused Column"],
        fields
    )

    assert mapping == {0: "customer_name"}
