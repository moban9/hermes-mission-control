-- DESIGN DDL v1.3.0; not an installed migration. Execute only in isolated fixture.
-- Status vocabulary: approvals-ux-v1.3.0-amendment.md#status-vocabulary
-- Redaction boundary: scrub all strings before INSERT, including snapshots and audit.
-- New names avoid silently altering historical tables. Import protocol is in amendment.
PRAGMA foreign_keys = ON;
CREATE TABLE approval_history_v13 (
 seq INTEGER PRIMARY KEY AUTOINCREMENT,
 captured_at REAL NOT NULL CHECK(captured_at >= 0 AND captured_at <= 1.7976931348623157e308),
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
CREATE INDEX approval_history_v13_request ON approval_history_v13(request_id,seq);
CREATE TRIGGER approval_history_v13_no_update BEFORE UPDATE ON approval_history_v13
 BEGIN SELECT RAISE(ABORT,'immutable attention ledger: UPDATE forbidden'); END;
CREATE TRIGGER approval_history_v13_no_delete BEFORE DELETE ON approval_history_v13
 BEGIN SELECT RAISE(ABORT,'immutable attention ledger: DELETE forbidden'); END;
CREATE VIEW approval_current_v13 AS
 SELECT h.* FROM approval_history_v13 h
 WHERE h.event_name='approval' AND NOT EXISTS
 (SELECT 1 FROM approval_history_v13 n WHERE n.request_id=h.request_id AND n.seq>h.seq);
CREATE TRIGGER approval_history_v13_guard BEFORE INSERT ON approval_history_v13
 WHEN NEW.event_name='approval'
 BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM approval_current_v13 WHERE request_id=NEW.request_id)
   AND NEW.status <> 'pending' THEN RAISE(ABORT,'first approval event must be pending') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM approval_current_v13 WHERE request_id=NEW.request_id
   AND status <> 'pending' AND status <> NEW.status)
   THEN RAISE(ABORT,'terminal status cannot change') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM approval_current_v13 WHERE request_id=NEW.request_id
   AND (json_extract(approval_json,'$.requested_at') IS NOT json_extract(NEW.approval_json,'$.requested_at')
   OR json_extract(approval_json,'$.expires_at') IS NOT json_extract(NEW.approval_json,'$.expires_at')))
   THEN RAISE(ABORT,'creation and deadline immutable') END;
 END;
-- Immutable creation claim reserves the sole dispatch closure, not proof of attempt.
-- Attempt is separately committed BEFORE I/O; crashes stay unknown until request-local
-- no-send reconciliation records the documented failure. Never retry or sweep.
CREATE TABLE approval_push_claims_v13 (
 request_id TEXT PRIMARY KEY,
 claimed_at REAL NOT NULL CHECK(claimed_at >= 0),
 creation_seq INTEGER UNIQUE NOT NULL REFERENCES approval_history_v13(seq)
);
CREATE TRIGGER approval_push_claims_v13_no_update BEFORE UPDATE ON approval_push_claims_v13
 BEGIN SELECT RAISE(ABORT,'push claim immutable'); END;
CREATE TRIGGER approval_push_claims_v13_no_delete BEFORE DELETE ON approval_push_claims_v13
 BEGIN SELECT RAISE(ABORT,'push claim immutable'); END;
CREATE TABLE approval_numeric_aliases_v13 (
 numeric_id INTEGER NOT NULL CHECK(numeric_id >= 0),
 request_id TEXT NOT NULL,
 PRIMARY KEY(numeric_id,request_id)
);
CREATE TRIGGER approval_numeric_aliases_v13_no_update BEFORE UPDATE ON approval_numeric_aliases_v13
 BEGIN SELECT RAISE(ABORT,'alias immutable'); END;
CREATE TRIGGER approval_numeric_aliases_v13_no_delete BEFORE DELETE ON approval_numeric_aliases_v13
 BEGIN SELECT RAISE(ABORT,'alias immutable'); END;
-- Audit fields are explicit columns below as well as canonical approval_json.notification.
-- Closed-schema semantic validation is mandatory through the fail-closed write hook;
-- DB triggers additionally enforce lifecycle, immutability and snapshot correspondence.
-- DB role has no direct projection writes: current state is a VIEW, replay is ledger seq.
-- Full state_json is bounded ApprovalState without row-owned seq/captured_at.
-- It is NOT the paginated GET /v1/approvals response. See v1.3 Read contracts.

-- The mandatory per-connection mc_approval_safe_json function validates closed schema,
-- finite types and canonical shared redaction safety on every JSON/key/identity.
-- It returns integer 1 ONLY for a complete safe artifact, otherwise 0 or raises.
-- Missing registration aborts INSERT (no such function), never a bypass.
CREATE TRIGGER approval_history_v13_safe BEFORE INSERT ON approval_history_v13 BEGIN
 SELECT CASE WHEN length(CAST(NEW.state_json AS BLOB))>1700000
 OR length(CAST(NEW.approval_json AS BLOB))>8192
 OR length(CAST(NEW.activity_json AS BLOB))>2048
 OR length(CAST(NEW.event_id AS BLOB))>128
 THEN RAISE(ABORT,'contract byte bound exceeded') END;
 SELECT CASE WHEN mc_approval_safe_json(NEW.state_json, 'state') IS NOT 1
   OR (NEW.approval_json IS NOT NULL AND mc_approval_safe_json(NEW.approval_json,'approval') IS NOT 1)
   OR (NEW.activity_json IS NOT NULL AND mc_approval_safe_json(NEW.activity_json,'activity') IS NOT 1)
   OR mc_approval_safe_json(NEW.event_id,'identity') IS NOT 1
 THEN RAISE(ABORT,'unsafe or invalid contract artifact') END;
 SELECT CASE WHEN NEW.captured_at < COALESCE((SELECT MAX(captured_at) FROM approval_history_v13),0)
 THEN RAISE(ABORT,'capture clock regression') END;
END;
CREATE TRIGGER approval_history_v13_terminal BEFORE INSERT ON approval_history_v13
 WHEN NEW.event_name='approval' BEGIN
 SELECT CASE WHEN EXISTS (
 SELECT 1 FROM approval_current_v13 old WHERE old.request_id=NEW.request_id AND old.status <> 'pending'
 AND (EXISTS(SELECT fullkey,type,atom FROM json_tree(json_remove(old.approval_json,'$.first_seen_at','$.notification'))
 EXCEPT SELECT fullkey,type,atom FROM json_tree(json_remove(NEW.approval_json,'$.first_seen_at','$.notification')))
 OR EXISTS(SELECT fullkey,type,atom FROM json_tree(json_remove(NEW.approval_json,'$.first_seen_at','$.notification'))
 EXCEPT SELECT fullkey,type,atom FROM json_tree(json_remove(old.approval_json,'$.first_seen_at','$.notification')))))
 THEN RAISE(ABORT,'terminal fields immutable') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM approval_current_v13 old WHERE old.request_id=NEW.request_id
 AND old.status<>'pending'
 AND NOT EXISTS(SELECT fullkey,type,atom FROM json_tree(old.approval_json)
 EXCEPT SELECT fullkey,type,atom FROM json_tree(NEW.approval_json))
 AND NOT EXISTS(SELECT fullkey,type,atom FROM json_tree(NEW.approval_json)
 EXCEPT SELECT fullkey,type,atom FROM json_tree(old.approval_json)))
 THEN RAISE(ABORT,'duplicate terminal event forbidden') END;
 SELECT CASE WHEN NEW.status='cancelled'
 AND EXISTS(SELECT 1 FROM approval_current_v13 old WHERE old.request_id=NEW.request_id AND old.status='pending')
 AND json_extract(NEW.approval_json,'$.terminal_at') IS NOT NEW.captured_at
 THEN RAISE(ABORT,'cancellation time must equal first commit capture') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM approval_current_v13 old WHERE old.request_id=NEW.request_id
 AND json_extract(old.approval_json,'$.first_seen_at') IS NOT NULL
 AND json_extract(old.approval_json,'$.first_seen_at') IS NOT json_extract(NEW.approval_json,'$.first_seen_at'))
 THEN RAISE(ABORT,'first seen immutable') END;
 SELECT CASE WHEN json_extract(NEW.approval_json,'$.status')='pending'
 AND (json_extract(NEW.approval_json,'$.terminal_at') IS NOT NULL
 OR json_extract(NEW.approval_json,'$.terminal_reason') IS NOT NULL)
 THEN RAISE(ABORT,'pending terminal fields invalid') END;
 SELECT CASE WHEN NEW.status <> 'pending' AND
 (json_type(NEW.approval_json,'$.terminal_at') NOT IN ('integer','real')
 OR json_extract(NEW.approval_json,'$.terminal_at') IS NULL
 OR json_extract(NEW.approval_json,'$.terminal_at') > NEW.captured_at
 OR json_extract(NEW.approval_json,'$.terminal_at') < json_extract(NEW.approval_json,'$.requested_at'))
 THEN RAISE(ABORT,'terminal time invalid') END;
 SELECT CASE WHEN NEW.status IN ('approved','denied') AND
 (json_extract(NEW.approval_json,'$.decided_at') IS NOT json_extract(NEW.approval_json,'$.terminal_at')
 OR COALESCE(length(json_extract(NEW.approval_json,'$.decided_by')),0)=0)
 THEN RAISE(ABORT,'decision metadata invalid') END;
 SELECT CASE WHEN NEW.status IN ('pending','cancelled','expired') AND
 (json_extract(NEW.approval_json,'$.decided_at') IS NOT NULL OR json_extract(NEW.approval_json,'$.decided_by') IS NOT NULL)
 THEN RAISE(ABORT,'nondecision metadata invalid') END;
 SELECT CASE WHEN NEW.status='expired' AND json_extract(NEW.approval_json,'$.terminal_at') IS NOT json_extract(NEW.approval_json,'$.expires_at')
 THEN RAISE(ABORT,'expiry time invalid') END;
END;
-- One immutable row per distinct audit stage, generated from committed full events.
CREATE TABLE approval_notification_audit_v13 (
 history_seq INTEGER PRIMARY KEY REFERENCES approval_history_v13(seq),
 request_id TEXT NOT NULL,
 claimed_at REAL NOT NULL CHECK(claimed_at>=0),
 attempted_at REAL CHECK(attempted_at>=claimed_at),
 suppression_reason TEXT CHECK(suppression_reason IN ('quiet_hours','unconfigured','already_terminal')),
 delivery_outcome TEXT CHECK(delivery_outcome IN ('sent','failed')),
 failure_reason TEXT CHECK(failure_reason IN ('transport_error','timeout','uncertain_delivery','crash_before_attempt')),
 CHECK(suppression_reason IS NULL OR (attempted_at IS NULL AND delivery_outcome IS NULL AND failure_reason IS NULL)),
 CHECK(delivery_outcome IS NOT 'sent' OR (attempted_at IS NOT NULL AND failure_reason IS NULL)),
 CHECK(delivery_outcome IS NOT 'failed' OR
 ((attempted_at IS NULL AND failure_reason IS 'crash_before_attempt') OR
 (attempted_at IS NOT NULL AND COALESCE(failure_reason IN ('transport_error','timeout','uncertain_delivery'),0)))),
 CHECK(delivery_outcome IS NOT NULL OR failure_reason IS NULL)
);
CREATE TRIGGER approval_notification_audit_v13_update BEFORE UPDATE ON approval_notification_audit_v13
 BEGIN SELECT RAISE(ABORT,'notification audit immutable'); END;
CREATE TRIGGER approval_notification_audit_v13_delete BEFORE DELETE ON approval_notification_audit_v13
 BEGIN SELECT RAISE(ABORT,'notification audit immutable'); END;
CREATE TRIGGER approval_notification_audit_v13_guard BEFORE INSERT ON approval_notification_audit_v13 BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM approval_notification_audit_v13 WHERE request_id=NEW.request_id)
 AND (NEW.attempted_at IS NOT NULL OR NEW.suppression_reason IS NOT NULL OR NEW.delivery_outcome IS NOT NULL OR NEW.failure_reason IS NOT NULL)
 THEN RAISE(ABORT,'notification first stage must be claim') END;
 SELECT CASE WHEN NEW.attempted_at IS NOT NULL
 AND NOT EXISTS(SELECT 1 FROM approval_notification_audit_v13 WHERE request_id=NEW.request_id AND attempted_at IS NOT NULL)
 AND EXISTS(SELECT 1 FROM approval_current_v13 WHERE request_id=NEW.request_id AND status<>'pending')
 THEN RAISE(ABORT,'no new notification attempt after terminal') END;
 SELECT CASE WHEN NEW.delivery_outcome='sent'
 AND NOT EXISTS(SELECT 1 FROM approval_notification_audit_v13 WHERE request_id=NEW.request_id AND attempted_at IS NOT NULL AND delivery_outcome IS NULL)
 THEN RAISE(ABORT,'sent requires prior committed attempt') END;
 SELECT CASE WHEN NEW.delivery_outcome='failed' AND NEW.attempted_at IS NOT NULL
 AND NOT EXISTS(SELECT 1 FROM approval_notification_audit_v13 WHERE request_id=NEW.request_id AND attempted_at IS NOT NULL AND delivery_outcome IS NULL)
 THEN RAISE(ABORT,'failed attempt requires prior committed attempt') END;
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM approval_history_v13 h WHERE h.seq=NEW.history_seq
 AND h.request_id IS NEW.request_id AND h.event_name='approval'
 AND json_extract(h.approval_json,'$.notification.claimed_at') IS NEW.claimed_at
 AND json_extract(h.approval_json,'$.notification.attempted_at') IS NEW.attempted_at
 AND json_extract(h.approval_json,'$.notification.suppression_reason') IS NEW.suppression_reason
 AND json_extract(h.approval_json,'$.notification.delivery_outcome') IS NEW.delivery_outcome
 AND json_extract(h.approval_json,'$.notification.failure_reason') IS NEW.failure_reason)
 THEN RAISE(ABORT,'audit must match source event') END;
 SELECT CASE WHEN EXISTS(SELECT 1 FROM approval_notification_audit_v13 old WHERE old.request_id=NEW.request_id AND
 (old.suppression_reason IS NOT NULL OR old.delivery_outcome IS NOT NULL
 OR old.claimed_at IS NOT NEW.claimed_at
 OR (old.attempted_at IS NOT NULL AND old.attempted_at IS NOT NEW.attempted_at)))
 THEN RAISE(ABORT,'notification terminal or attempt immutable') END;
END;
CREATE TRIGGER approval_history_v13_notification AFTER INSERT ON approval_history_v13
 WHEN NEW.event_name='approval' AND NOT EXISTS(
 SELECT 1 FROM approval_history_v13 old WHERE old.request_id=NEW.request_id AND old.seq<NEW.seq
 AND json_extract(old.approval_json,'$.notification') IS json_extract(NEW.approval_json,'$.notification')
 AND old.seq=(SELECT MAX(seq) FROM approval_history_v13 p WHERE p.request_id=NEW.request_id AND p.seq<NEW.seq))
 BEGIN
 INSERT INTO approval_notification_audit_v13 SELECT NEW.seq,NEW.request_id,
 json_extract(NEW.approval_json,'$.notification.claimed_at'),json_extract(NEW.approval_json,'$.notification.attempted_at'),
 json_extract(NEW.approval_json,'$.notification.suppression_reason'),json_extract(NEW.approval_json,'$.notification.delivery_outcome'),
 json_extract(NEW.approval_json,'$.notification.failure_reason');
 END;
CREATE TRIGGER approval_history_v13_creation_claim AFTER INSERT ON approval_history_v13
 WHEN NEW.event_name='approval' AND NOT EXISTS(SELECT 1 FROM approval_history_v13 old
 WHERE old.request_id=NEW.request_id AND old.seq<NEW.seq)
 BEGIN INSERT INTO approval_push_claims_v13(request_id,claimed_at,creation_seq)
 VALUES(NEW.request_id,json_extract(NEW.approval_json,'$.notification.claimed_at'),NEW.seq); END;
CREATE TRIGGER approval_push_claims_v13_guard BEFORE INSERT ON approval_push_claims_v13 BEGIN
 SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM approval_history_v13 h WHERE h.seq=NEW.creation_seq
 AND h.request_id IS NEW.request_id AND h.status='pending'
 AND json_extract(h.approval_json,'$.notification.claimed_at') IS NEW.claimed_at
 AND NOT EXISTS(SELECT 1 FROM approval_history_v13 p WHERE p.request_id=h.request_id AND p.seq<h.seq))
 THEN RAISE(ABORT,'claim must reference first creation') END;
END;
CREATE VIEW approval_snapshot_v13 AS SELECT json_object(
 'approvals',json((SELECT json_group_array(json(approval_json)) FROM
 (SELECT approval_json FROM approval_current_v13 WHERE status='pending'
 ORDER BY json_extract(approval_json,'$.requested_at'),request_id LIMIT 100))),
 'approval_history',json((SELECT json_group_array(json(approval_json)) FROM
 (SELECT approval_json FROM approval_current_v13 WHERE status<>'pending'
 ORDER BY json_extract(approval_json,'$.terminal_at') DESC,request_id LIMIT 100))),
 'pending_truncated',json(CASE WHEN (SELECT COUNT(*) FROM approval_current_v13 WHERE status='pending')>100 THEN 'true' ELSE 'false' END)
 ) AS state_json;
CREATE TRIGGER approval_history_v13_snapshot AFTER INSERT ON approval_history_v13 BEGIN
 SELECT CASE WHEN EXISTS(SELECT fullkey,type,atom FROM json_tree(NEW.state_json)
 EXCEPT SELECT fullkey,type,atom FROM json_tree((SELECT state_json FROM approval_snapshot_v13)))
 OR EXISTS(SELECT fullkey,type,atom FROM json_tree((SELECT state_json FROM approval_snapshot_v13))
 EXCEPT SELECT fullkey,type,atom FROM json_tree(NEW.state_json))
 THEN RAISE(ABORT,'snapshot disagrees with canonical current state') END;
END;
