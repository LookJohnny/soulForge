CREATE TABLE IF NOT EXISTS relationship_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    end_user_id UUID NOT NULL REFERENCES end_users(id),
    character_id UUID NOT NULL REFERENCES characters(id),
    event_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    choice_index SMALLINT,
    outcome TEXT,
    state_changes JSONB NOT NULL DEFAULT '{}'::jsonb,
    completed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_rel_events_user_char ON relationship_events(end_user_id, character_id, completed_at DESC);
