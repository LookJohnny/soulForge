-- Immutable raw event stream underneath the five-layer companion memories.
-- Derived memories and reflections can point back to these rows through
-- source_log_id / evidence_refs so memory compilation remains auditable.

CREATE TABLE "raw_event_logs" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "user_id" UUID NOT NULL,
    "character_id" UUID,
    "device_id" VARCHAR(100),
    "session_id" VARCHAR(100),
    "event_type" VARCHAR(80) NOT NULL,
    "source" VARCHAR(50) NOT NULL DEFAULT 'api',
    "content" TEXT NOT NULL,
    "payload" JSONB NOT NULL DEFAULT '{}'::jsonb,
    "context" JSONB NOT NULL DEFAULT '{}'::jsonb,
    "importance_score" INTEGER NOT NULL DEFAULT 5,
    "sensitivity_level" "SensitivityLevel" NOT NULL DEFAULT 'LOW',
    "observed_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "raw_event_logs_pkey" PRIMARY KEY ("id"),
    CONSTRAINT "raw_event_logs_importance_score_check"
      CHECK ("importance_score" BETWEEN 1 AND 10)
);

CREATE INDEX "raw_event_logs_user_id_character_id_observed_at_idx"
  ON "raw_event_logs"("user_id", "character_id", "observed_at");
CREATE INDEX "raw_event_logs_event_type_idx" ON "raw_event_logs"("event_type");
CREATE INDEX "raw_event_logs_importance_score_idx" ON "raw_event_logs"("importance_score");

ALTER TABLE "raw_event_logs"
  ADD CONSTRAINT "raw_event_logs_user_id_fkey"
  FOREIGN KEY ("user_id") REFERENCES "end_users"("id")
  ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE "raw_event_logs"
  ADD CONSTRAINT "raw_event_logs_character_id_fkey"
  FOREIGN KEY ("character_id") REFERENCES "characters"("id")
  ON DELETE SET NULL ON UPDATE CASCADE;

ALTER TABLE "raw_event_logs"
  ADD CONSTRAINT "raw_event_logs_device_id_fkey"
  FOREIGN KEY ("device_id") REFERENCES "devices"("id")
  ON DELETE SET NULL ON UPDATE CASCADE;
