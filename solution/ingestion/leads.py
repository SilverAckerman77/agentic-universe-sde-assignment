
import csv
from dataclasses import dataclass
from pathlib import Path

from solution.ingestion.normalizers import normalize_value
from solution.ingestion.schema_loader import build_header_mapping


@dataclass
class LeadFileResult:
    leads: list[dict]
    rejections: list[dict]
    rows_total: int
    field_warnings: int


def ingest_lead_file(
    file_path: Path,
    workflow_schema: dict,
) -> LeadFileResult:
    """
    Read and validate one lead CSV file.

    Returns accepted leads, rejected rows, row count,
    and optional-field warning count.
    """
    file_path = Path(file_path)

    workflow_id = workflow_schema["workflow_id"]
    fields = workflow_schema["fields"]
    batch_id = file_path.stem

    accepted = []
    rejections = []
    rows_total = 0
    field_warnings = 0

    with file_path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:

        reader = csv.reader(file)

        try:
            headers = next(reader)
        except StopIteration:
            return LeadFileResult([], [], 0, 0)

        header_mapping = build_header_mapping(headers, fields)

        # Reverse index: schema field -> CSV column index.
        field_indexes = {}

        for index, field_name in header_mapping.items():
            field_indexes.setdefault(field_name, index)

        for row in reader:

            # Ignore completely blank rows.
            if all(not cell.strip() for cell in row):
                continue

            rows_total += 1
            row_number = rows_total

            lead = {
                "workflow_id": workflow_id,
                "batch_id": batch_id,
            }

            row_error = None
            row_warning_count = 0

            # Always process fields in schema order.
            for field in fields:
                name = field["name"]
                field_type = field["type"]

                column_index = field_indexes.get(name)

                raw_value = (
                    row[column_index]
                    if column_index is not None
                    and column_index < len(row)
                    else ""
                )

                raw_value = raw_value.strip()

                if not raw_value:

                    lead[name] = None

                    if field.get("required", False):
                        row_error = f"missing_required:{name}"
                        break

                    continue

                try:
                    lead[name] = normalize_value(raw_value, field)

                except ValueError:

                    lead[name] = None

                    if field_type == "phone":
                        row_error = "invalid_phone"
                        break

                    row_warning_count += 1

            if row_error:
                rejections.append({
                    "workflow_id": workflow_id,
                    "batch_id": batch_id,
                    "row_number": row_number,
                    "reason": row_error,
                })
                continue

            # Only accepted rows contribute field warnings.
            field_warnings += row_warning_count
            accepted.append(lead)

    return LeadFileResult(
        leads=accepted,
        rejections=rejections,
        rows_total=rows_total,
        field_warnings=field_warnings,
    )


def upsert_lead(
    lead_index: dict,
    incoming: dict,
) -> bool:
    """
    Insert a new lead or merge a duplicate.

    Identity: (workflow_id, canonical phone)

    Returns True when a duplicate is merged.
    Returns False when a new lead is inserted.
    """
    identity = (
        incoming["workflow_id"],
        incoming["phone"],
    )

    existing = lead_index.get(identity)

    if existing is None:
        lead_index[identity] = dict(incoming)
        return False

    # Preserve original batch_id and lead identity.
    protected_fields = {
        "workflow_id",
        "phone",
        "batch_id",
    }

    # Last non-null value wins.
    for field_name, value in incoming.items():

        if field_name in protected_fields:
            continue

        if value is not None:
            existing[field_name] = value

    return True


def apply_defaults(
    lead_index: dict,
    workflow_schema: dict,
) -> None:
    """
    Apply schema defaults after all batches are merged.
    """
    for lead in lead_index.values():

        if lead["workflow_id"] != workflow_schema["workflow_id"]:
            continue

        for field in workflow_schema["fields"]:

            name = field["name"]

            if (
                lead.get(name) is None
                and "default" in field
            ):
                lead[name] = field["default"]
