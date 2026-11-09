-- CANDIDATE additive schema; application owns auth/expiry/idempotency transactions.
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS approval_messages (
 seq INTEGER PRIMARY KEY AUTOINCREMENT,
 approval_id TEXT NOT NULL REFERENCES approvals(request_id) ON DELETE RESTRICT,
 at REAL NOT NULL,
 role TEXT NOT NULL CHECK(role IN ('operator','agent')),
 author TEXT NOT NULL CHECK(length(author)>0),
 kind TEXT NOT NULL CHECK(kind IN ('question','answer','note')),
 text TEXT NOT NULL CHECK(length(trim(text)) BETWEEN 1 AND 8000),
 CHECK((role='operator' AND kind='question') OR (role='agent' AND kind IN ('answer','note')))
);
CREATE INDEX IF NOT EXISTS approval_messages_thread ON approval_messages(approval_id,seq);
CREATE TABLE IF NOT EXISTS approval_message_context (
 message_seq INTEGER PRIMARY KEY REFERENCES approval_messages(seq) ON DELETE RESTRICT,
 approval_id TEXT NOT NULL REFERENCES approvals(request_id),
 author TEXT NOT NULL,
 client_message_id TEXT NOT NULL,
 question_seq INTEGER REFERENCES approval_messages(seq),
 supersedes_seq INTEGER REFERENCES approval_messages(seq),
 UNIQUE(approval_id,author,client_message_id)
);
CREATE TRIGGER IF NOT EXISTS approval_messages_pending BEFORE INSERT ON approval_messages
WHEN NOT EXISTS(SELECT 1 FROM approvals WHERE request_id=NEW.approval_id AND status='pending')
BEGIN SELECT RAISE(ABORT,'approval_not_pending'); END;
CREATE TRIGGER IF NOT EXISTS approval_messages_no_update BEFORE UPDATE ON approval_messages
BEGIN SELECT RAISE(ABORT,'immutable_message'); END;
CREATE TRIGGER IF NOT EXISTS approval_messages_no_delete BEFORE DELETE ON approval_messages
BEGIN SELECT RAISE(ABORT,'immutable_message'); END;
CREATE TRIGGER IF NOT EXISTS approval_message_context_no_update BEFORE UPDATE ON approval_message_context
BEGIN SELECT RAISE(ABORT,'immutable_message_context'); END;
CREATE TRIGGER IF NOT EXISTS approval_message_context_no_delete BEFORE DELETE ON approval_message_context
BEGIN SELECT RAISE(ABORT,'immutable_message_context'); END;
CREATE TRIGGER IF NOT EXISTS approval_message_context_valid BEFORE INSERT ON approval_message_context
WHEN NOT EXISTS(SELECT 1 FROM approval_messages m WHERE m.seq=NEW.message_seq AND m.approval_id=NEW.approval_id AND m.author=NEW.author)
 OR (NEW.question_seq IS NOT NULL AND NOT EXISTS(SELECT 1 FROM approval_messages q WHERE q.seq=NEW.question_seq AND q.approval_id=NEW.approval_id AND q.kind='question' AND q.seq<NEW.message_seq))
 OR EXISTS(SELECT 1 FROM approval_messages m WHERE m.seq=NEW.message_seq AND ((m.kind='question' AND NEW.question_seq IS NOT NULL) OR (m.kind='answer' AND NEW.question_seq IS NULL)))
 OR (NEW.supersedes_seq IS NOT NULL AND NOT EXISTS(SELECT 1 FROM approval_messages old JOIN approval_messages cur ON cur.seq=NEW.message_seq WHERE old.seq=NEW.supersedes_seq AND old.seq<cur.seq AND old.approval_id=cur.approval_id AND old.author=cur.author AND old.role=cur.role AND old.kind=cur.kind))
BEGIN SELECT RAISE(ABORT,'invalid_message_reference'); END;
CREATE TABLE IF NOT EXISTS approval_details_outbox (
 event_id TEXT PRIMARY KEY,
 approval_id TEXT NOT NULL REFERENCES approvals(request_id),
 question_seq INTEGER UNIQUE NOT NULL REFERENCES approval_messages(seq),
 created_at REAL NOT NULL,
 attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts>=0),
 next_attempt_at REAL NOT NULL,
 lease_until REAL, admitted_at REAL, acknowledged_at REAL, last_error_code TEXT
);
CREATE INDEX IF NOT EXISTS approval_details_outstanding ON approval_details_outbox(next_attempt_at) WHERE acknowledged_at IS NULL;
CREATE TABLE IF NOT EXISTS approval_details_receipts (
 event_id TEXT PRIMARY KEY REFERENCES approval_details_outbox(event_id),
 ceo_run_id TEXT NOT NULL, ceo_session_id TEXT NOT NULL,
 ceo_started_at REAL NOT NULL,
 outcome TEXT NOT NULL CHECK(outcome IN ('answered','unable','closed')),
 answer_seq INTEGER REFERENCES approval_messages(seq),
 acknowledged_at REAL NOT NULL,
 CHECK((outcome='answered' AND answer_seq IS NOT NULL) OR (outcome IN ('unable','closed') AND answer_seq IS NULL))
);
-- One app transaction MUST insert message+context (+outbox for questions), validate
-- server-derived expiry, references, same-question answer correction and rate limits.
-- Receipts must validate answer is same-approval answer to the outbox question.
-- Never delete messages/context to satisfy retention cleanup. No cascade.
