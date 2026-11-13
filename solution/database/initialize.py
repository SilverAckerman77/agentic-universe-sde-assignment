
from pathlib import Path

from solution.database.connection import get_connection


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_FILE = PROJECT_ROOT / "solution" / "database" / "schema.sql"


def initialize_database(db_path=None):
    """Create database tables and indexes."""
    connection = get_connection(
        db_path if db_path is not None else
        PROJECT_ROOT / "data" / "interaction_ledger.sqlite3"
    )

    try:
        sql = SCHEMA_FILE.read_text(encoding="utf-8")
        connection.executescript(sql)
        connection.commit()
    finally:
        connection.close()


if __name__ == "__main__":
    initialize_database()
    print("Database initialized successfully.")
