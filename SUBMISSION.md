# Submission

## Candidate

- Name: Neeraj N
- Assignment chosen: A — Interaction Ledger & Reporting Pipeline
- Time spent: 6 hours (1hour to plan and the rest took to execute)

## How to run

Requirements: Python 3.11+

### Windows PowerShell setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Generate local encryption keys:

```powershell
python -c "from cryptography.fernet import Fernet; import secrets; from pathlib import Path; Path('.env').write_text('FERNET_KEY='+Fernet.generate_key().decode()+'\nPHONE_HMAC_KEY='+secrets.token_hex(32)+'\n', encoding='utf-8')"
```

Generate the synthetic dataset:

```powershell
python assignment-a-data\tools\generate_data.py --seed 42 --scale small --out data
```

Run ingestion:

```powershell
python -m solution.ingestion.pipeline ingest data\drop_1
python -m solution.ingestion.pipeline ingest data\drop_2
```

Generate reports:

```powershell
python -m solution.ingestion.pipeline report --out reports/
```

Run tests:

```powershell
python -m pytest tests/ -v
```

## Design

The implementation uses Python and SQLite to build a schema-driven interaction ledger and reporting pipeline.

Lead ingestion reads workflow-specific CSV schemas, maps header aliases, normalizes values, validates required fields and records rejected rows. Duplicate leads are identified using the workflow ID and canonical phone hash. The first batch ID is retained, and subsequent non-null values overwrite existing values.

Customer PII fields are encrypted using Fernet. Canonical phone numbers are matched through deterministic HMAC-SHA256 hashes, allowing event-to-lead linking without storing plaintext phone numbers.

The SQLite database contains separate tables for leads, interaction events, lead rejections and ingested-drop tracking. Event IDs are unique, and database triggers prevent event updates and deletions.

Events are linked dynamically during reporting. This allows events received before their leads to become linkable after subsequent drops are ingested. Supervisor overrides are resolved through call IDs.

The reporting engine derives call metrics, effective dispositions, lead buckets, batch summaries and data-quality statistics.

## Decisions & assumptions

| Decision | Why | Alternative considered |
|---|---|---|
| SQLite database | Simple deployment and supported by the assignment | PostgreSQL |
| Fernet encryption for PII | Protects sensitive fields at rest | Plaintext storage, rejected |
| HMAC-SHA256 phone matching | Deterministic matching without plaintext phone storage | Encrypted phone lookup |
| Dynamic orphan resolution | Supports leads arriving after their events | Permanently classifying early events as orphaned |
| Database event triggers | Protects the append-only ledger | Application-only enforcement |
| Absolute source path for drop tracking | Prevents accidental re-ingestion of the same path | Content-based drop fingerprint |

A resolved drop path is used as the idempotency key. Moving an already processed drop to another path is not treated as the same ingestion identity.

## Failure modes considered

- Invalid JSON and missing event identifiers are counted as malformed events.
- Duplicate event IDs are skipped globally.
- Invalid lead rows are rejected with a reason.
- Duplicate leads are merged without changing their original batch ID.
- Unknown linked dispositions are counted and excluded from outcome calculations.
- Orphan events are retained in the ledger and excluded from reports until they can be linked.
- Database transactions ensure a drop is not marked as processed before ingestion succeeds.
- Encryption keys must be retained to decrypt existing PII.

## Testing

The implementation was tested with pytest on Windows using Python 3.14.3.

Testing covers:

- Phone, date, decimal and header normalization.
- Workflow schema and disposition loading.
- Lead validation and duplicate merging.
- PII encryption and deterministic phone hashing.
- SQLite initialization and append-only event protection.
- Event timestamp normalization and duplicate handling.
- Reporting, supervisor overrides, unknown dispositions and orphan events.
- Empty-database report generation.

The pipeline was also executed on synthetic datasets generated with seeds 42 and 73.

## Results

### Seed 42

- Total input lead rows: 2,057
- Rejected rows: 108
- Merged duplicate lead rows: 57
- Final unique leads: 1,892
- Total event lines: 8,745
- Malformed events: 8
- Duplicate events dropped: 237
- Linked events: 8,038
- Orphan events: 462
- Calls: 2,536

### Seed 73

- Total input lead rows: 2,055
- Rejected rows: 89
- Merged duplicate lead rows: 55
- Final unique leads: 1,911
- Total event lines: 8,656
- Malformed events: 8
- Duplicate events dropped: 266
- Linked events: 8,039
- Orphan events: 343
- Calls: 2,511

Performance timings have not been benchmarked.

## If I had another day

1. Add more edge-case tests for disposition precedence and every lead bucket.
2. Benchmark the large synthetic dataset and improve query performance.
3. Implement content-based drop fingerprints for stronger idempotency across moved directories.
4. Add more extensive crash-recovery and transaction tests.
5. Improve operational logging and monitoring.