-- Reflection proposals generated from evidence-backed memory streams.
-- These records make relationship/private-state/rule compilation auditable:
-- every insight points back to source memory ids.

CREATE TABLE "memory_reflections" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "user_id" UUID NOT NULL,
    "character_id" UUID,
    "question" TEXT NOT NULL,
    "insight" TEXT NOT NULL,
    "evidence_refs" UUID[] DEFAULT ARRAY[]::UUID[],
    "target_layer" TEXT NOT NULL,
    "policy_action" TEXT NOT NULL DEFAULT 'pass',
    "status" TEXT NOT NULL DEFAULT 'pending_apply',
    "confidence_score" DOUBLE PRECISION NOT NULL DEFAULT 0.75,
    "sensitivity_level" "SensitivityLevel" NOT NULL DEFAULT 'LOW',
    "raw_source" JSONB NOT NULL DEFAULT '{}',
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "memory_reflections_pkey" PRIMARY KEY ("id"),
    CONSTRAINT "memory_reflections_confidence_score_check"
      CHECK ("confidence_score" >= 0.0 AND "confidence_score" <= 1.0),
    CONSTRAINT "memory_reflections_status_check"
      CHECK ("status" IN ('pending_apply', 'applied', 'rejected', 'reverted')),
    CONSTRAINT "memory_reflections_policy_action_check"
      CHECK ("policy_action" IN ('pass', 'private_only', 'discard', 'notify_guardian')),
    CONSTRAINT "memory_reflections_target_layer_check"
      CHECK ("target_layer" IN ('relationship', 'private_state', 'preference', 'rule'))
);

CREATE INDEX "memory_reflections_user_id_character_id_idx"
  ON "memory_reflections"("user_id", "character_id");
CREATE INDEX "memory_reflections_target_layer_idx" ON "memory_reflections"("target_layer");
CREATE INDEX "memory_reflections_status_idx" ON "memory_reflections"("status");
CREATE INDEX "memory_reflections_evidence_refs_idx"
  ON "memory_reflections" USING GIN ("evidence_refs");

ALTER TABLE "memory_reflections"
  ADD CONSTRAINT "memory_reflections_user_id_fkey"
  FOREIGN KEY ("user_id") REFERENCES "end_users"("id")
  ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE "memory_reflections"
  ADD CONSTRAINT "memory_reflections_character_id_fkey"
  FOREIGN KEY ("character_id") REFERENCES "characters"("id")
  ON DELETE SET NULL ON UPDATE CASCADE;
