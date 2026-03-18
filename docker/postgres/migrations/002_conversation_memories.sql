-- Add conversation memory table for long-term character memory
-- and device_secret field for device authentication

CREATE TYPE "MemoryType" AS ENUM ('TOPIC', 'PREFERENCE', 'EVENT');

CREATE TABLE IF NOT EXISTS conversation_memories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    end_user_id UUID NOT NULL REFERENCES end_users(id),
    character_id UUID NOT NULL REFERENCES characters(id),
    type "MemoryType" NOT NULL,
    content VARCHAR(200) NOT NULL,
    source TEXT,
    session_id VARCHAR(100),
    confidence FLOAT DEFAULT 1.0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_conv_mem_user_char ON conversation_memories(end_user_id, character_id);
CREATE INDEX IF NOT EXISTS idx_conv_mem_created ON conversation_memories(created_at);

-- Add device_secret to devices table
ALTER TABLE devices ADD COLUMN IF NOT EXISTS device_secret VARCHAR(200);

INSERT INTO schema_migrations (version, name) VALUES (2, '002_conversation_memories')
ON CONFLICT (version) DO NOTHING;
