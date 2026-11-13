
import argparse
import json
import sqlite3

from pathlib import Path

from solution.database.connection import get_connection
from solution.database.initialize import initialize_database
from solution.database.repository import (
    upsert_lead_record,
    save_rejections,
)
from solution.ingestion.leads import ingest_lead_file
from solution.ingestion.events import ingest_event_files
from solution.ingestion.schema_loader import (
    load_workflow_schemas,
    load_dispositions,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_DB_PATH = (
    PROJECT_ROOT / "data" / "interaction_ledger.sqlite3"
)


def ingest_drop(
    drop_path: str | Path,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict:
    """Ingest all lead batches and event files from one drop."""

    drop_dir = Path(drop_path).resolve()
    db_path = Path(db_path)

    if not drop_dir.is_dir():
        raise FileNotFoundError(
            f"Drop directory does not exist: {drop_dir}"
        )

    drop_name = drop_dir.name
    drop_key = str(drop_dir)

    schemas = load_workflow_schemas()
    dispositions = load_dispositions()

    # Initialize tables before starting the ingestion transaction.
    initialize_database(db_path)

    connection = get_connection(db_path)

    stats = {
        "lead_rows_total": 0,
        "lead_rows_rejected": 0,
        "duplicate_lead_rows_merged": 0,
        "field_warnings": 0,
        "events_total": 0,
        "malformed_events": 0,
        "duplicate_events_dropped": 0,
    }

    try:
        existing = connection.execute(
            """
            SELECT 1
            FROM ingested_drops
            WHERE drop_key = ?
            """,
            (drop_key,),
        ).fetchone()

        if existing:
            return {
                "already_ingested": True,
                "drop": drop_name,
                "stats": stats,
            }

        # All changes for this drop commit together.
        with connection:

            # 1. Ingest workflow-specific lead files.
            for workflow_id, schema in schemas.items():

                lead_dir = (
                    drop_dir / "leads" / workflow_id
                )

                if not lead_dir.exists():
                    continue

                for lead_file in sorted(lead_dir.glob("*.csv")):

                    result = ingest_lead_file(
                        lead_file,
                        schema,
                    )

                    stats["lead_rows_total"] += result.rows_total

                    stats["lead_rows_rejected"] += len(
                        result.rejections
                    )

                    stats["field_warnings"] += (
                        result.field_warnings
                    )

                    save_rejections(
                        connection,
                        drop_name,
                        workflow_id,
                        result.rejections,
                    )

                    for lead in result.leads:

                        was_duplicate = upsert_lead_record(
                            connection,
                            lead,
                            schema,
                        )

                        if was_duplicate:
                            stats[
                                "duplicate_lead_rows_merged"
                            ] += 1

            # 2. Ingest event files after lead processing.
            event_stats = ingest_event_files(
                connection,
                drop_dir,
                dispositions,
            )

            stats.update(event_stats)

            # 3. Mark the drop as fully processed.
            connection.execute(
                """
                INSERT INTO ingested_drops (
                    drop_key,
                    drop_name,
                    source_path,
                    stats_json
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    drop_key,
                    drop_name,
                    str(drop_dir),
                    json.dumps(stats),
                ),
            )

        return {
            "already_ingested": False,
            "drop": drop_name,
            "stats": stats,
        }

    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(
        description="Agentic Universe interaction pipeline"
    )

    parser.add_argument(
        "command",
        choices=["ingest"],
    )

    parser.add_argument(
        "drop_path",
    )

    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB_PATH),
    )

    args = parser.parse_args()

    if args.command == "ingest":

        result = ingest_drop(
            args.drop_path,
            args.db,
        )

        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
