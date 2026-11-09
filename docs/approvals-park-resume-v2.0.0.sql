-- Proposed additive v2 schema; approvals exists. Application validates JSON/hash/auth.
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS approval_context_v2 (
 request_id TEXT PRIMARY KEY REFERENCES approvals(request_id),
 intent_id TEXT UNIQUE NOT NULL, board_id TEXT NOT NULL, card_id TEXT NOT NULL,
 profile TEXT NOT NULL, origin_session_id TEXT NOT NULL, origin_run_id TEXT NOT NULL,
 tool_name TEXT NOT NULL, action_hash TEXT NOT NULL CHECK(length(action_hash)=64),
 hash_version INTEGER NOT NULL CHECK(hash_version=1),
 execution_context_json TEXT NOT NULL, redacted_detail TEXT NOT NULL,
 expires_at REAL NOT NULL, terminal_reason TEXT,
 decision_id TEXT UNIQUE, decision_actor_id TEXT
);
CREATE TABLE IF NOT EXISTS approval_parks_v2 (
 request_id TEXT PRIMARY KEY REFERENCES approval_context_v2(request_id),
 board_generation TEXT NOT NULL, parked_at REAL NOT NULL,
 unblocked_at REAL, resume_generation TEXT
);
CREATE TABLE IF NOT EXISTS approval_grants_v2 (
 request_id TEXT PRIMARY KEY REFERENCES approval_context_v2(request_id),
 grant_id TEXT UNIQUE NOT NULL, token_version INTEGER NOT NULL CHECK(token_version=1),
 token_sha256 TEXT UNIQUE NOT NULL CHECK(length(token_sha256)=64),
 issued_at REAL NOT NULL, expires_at REAL NOT NULL,
 consumed_at REAL, execution_state TEXT NOT NULL DEFAULT 'not_started'
 CHECK(execution_state IN ('not_started','unknown','completed','failed')),
 CHECK(expires_at>issued_at), CHECK(consumed_at IS NULL OR consumed_at>=issued_at)
);
CREATE TABLE IF NOT EXISTS approval_outbox_v2 (
 event_id TEXT PRIMARY KEY, request_id TEXT NOT NULL REFERENCES approval_context_v2(request_id),
 event_type TEXT NOT NULL, payload_json TEXT NOT NULL,
 created_at REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts>=0),
 next_attempt_at REAL NOT NULL, lease_until REAL,
 admitted_at REAL, acknowledged_at REAL, last_error_code TEXT,
 UNIQUE(request_id,event_type)
);
CREATE INDEX IF NOT EXISTS approval_outbox_v2_outstanding ON approval_outbox_v2(next_attempt_at)
 WHERE acknowledged_at IS NULL;
CREATE TABLE IF NOT EXISTS approval_wake_receipts_v2 (
 event_id TEXT PRIMARY KEY REFERENCES approval_outbox_v2(event_id),
 ceo_run_id TEXT NOT NULL, ceo_session_id TEXT NOT NULL,
 ceo_started_at REAL NOT NULL, card_unblocked_at REAL,
 outcome TEXT NOT NULL CHECK(outcome IN ('resumed','denied','expired','already_applied','superseded_block','grant_expired')),
 acknowledged_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS approval_push_v2 (
 request_id TEXT PRIMARY KEY REFERENCES approvals(request_id),
 claimed_at REAL NOT NULL, attempted_at REAL,
 state TEXT NOT NULL CHECK(state IN ('claimed','sent','failed','uncertain','suppressed_quiet')),
 reason_code TEXT
);
CREATE TABLE IF NOT EXISTS approval_audit_v2 (
 event_id TEXT PRIMARY KEY, request_id TEXT NOT NULL REFERENCES approvals(request_id),
 schema_version INTEGER NOT NULL CHECK(schema_version=2),
 event_type TEXT NOT NULL, occurred_at REAL NOT NULL,
 actor_principal TEXT, reason_code TEXT, redacted_payload_json TEXT NOT NULL
);
