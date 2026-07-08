-- Migration to add technical_features and events as JSONB to run_logs.
-- Apply with: psql "$DATABASE_URL" -f backend/schemas/migrations/003_add_indicators_and_events.sql

ALTER TABLE run_logs ADD COLUMN IF NOT EXISTS technical_features JSONB;
ALTER TABLE run_logs ADD COLUMN IF NOT EXISTS events JSONB;
