-- Mission Control local database (writable MC state: snapshots + alerts).
-- This is SEPARATE from Hermes' own state.db files, which are opened read-only.
-- Path A tables (approvals, commands) are reserved for the v2 control channel.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- Reserved for Path A (v2): the approval/control channel. Empty in v1.
CREATE TABLE IF NOT EXISTS approvals (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id   TEXT    UNIQUE NOT NULL,
    agent        TEXT    NOT NULL,
    kind         TEXT    NOT NULL,                -- 'tool_call' | 'command' | 'deploy'
    payload_json TEXT,
    status       TEXT    NOT NULL DEFAULT 'pending',  -- pending|approved|rejected|cancelled
    requested_at REAL    NOT NULL,
    decided_at   REAL,
    decided_by   TEXT,
    note         TEXT
);

-- Reserved for Path A (v2): outbound commands to agents. Empty in v1.
CREATE TABLE IF NOT EXISTS commands (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    command_id   TEXT    UNIQUE NOT NULL,
    target_agent TEXT    NOT NULL,
    command      TEXT    NOT NULL,                -- 'pause' | 'resume' | 'stop' | 'retry'
    payload_json TEXT,
    status       TEXT    NOT NULL DEFAULT 'queued',   -- queued|sent|acknowledged|failed
    created_at   REAL    NOT NULL,
    sent_at      REAL,
    ack_at       REAL,
    result_json  TEXT
);

-- Periodic snapshots of the derived state (drives the "replay" panel).
CREATE TABLE IF NOT EXISTS snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at REAL    NOT NULL,
    state_json  TEXT    NOT NULL,
    fingerprint TEXT
);
CREATE INDEX IF NOT EXISTS idx_snapshots_captured ON snapshots(captured_at);

-- Raised/resolved alerts (stuck agent, offline, error burst, budget risk).
CREATE TABLE IF NOT EXISTS alerts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT    NOT NULL,
    severity    TEXT    NOT NULL,
    agent       TEXT,
    message     TEXT    NOT NULL,
    data_json   TEXT,
    raised_at   REAL    NOT NULL,
    resolved_at REAL
);
CREATE INDEX IF NOT EXISTS idx_alerts_raised ON alerts(raised_at);
CREATE INDEX IF NOT EXISTS idx_alerts_open ON alerts(resolved_at) WHERE resolved_at IS NULL;
