
CREATE TABLE IF NOT EXISTS leads (
    lead_id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_id TEXT NOT NULL,
    phone_hash TEXT NOT NULL,
    pii_encrypted TEXT NOT NULL,
    external_ref TEXT NOT NULL,
    attributes_json TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(workflow_id, phone_hash)
);

CREATE INDEX IF NOT EXISTS idx_leads_workflow_batch
ON leads(workflow_id, batch_id);

CREATE INDEX IF NOT EXISTS idx_leads_external_ref
ON leads(workflow_id, external_ref);


CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    workflow_id TEXT NOT NULL,
    call_id TEXT,
    occurred_at TEXT NOT NULL,
    phone_hash TEXT,
    payload_json TEXT NOT NULL,
    source_drop TEXT NOT NULL,
    is_unknown_disposition INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_events_call
ON events(workflow_id, call_id);

CREATE INDEX IF NOT EXISTS idx_events_phone
ON events(workflow_id, phone_hash);

CREATE INDEX IF NOT EXISTS idx_events_time
ON events(workflow_id, occurred_at);


CREATE TABLE IF NOT EXISTS lead_rejections (
    rejection_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_drop TEXT NOT NULL,
    workflow_id TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    row_number INTEGER NOT NULL,
    reason TEXT NOT NULL,

    UNIQUE(source_drop, workflow_id, batch_id, row_number)
);

CREATE TABLE IF NOT EXISTS ingested_drops (
    drop_key TEXT PRIMARY KEY,
    drop_name TEXT NOT NULL,
    source_path TEXT NOT NULL,
    processed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    stats_json TEXT NOT NULL
);


CREATE TRIGGER IF NOT EXISTS events_no_update
BEFORE UPDATE ON events
BEGIN
    SELECT RAISE(ABORT, 'Interaction ledger is append-only');
END;

CREATE TRIGGER IF NOT EXISTS events_no_delete
BEFORE DELETE ON events
BEGIN
    SELECT RAISE(ABORT, 'Interaction ledger is append-only');
END;
