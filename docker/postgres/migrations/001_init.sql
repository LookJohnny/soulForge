-- SoulForge Database Initialization
-- This migration creates the base schema for ai-core services.
-- For the main schema (brands, users, characters, etc.), see packages/database/prisma/schema.prisma.
-- This file handles tables not managed by Prisma or needed for ai-core-specific features.

-- Usage records (if not already created by Prisma)
CREATE TABLE IF NOT EXISTS usage_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    brand_id UUID NOT NULL,
    type VARCHAR(20) NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    date DATE NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(brand_id, type, date)
);

CREATE INDEX IF NOT EXISTS idx_usage_records_brand_date ON usage_records(brand_id, date);

-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO schema_migrations (version, name) VALUES (1, '001_init')
ON CONFLICT (version) DO NOTHING;
