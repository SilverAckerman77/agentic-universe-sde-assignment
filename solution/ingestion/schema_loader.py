
import csv
import json
from pathlib import Path

from solution.ingestion.normalizers import normalize_header


ROOT_DIR = Path(__file__).resolve().parents[2]
SCHEMA_DIR = ROOT_DIR / "assignment-a-data" / "schemas"


def load_workflow_schemas(schema_dir: Path = SCHEMA_DIR) -> dict:
    """
    Load every workflow JSON schema.

    Returns:
        {
            "motor_renewal": {...},
            "policy_feedback": {...}
        }
    """
    schemas = {}

    for schema_file in sorted(schema_dir.glob("*.json")):
        with schema_file.open("r", encoding="utf-8") as file:
            schema = json.load(file)

        workflow_id = schema.get("workflow_id")
        fields = schema.get("fields")

        if not workflow_id or not isinstance(fields, list):
            raise ValueError(f"Invalid workflow schema: {schema_file.name}")

        names = set()

        for field in fields:
            name = field.get("name")

            if not name or name in names:
                raise ValueError(
                    f"Missing or duplicate field name in {schema_file.name}"
                )

            names.add(name)

            if field.get("type") not in {
                "string", "phone", "date", "decimal", "enum"
            }:
                raise ValueError(f"Unsupported field type: {name}")

        if workflow_id in schemas:
            raise ValueError(f"Duplicate workflow: {workflow_id}")

        schemas[workflow_id] = schema

    return schemas


def load_dispositions(
    disposition_file: Path = SCHEMA_DIR / "dispositions.csv"
) -> dict:
    """
    Load disposition definitions.

    Returns:
        {
            ("motor_renewal", "renewed"): {
                "label": "Policy renewed",
                "is_terminal": True,
                "is_success": True
            }
        }
    """
    dispositions = {}

    with disposition_file.open(
        "r", encoding="utf-8-sig", newline=""
    ) as file:

        reader = csv.DictReader(file)

        required_columns = {
            "workflow_id",
            "code",
            "label",
            "is_terminal",
            "is_success",
        }

        if not required_columns.issubset(reader.fieldnames or []):
            raise ValueError("Invalid dispositions.csv header")

        for row in reader:
            workflow_id = row["workflow_id"].strip()
            code = row["code"].strip().lower()

            key = (workflow_id, code)

            if key in dispositions:
                raise ValueError(f"Duplicate disposition: {key}")

            def parse_bool(value):
                value = value.strip().lower()
                if value not in {"true", "false"}:
                    raise ValueError(f"Invalid boolean: {value}")
                return value == "true"

            dispositions[key] = {
                "label": row["label"].strip(),
                "is_terminal": parse_bool(row["is_terminal"]),
                "is_success": parse_bool(row["is_success"]),
            }

    return dispositions


def build_header_mapping(headers: list[str], fields: list[dict]) -> dict:
    """
    Map CSV column indexes to schema field names.

    Example:
        ["Name", "Mobile_No", "Policy No"]
        -> {0: "customer_name", 1: "phone", 2: "policy_number"}
    """
    aliases = {}

    for field in fields:
        candidates = [field["name"]] + field.get("aliases", [])

        for candidate in candidates:
            normalized = normalize_header(candidate)

            if normalized in aliases and aliases[normalized] != field["name"]:
                raise ValueError(
                    f"Ambiguous schema alias: {candidate}"
                )

            aliases[normalized] = field["name"]

    mapping = {}

    for index, header in enumerate(headers):
        normalized = normalize_header(header)

        if normalized in aliases:
            mapping[index] = aliases[normalized]

    return mapping
