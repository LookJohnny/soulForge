-- CreateEnum
CREATE TYPE "MemoryLayer" AS ENUM ('PROFILE', 'EPISODIC', 'SEMANTIC', 'RELATIONAL');

-- CreateEnum
CREATE TYPE "SensitivityLevel" AS ENUM ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL');

-- CreateEnum
CREATE TYPE "MemoryPermissionLevel" AS ENUM ('AUTO', 'CONFIRMED', 'PENDING_CONFIRMATION', 'DENIED');

-- CreateEnum
CREATE TYPE "MemoryConflictStatus" AS ENUM ('NONE', 'POTENTIAL', 'CONFIRMED_CONFLICT', 'SUPERSEDED');

-- CreateEnum
CREATE TYPE "MemoryUseMode" AS ENUM ('DIRECT_SURFACE', 'IMPLICIT_ONLY', 'REQUIRE_CONFIRMATION', 'BLOCKED');

-- CreateTable
CREATE TABLE "profile_memories" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "user_id" UUID NOT NULL,
    "character_id" UUID,
    "memory_type" "MemoryLayer" NOT NULL DEFAULT 'PROFILE',
    "key" TEXT NOT NULL,
    "content" TEXT NOT NULL,
    "raw_source" JSONB NOT NULL DEFAULT '{}',
    "timestamp" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "confidence_score" DOUBLE PRECISION NOT NULL DEFAULT 0.8,
    "emotional_valence" DOUBLE PRECISION,
    "sensitivity_level" "SensitivityLevel" NOT NULL DEFAULT 'LOW',
    "permission_level" "MemoryPermissionLevel" NOT NULL DEFAULT 'AUTO',
    "retrieval_weight" DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    "decay_rate" DOUBLE PRECISION NOT NULL DEFAULT 0.01,
    "last_used_at" TIMESTAMP(3),
    "usage_count" INTEGER NOT NULL DEFAULT 0,
    "update_history" JSONB NOT NULL DEFAULT '[]',
    "conflict_status" "MemoryConflictStatus" NOT NULL DEFAULT 'NONE',
    "can_surface_directly" BOOLEAN NOT NULL DEFAULT false,
    "implicit_only" BOOLEAN NOT NULL DEFAULT true,
    "requires_confirmation" BOOLEAN NOT NULL DEFAULT false,
    "frozen_at" TIMESTAMP(3),
    "deleted_at" TIMESTAMP(3),
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "profile_memories_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "episodic_memories" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "user_id" UUID NOT NULL,
    "character_id" UUID,
    "device_id" VARCHAR(100),
    "memory_type" "MemoryLayer" NOT NULL DEFAULT 'EPISODIC',
    "content" TEXT NOT NULL,
    "raw_source" JSONB NOT NULL,
    "source_log_id" UUID,
    "raw_transcript" JSONB NOT NULL DEFAULT '{}',
    "timestamp" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "context_window" JSONB NOT NULL DEFAULT '{}',
    "detected_topics" TEXT[] DEFAULT ARRAY[]::TEXT[],
    "confidence_score" DOUBLE PRECISION NOT NULL DEFAULT 0.7,
    "emotional_valence" DOUBLE PRECISION,
    "pad_snapshot" JSONB,
    "sensitivity_level" "SensitivityLevel" NOT NULL DEFAULT 'LOW',
    "permission_level" "MemoryPermissionLevel" NOT NULL DEFAULT 'AUTO',
    "retrieval_weight" DOUBLE PRECISION NOT NULL DEFAULT 0.6,
    "decay_rate" DOUBLE PRECISION NOT NULL DEFAULT 0.05,
    "last_used_at" TIMESTAMP(3),
    "usage_count" INTEGER NOT NULL DEFAULT 0,
    "update_history" JSONB NOT NULL DEFAULT '[]',
    "conflict_status" "MemoryConflictStatus" NOT NULL DEFAULT 'NONE',
    "can_surface_directly" BOOLEAN NOT NULL DEFAULT false,
    "implicit_only" BOOLEAN NOT NULL DEFAULT true,
    "requires_confirmation" BOOLEAN NOT NULL DEFAULT false,
    "frozen_at" TIMESTAMP(3),
    "deleted_at" TIMESTAMP(3),
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "episodic_memories_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "semantic_memories" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "user_id" UUID NOT NULL,
    "character_id" UUID,
    "memory_type" "MemoryLayer" NOT NULL DEFAULT 'SEMANTIC',
    "content" TEXT NOT NULL,
    "raw_source" JSONB NOT NULL DEFAULT '{}',
    "source_memory_ids" UUID[] DEFAULT ARRAY[]::UUID[],
    "timestamp" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "confidence_score" DOUBLE PRECISION NOT NULL DEFAULT 0.75,
    "evidence_count" INTEGER NOT NULL DEFAULT 0,
    "emotional_valence" DOUBLE PRECISION,
    "sensitivity_level" "SensitivityLevel" NOT NULL DEFAULT 'LOW',
    "permission_level" "MemoryPermissionLevel" NOT NULL DEFAULT 'AUTO',
    "retrieval_weight" DOUBLE PRECISION NOT NULL DEFAULT 0.9,
    "decay_rate" DOUBLE PRECISION NOT NULL DEFAULT 0.02,
    "last_used_at" TIMESTAMP(3),
    "usage_count" INTEGER NOT NULL DEFAULT 0,
    "update_history" JSONB NOT NULL DEFAULT '[]',
    "conflict_status" "MemoryConflictStatus" NOT NULL DEFAULT 'NONE',
    "can_surface_directly" BOOLEAN NOT NULL DEFAULT false,
    "implicit_only" BOOLEAN NOT NULL DEFAULT true,
    "requires_confirmation" BOOLEAN NOT NULL DEFAULT false,
    "frozen_at" TIMESTAMP(3),
    "deleted_at" TIMESTAMP(3),
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "semantic_memories_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "relational_memories" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "user_id" UUID NOT NULL,
    "character_id" UUID,
    "memory_type" "MemoryLayer" NOT NULL DEFAULT 'RELATIONAL',
    "content" TEXT NOT NULL,
    "relation_axis" TEXT NOT NULL,
    "raw_source" JSONB NOT NULL DEFAULT '{}',
    "source_memory_ids" UUID[] DEFAULT ARRAY[]::UUID[],
    "timestamp" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "confidence_score" DOUBLE PRECISION NOT NULL DEFAULT 0.8,
    "emotional_valence" DOUBLE PRECISION,
    "sensitivity_level" "SensitivityLevel" NOT NULL DEFAULT 'LOW',
    "permission_level" "MemoryPermissionLevel" NOT NULL DEFAULT 'AUTO',
    "retrieval_weight" DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    "decay_rate" DOUBLE PRECISION NOT NULL DEFAULT 0.01,
    "last_used_at" TIMESTAMP(3),
    "usage_count" INTEGER NOT NULL DEFAULT 0,
    "update_history" JSONB NOT NULL DEFAULT '[]',
    "conflict_status" "MemoryConflictStatus" NOT NULL DEFAULT 'NONE',
    "can_surface_directly" BOOLEAN NOT NULL DEFAULT false,
    "implicit_only" BOOLEAN NOT NULL DEFAULT true,
    "requires_confirmation" BOOLEAN NOT NULL DEFAULT false,
    "frozen_at" TIMESTAMP(3),
    "deleted_at" TIMESTAMP(3),
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "relational_memories_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "memory_policies" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "user_id" UUID NOT NULL,
    "memory_id" UUID NOT NULL,
    "memory_table" TEXT NOT NULL,
    "memory_type" "MemoryLayer" NOT NULL,
    "content" TEXT NOT NULL,
    "raw_source" JSONB NOT NULL DEFAULT '{}',
    "timestamp" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "confidence_score" DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    "emotional_valence" DOUBLE PRECISION,
    "sensitivity_level" "SensitivityLevel" NOT NULL DEFAULT 'LOW',
    "permission_level" "MemoryPermissionLevel" NOT NULL DEFAULT 'AUTO',
    "retrieval_weight" DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    "decay_rate" DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    "last_used_at" TIMESTAMP(3),
    "usage_count" INTEGER NOT NULL DEFAULT 0,
    "update_history" JSONB NOT NULL DEFAULT '[]',
    "conflict_status" "MemoryConflictStatus" NOT NULL DEFAULT 'NONE',
    "can_surface_directly" BOOLEAN NOT NULL DEFAULT false,
    "implicit_only" BOOLEAN NOT NULL DEFAULT true,
    "requires_confirmation" BOOLEAN NOT NULL DEFAULT false,
    "use_mode" "MemoryUseMode" NOT NULL DEFAULT 'IMPLICIT_ONLY',
    "allowed_channels" TEXT[] DEFAULT ARRAY['response_style']::TEXT[],
    "forbidden_contexts" TEXT[] DEFAULT ARRAY[]::TEXT[],
    "expires_at" TIMESTAMP(3),
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "memory_policies_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "compiled_behavior_rules" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "user_id" UUID NOT NULL,
    "character_id" UUID,
    "memory_type" TEXT NOT NULL DEFAULT 'COMPILED_BEHAVIOR_RULE',
    "rule_type" TEXT NOT NULL,
    "trigger" JSONB NOT NULL DEFAULT '{}',
    "content" TEXT NOT NULL,
    "raw_source" JSONB NOT NULL DEFAULT '{}',
    "source_memory_ids" UUID[] DEFAULT ARRAY[]::UUID[],
    "timestamp" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "confidence_score" DOUBLE PRECISION NOT NULL DEFAULT 0.8,
    "emotional_valence" DOUBLE PRECISION,
    "sensitivity_level" "SensitivityLevel" NOT NULL DEFAULT 'LOW',
    "permission_level" "MemoryPermissionLevel" NOT NULL DEFAULT 'AUTO',
    "retrieval_weight" DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    "decay_rate" DOUBLE PRECISION NOT NULL DEFAULT 0.01,
    "last_used_at" TIMESTAMP(3),
    "usage_count" INTEGER NOT NULL DEFAULT 0,
    "update_history" JSONB NOT NULL DEFAULT '[]',
    "conflict_status" "MemoryConflictStatus" NOT NULL DEFAULT 'NONE',
    "can_surface_directly" BOOLEAN NOT NULL DEFAULT false,
    "implicit_only" BOOLEAN NOT NULL DEFAULT true,
    "requires_confirmation" BOOLEAN NOT NULL DEFAULT false,
    "version" INTEGER NOT NULL DEFAULT 1,
    "enabled" BOOLEAN NOT NULL DEFAULT true,
    "rollback_of" UUID,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "compiled_behavior_rules_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "memory_usage_logs" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "response_id" VARCHAR(100),
    "user_id" UUID NOT NULL,
    "character_id" UUID,
    "memory_id" UUID NOT NULL,
    "memory_table" TEXT NOT NULL,
    "use_mode" "MemoryUseMode" NOT NULL,
    "channel" TEXT NOT NULL,
    "prompt_tokens" INTEGER,
    "surfaced_text" TEXT,
    "policy_reason" TEXT,
    "user_feedback" TEXT,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "memory_usage_logs_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "memory_pending_confirmations" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "user_id" UUID NOT NULL,
    "character_id" UUID,
    "proposed_memory" JSONB NOT NULL,
    "reason" TEXT NOT NULL,
    "expires_at" TIMESTAMP(3) NOT NULL,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "memory_pending_confirmations_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "profile_memories_user_id_character_id_key_key" ON "profile_memories"("user_id", "character_id", "key");
CREATE INDEX "profile_memories_user_id_character_id_idx" ON "profile_memories"("user_id", "character_id");
CREATE INDEX "profile_memories_deleted_at_idx" ON "profile_memories"("deleted_at");

CREATE INDEX "episodic_memories_user_id_character_id_idx" ON "episodic_memories"("user_id", "character_id");
CREATE INDEX "episodic_memories_created_at_idx" ON "episodic_memories"("created_at");
CREATE INDEX "episodic_memories_deleted_at_idx" ON "episodic_memories"("deleted_at");

CREATE INDEX "semantic_memories_user_id_character_id_idx" ON "semantic_memories"("user_id", "character_id");
CREATE INDEX "semantic_memories_deleted_at_idx" ON "semantic_memories"("deleted_at");

CREATE INDEX "relational_memories_user_id_character_id_idx" ON "relational_memories"("user_id", "character_id");
CREATE INDEX "relational_memories_relation_axis_idx" ON "relational_memories"("relation_axis");
CREATE INDEX "relational_memories_deleted_at_idx" ON "relational_memories"("deleted_at");

CREATE INDEX "memory_policies_user_id_memory_id_idx" ON "memory_policies"("user_id", "memory_id");
CREATE INDEX "memory_policies_use_mode_idx" ON "memory_policies"("use_mode");

CREATE INDEX "compiled_behavior_rules_user_id_character_id_idx" ON "compiled_behavior_rules"("user_id", "character_id");
CREATE INDEX "compiled_behavior_rules_rule_type_idx" ON "compiled_behavior_rules"("rule_type");
CREATE INDEX "compiled_behavior_rules_enabled_idx" ON "compiled_behavior_rules"("enabled");
CREATE INDEX "compiled_behavior_rules_trigger_idx" ON "compiled_behavior_rules" USING GIN ("trigger");

CREATE INDEX "memory_usage_logs_response_id_idx" ON "memory_usage_logs"("response_id");
CREATE INDEX "memory_usage_logs_user_id_character_id_idx" ON "memory_usage_logs"("user_id", "character_id");
CREATE INDEX "memory_usage_logs_memory_id_idx" ON "memory_usage_logs"("memory_id");

CREATE INDEX "memory_pending_confirmations_user_id_character_id_idx" ON "memory_pending_confirmations"("user_id", "character_id");
CREATE INDEX "memory_pending_confirmations_expires_at_idx" ON "memory_pending_confirmations"("expires_at");

-- AddForeignKey
ALTER TABLE "profile_memories" ADD CONSTRAINT "profile_memories_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "end_users"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
ALTER TABLE "profile_memories" ADD CONSTRAINT "profile_memories_character_id_fkey" FOREIGN KEY ("character_id") REFERENCES "characters"("id") ON DELETE SET NULL ON UPDATE CASCADE;

ALTER TABLE "episodic_memories" ADD CONSTRAINT "episodic_memories_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "end_users"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
ALTER TABLE "episodic_memories" ADD CONSTRAINT "episodic_memories_character_id_fkey" FOREIGN KEY ("character_id") REFERENCES "characters"("id") ON DELETE SET NULL ON UPDATE CASCADE;
ALTER TABLE "episodic_memories" ADD CONSTRAINT "episodic_memories_device_id_fkey" FOREIGN KEY ("device_id") REFERENCES "devices"("id") ON DELETE SET NULL ON UPDATE CASCADE;

ALTER TABLE "semantic_memories" ADD CONSTRAINT "semantic_memories_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "end_users"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
ALTER TABLE "semantic_memories" ADD CONSTRAINT "semantic_memories_character_id_fkey" FOREIGN KEY ("character_id") REFERENCES "characters"("id") ON DELETE SET NULL ON UPDATE CASCADE;

ALTER TABLE "relational_memories" ADD CONSTRAINT "relational_memories_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "end_users"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
ALTER TABLE "relational_memories" ADD CONSTRAINT "relational_memories_character_id_fkey" FOREIGN KEY ("character_id") REFERENCES "characters"("id") ON DELETE SET NULL ON UPDATE CASCADE;

ALTER TABLE "memory_policies" ADD CONSTRAINT "memory_policies_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "end_users"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE "compiled_behavior_rules" ADD CONSTRAINT "compiled_behavior_rules_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "end_users"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
ALTER TABLE "compiled_behavior_rules" ADD CONSTRAINT "compiled_behavior_rules_character_id_fkey" FOREIGN KEY ("character_id") REFERENCES "characters"("id") ON DELETE SET NULL ON UPDATE CASCADE;

ALTER TABLE "memory_usage_logs" ADD CONSTRAINT "memory_usage_logs_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "end_users"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
ALTER TABLE "memory_usage_logs" ADD CONSTRAINT "memory_usage_logs_character_id_fkey" FOREIGN KEY ("character_id") REFERENCES "characters"("id") ON DELETE SET NULL ON UPDATE CASCADE;

ALTER TABLE "memory_pending_confirmations" ADD CONSTRAINT "memory_pending_confirmations_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "end_users"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
ALTER TABLE "memory_pending_confirmations" ADD CONSTRAINT "memory_pending_confirmations_character_id_fkey" FOREIGN KEY ("character_id") REFERENCES "characters"("id") ON DELETE SET NULL ON UPDATE CASCADE;
