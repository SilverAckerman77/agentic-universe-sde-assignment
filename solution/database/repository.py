
import json
import sqlite3

from solution.security.encryption import (
    encrypt_pii,
    decrypt_pii,
    phone_digest,
)


def upsert_lead_record(
    connection: sqlite3.Connection,
    lead: dict,
    workflow_schema: dict,
) -> bool:
    """
    Insert or merge one lead.

    Returns:
        False: new lead inserted.
        True: existing lead merged.
    """
    workflow_id = lead["workflow_id"]
    canonical_phone = lead["phone"]
    phone_hash = phone_digest(canonical_phone)

    fields = workflow_schema["fields"]

    pii_fields = {
        field["name"]
        for field in fields
        if field.get("pii", False)
    }

    reference_fields = [
        field["name"]
        for field in fields
        if field.get("reference", False)
    ]

    if len(reference_fields) != 1:
        raise ValueError(
            f"Expected one reference field for {workflow_id}"
        )

    reference_name = reference_fields[0]
    external_ref = lead.get(reference_name)

    if not external_ref:
        raise ValueError("Lead is missing its external reference")

    identity = connection.execute(
        """
        SELECT *
        FROM leads
        WHERE workflow_id = ?
          AND phone_hash = ?
        """,
        (workflow_id, phone_hash),
    ).fetchone()

    if identity is None:

        pii_data = {
            name: lead.get(name)
            for name in pii_fields
        }

        attributes = {
            field["name"]: lead.get(field["name"])
            for field in fields
            if field["name"] not in pii_fields
            and not field.get("reference", False)
        }

        connection.execute(
            """
            INSERT INTO leads (
                workflow_id,
                phone_hash,
                pii_encrypted,
                external_ref,
                attributes_json,
                batch_id
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                workflow_id,
                phone_hash,
                encrypt_pii(pii_data),
                external_ref,
                json.dumps(attributes, ensure_ascii=False),
                lead["batch_id"],
            ),
        )

        return False

    # Existing identity: decrypt current PII before merging.
    pii_data = decrypt_pii(identity["pii_encrypted"])
    attributes = json.loads(identity["attributes_json"])
    merged_reference = identity["external_ref"]

    for field in fields:

        name = field["name"]

        # Phone is the permanent identity of the lead.
        if name == "phone":
            continue

        incoming_value = lead.get(name)

        # Null never overwrites existing data.
        if incoming_value is None:
            continue

        if name in pii_fields:
            pii_data[name] = incoming_value

        elif field.get("reference", False):
            merged_reference = incoming_value

        else:
            attributes[name] = incoming_value

    connection.execute(
        """
        UPDATE leads
        SET pii_encrypted = ?,
            external_ref = ?,
            attributes_json = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE lead_id = ?
        """,
        (
            encrypt_pii(pii_data),
            merged_reference,
            json.dumps(attributes, ensure_ascii=False),
            identity["lead_id"],
        ),
    )

    # batch_id deliberately remains unchanged.
    return True


def save_rejections(
    connection: sqlite3.Connection,
    source_drop: str,
    workflow_id: str,
    rejections: list[dict],
) -> None:
    """Persist rejection metadata without storing customer PII."""

    connection.executemany(
        """
        INSERT OR IGNORE INTO lead_rejections (
            source_drop,
            workflow_id,
            batch_id,
            row_number,
            reason
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            (
                source_drop,
                workflow_id,
                item["batch_id"],
                item["row_number"],
                item["reason"],
            )
            for item in rejections
        ],
    )
