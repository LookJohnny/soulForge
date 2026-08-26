ALTER TABLE relationship_states
    ADD COLUMN IF NOT EXISTS trust SMALLINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS intimacy SMALLINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS comfort SMALLINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS respect SMALLINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS energy SMALLINT NOT NULL DEFAULT 100,
    ADD COLUMN IF NOT EXISTS app_mode TEXT NOT NULL DEFAULT 'dating_sim',
    ADD COLUMN IF NOT EXISTS saved_stage TEXT,
    ADD COLUMN IF NOT EXISTS total_interactions INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS first_interaction_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_interaction_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS decay_clocks JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS completed_events JSONB NOT NULL DEFAULT '[]'::jsonb;

-- Derive the new axes from the single-axis history (idempotent: only rows
-- that have never been touched by the new engine, i.e. last_interaction_at IS NULL).
UPDATE relationship_states SET
    trust    = LEAST(100, affinity / 10),
    comfort  = LEAST(100, affinity / 12),
    intimacy = LEAST(100, GREATEST(0, (affinity - 300) / 10)),
    respect  = LEAST(100, affinity / 15),
    total_interactions = GREATEST(turn_count_today, streak_days * 3),
    first_interaction_at = created_at,
    last_interaction_at  = updated_at
WHERE last_interaction_at IS NULL;

-- Old five-stage names → new names. Romance stages require events and are
-- never granted by migration.
UPDATE relationship_states SET stage = 'FRIEND'       WHERE stage = 'FAMILIAR';
