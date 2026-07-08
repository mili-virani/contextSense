-- Run logs for every pipeline execution (approved and rejected).
-- Apply with: psql "$DATABASE_URL" -f backend/schemas/migrations/001_create_run_logs.sql

CREATE TABLE IF NOT EXISTS run_logs (
    id BIGSERIAL PRIMARY KEY,
    ticker VARCHAR(16) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    direction VARCHAR(16) NOT NULL CHECK (direction IN ('up', 'down', 'neutral')),
    confidence DOUBLE PRECISION NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    approved BOOLEAN NOT NULL,
    horizon_days INTEGER,
    cited_event_ids TEXT[] NOT NULL DEFAULT '{}',
    actual_outcome TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_run_logs_ticker_timestamp ON run_logs (ticker, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_run_logs_approved ON run_logs (approved);
