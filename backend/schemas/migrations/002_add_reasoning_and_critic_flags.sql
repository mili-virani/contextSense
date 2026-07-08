-- Migration to add reasoning_summary and critic_flags to run_logs.
-- Apply with: psql "$DATABASE_URL" -f backend/schemas/migrations/002_add_reasoning_and_critic_flags.sql

ALTER TABLE run_logs ADD COLUMN IF NOT EXISTS reasoning_summary TEXT DEFAULT '';
ALTER TABLE run_logs ADD COLUMN IF NOT EXISTS critic_flags TEXT[] DEFAULT '{}';
