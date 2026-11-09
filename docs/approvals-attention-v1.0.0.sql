-- Additive migration specification. Do not execute against production in design phase.
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS approval_attention (
 request_id TEXT PRIMARY KEY REFERENCES approvals(request_id),
 first_seen_at REAL
);
CREATE TABLE IF NOT EXISTS approval_pings (
 request_id TEXT NOT NULL REFERENCES approvals(request_id),
 ordinal INTEGER NOT NULL CHECK (ordinal BETWEEN 1 AND 3),
 claimed_at REAL NOT NULL,
 attempted_at REAL,
 sent_at REAL,
 state TEXT NOT NULL CHECK (state IN ('claimed','attempted','sent','failed','uncertain','skipped')),
 PRIMARY KEY (request_id, ordinal),
 CHECK (sent_at IS NULL OR attempted_at IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_approval_pings_attempted ON approval_pings(attempted_at);
