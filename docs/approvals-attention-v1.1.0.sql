-- Replaces v1.0 draft ping migration; no notification sweep or cron.
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS approval_attention (
 request_id TEXT PRIMARY KEY REFERENCES approvals(request_id),
 first_seen_at REAL
);
CREATE TABLE IF NOT EXISTS approval_pushes (
 request_id TEXT PRIMARY KEY REFERENCES approvals(request_id),
 created_at REAL NOT NULL,
 attempted_at REAL,
 sent_at REAL,
 state TEXT NOT NULL CHECK (state IN ('claimed','attempted','sent','failed','uncertain','suppressed_quiet','unconfigured')),
 CHECK (sent_at IS NULL OR attempted_at IS NOT NULL)
);
-- Existing approvals.status has no CHECK; explicit expired needs no table rebuild.
-- expires_at/expiry_reason are versioned payload facts, never silence-denial.
