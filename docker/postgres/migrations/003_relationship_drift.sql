-- Relationship evolution + personality drift

CREATE TYPE "RelationshipStage" AS ENUM ('STRANGER', 'ACQUAINTANCE', 'FAMILIAR', 'FRIEND', 'BESTFRIEND');

CREATE TABLE IF NOT EXISTS relationship_states (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    end_user_id UUID NOT NULL REFERENCES end_users(id),
    character_id UUID NOT NULL REFERENCES characters(id),
    affinity INTEGER NOT NULL DEFAULT 0,
    stage "RelationshipStage" NOT NULL DEFAULT 'STRANGER',
    streak_days INTEGER NOT NULL DEFAULT 0,
    last_interaction_date DATE,
    turn_count_today INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(end_user_id, character_id)
);

CREATE INDEX IF NOT EXISTS idx_rel_state_user ON relationship_states(end_user_id);
CREATE INDEX IF NOT EXISTS idx_rel_state_char ON relationship_states(character_id);

-- Add personality_drift to user_customizations
ALTER TABLE user_customizations ADD COLUMN IF NOT EXISTS personality_drift JSONB;

INSERT INTO schema_migrations (version, name) VALUES (3, '003_relationship_drift')
ON CONFLICT (version) DO NOTHING;
