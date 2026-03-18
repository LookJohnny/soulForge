-- Character archetype generalization + device type

CREATE TYPE "CharacterArchetype" AS ENUM ('ANIMAL', 'HUMAN', 'FANTASY', 'ABSTRACT');

-- Add archetype column (default ANIMAL for backward compat)
ALTER TABLE characters ADD COLUMN IF NOT EXISTS archetype "CharacterArchetype" NOT NULL DEFAULT 'ANIMAL';

-- Make species nullable (not needed for ABSTRACT archetype)
ALTER TABLE characters ALTER COLUMN species DROP NOT NULL;

-- Add device_type to devices
ALTER TABLE devices ADD COLUMN IF NOT EXISTS device_type VARCHAR(20) NOT NULL DEFAULT 'toy';

INSERT INTO schema_migrations (version, name) VALUES (4, '004_archetype_device_type')
ON CONFLICT (version) DO NOTHING;
