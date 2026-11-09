-- DESIGN DDL v1.2.0; not an installed migration. Execute only in isolated fixture.
-- Status vocabulary: approvals-ux-v1.2.0-amendment.md#status-vocabulary
-- Redaction boundary: scrub all strings before INSERT, including snapshots and audit.
-- New names avoid silently altering historical tables. Import protocol is in amendment.
PRAGMA foreign_keys = ON;
CREATE TABLE approval_history_v12 (
 seq INTEGER PRIMARY KEY AUTOINCREMENT,
 captured_at REAL NOT NULL CHECK(captured_at >= 0),
 event_name TEXT NOT NULL CHECK(event_name IN ('snapshot','activity','approval')),
 event_id TEXT UNIQUE NOT NULL,
 request_id TEXT,
 status TEXT CHECK(status IN ('pending','approved','denied','cancelled','expired')),
 approval_json TEXT CHECK(approval_json IS NULL OR json_valid(approval_json)),
 activity_json TEXT CHECK(activity_json IS NULL OR json_valid(activity_json)),
 state_json TEXT NOT NULL CHECK(json_valid(state_json)),
 CHECK((event_name = 'approval' AND request_id IS NOT NULL AND status IS NOT NULL AND approval_json IS NOT NULL)
    OR (event_name <> 'approval' AND request_id IS NULL AND status IS NULL AND approval_json IS NULL)),
 CHECK(event_name <> 'activity' OR activity_json IS NOT NULL),
 CHECK(approval_json IS NULL OR (json_extract(approval_json,'$.request_id') IS request_id
    AND json_extract(approval_json,'$.status') IS status)),
 CHECK(approval_json IS NULL OR (json_extract(approval_json,'$.expires_at') IS NOT NULL
    AND json_extract(approval_json,'$.requested_at') IS NOT NULL
    AND json_extract(approval_json,'$.expires_at') = json_extract(approval_json,'$.requested_at') + 604800)),
 CHECK(status IS NOT 'expired' OR json_extract(approval_json,'$.expiry_reason') IS 'Approval expired after 7 days without a decision.'),
 CHECK(status IS NOT 'cancelled' OR COALESCE(json_extract(approval_json,'$.terminal_reason') IN ('requester_withdrew','worker_died'),0))
);
CREATE INDEX approval_history_v12_request ON approval_history_v12(request_id,seq);
CREATE TRIGGER approval_history_v12_no_update BEFORE UPDATE ON approval_history_v12
 BEGIN SELECT RAISE(ABORT,'immutable attention ledger: UPDATE forbidden'); END;
CREATE TRIGGER approval_history_v12_no_delete BEFORE DELETE ON approval_history_v12
 BEGIN SELECT RAISE(ABORT,'immutable attention ledger: DELETE forbidden'); END;
CREATE VIEW approval_current_v12 AS
 SELECT h.* FROM approval_history_v12 h
 WHERE h.event_name='approval' AND NOT EXISTS
 (SELECT 1 FROM approval_history_v12 n WHERE n.request_id=h.request_id AND n.seq>h.seq);
CREATE TRIGGER approval_history_v12_guard BEFORE INSERT ON approval_history_v12
 WHEN NEW.event_name='approval'
 BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM approval_current_v12 WHERE request_id=NEW.request_id)
   AND NEW.status <> 'pending' THEN RAISE(ABORT,'first approval event must be pending') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM approval_current_v12 WHERE request_id=NEW.request_id
   AND status <> 'pending' AND status <> NEW.status)
   THEN RAISE(ABORT,'terminal status cannot change') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM approval_current_v12 WHERE request_id=NEW.request_id
   AND (json_extract(approval_json,'$.requested_at') IS NOT json_extract(NEW.approval_json,'$.requested_at')
   OR json_extract(approval_json,'$.expires_at') IS NOT json_extract(NEW.approval_json,'$.expires_at')))
   THEN RAISE(ABORT,'creation and deadline immutable') END;
 END;
-- Immutable claim consumes the only attempt BEFORE I/O. Separate result event updates
-- the projection, not this row. Crash after claim means no retry and delivery failed.
CREATE TABLE approval_push_claims_v12 (
 request_id TEXT PRIMARY KEY,
 claimed_at REAL NOT NULL CHECK(claimed_at >= 0),
 creation_seq INTEGER UNIQUE NOT NULL REFERENCES approval_history_v12(seq)
);
CREATE TRIGGER approval_push_claims_v12_no_update BEFORE UPDATE ON approval_push_claims_v12
 BEGIN SELECT RAISE(ABORT,'push claim immutable'); END;
CREATE TRIGGER approval_push_claims_v12_no_delete BEFORE DELETE ON approval_push_claims_v12
 BEGIN SELECT RAISE(ABORT,'push claim immutable'); END;
CREATE TABLE approval_numeric_aliases_v12 (
 numeric_id INTEGER NOT NULL CHECK(numeric_id >= 0),
 request_id TEXT NOT NULL,
 PRIMARY KEY(numeric_id,request_id)
);
CREATE TRIGGER approval_numeric_aliases_v12_no_update BEFORE UPDATE ON approval_numeric_aliases_v12
 BEGIN SELECT RAISE(ABORT,'alias immutable'); END;
CREATE TRIGGER approval_numeric_aliases_v12_no_delete BEFORE DELETE ON approval_numeric_aliases_v12
 BEGIN SELECT RAISE(ABORT,'alias immutable'); END;
-- Notification audit fields live in each canonical approval_json.notification:
-- suppression_reason: null | quiet_hours | unconfigured; delivery_outcome: null | sent | failed.
-- At insertion, require full presentation schema validation and additional state-machine
-- validation in the write adapter; SQLite constraints do NOT certify semantic redaction.
-- DB role has no direct projection writes: current state is a VIEW, replay is ledger seq.
-- Full state_json is the stored GET approval_state at this seq. seq/captured_at metadata
-- are injected from the row on read, never accepted from clients.
