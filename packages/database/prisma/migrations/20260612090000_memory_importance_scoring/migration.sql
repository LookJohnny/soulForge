-- Generative Agents-inspired memory retrieval signal.
-- Importance is a 1-10 "poignancy" score used together with recency and
-- relevance during prompt-time retrieval.

ALTER TABLE "profile_memories"
  ADD COLUMN "importance_score" INTEGER NOT NULL DEFAULT 5;
ALTER TABLE "episodic_memories"
  ADD COLUMN "importance_score" INTEGER NOT NULL DEFAULT 5;
ALTER TABLE "semantic_memories"
  ADD COLUMN "importance_score" INTEGER NOT NULL DEFAULT 5;
ALTER TABLE "relational_memories"
  ADD COLUMN "importance_score" INTEGER NOT NULL DEFAULT 5;
ALTER TABLE "memory_policies"
  ADD COLUMN "importance_score" INTEGER NOT NULL DEFAULT 5;
ALTER TABLE "compiled_behavior_rules"
  ADD COLUMN "importance_score" INTEGER NOT NULL DEFAULT 5;

UPDATE "profile_memories"
SET "importance_score" = GREATEST(
  1,
  LEAST(10, ROUND(3 + ("retrieval_weight" * 3) + ("confidence_score" * 2))::INTEGER)
);

UPDATE "episodic_memories"
SET "importance_score" = GREATEST(
  1,
  LEAST(10, ROUND(2 + ("retrieval_weight" * 3) + ("confidence_score" * 2))::INTEGER)
);

UPDATE "semantic_memories"
SET "importance_score" = GREATEST(
  1,
  LEAST(10, ROUND(3 + ("retrieval_weight" * 3) + ("confidence_score" * 2))::INTEGER)
);

UPDATE "relational_memories"
SET "importance_score" = GREATEST(
  1,
  LEAST(10, ROUND(4 + ("retrieval_weight" * 3) + ("confidence_score" * 2))::INTEGER)
);

UPDATE "compiled_behavior_rules"
SET "importance_score" = GREATEST(
  1,
  LEAST(10, ROUND(4 + ("retrieval_weight" * 3) + ("confidence_score" * 2))::INTEGER)
);

UPDATE "memory_policies" policy
SET "importance_score" = source.importance_score
FROM (
  SELECT id, importance_score FROM "profile_memories"
  UNION ALL
  SELECT id, importance_score FROM "episodic_memories"
  UNION ALL
  SELECT id, importance_score FROM "semantic_memories"
  UNION ALL
  SELECT id, importance_score FROM "relational_memories"
  UNION ALL
  SELECT id, importance_score FROM "compiled_behavior_rules"
) source
WHERE policy."memory_id" = source.id;

ALTER TABLE "profile_memories"
  ADD CONSTRAINT "profile_memories_importance_score_check"
  CHECK ("importance_score" BETWEEN 1 AND 10);
ALTER TABLE "episodic_memories"
  ADD CONSTRAINT "episodic_memories_importance_score_check"
  CHECK ("importance_score" BETWEEN 1 AND 10);
ALTER TABLE "semantic_memories"
  ADD CONSTRAINT "semantic_memories_importance_score_check"
  CHECK ("importance_score" BETWEEN 1 AND 10);
ALTER TABLE "relational_memories"
  ADD CONSTRAINT "relational_memories_importance_score_check"
  CHECK ("importance_score" BETWEEN 1 AND 10);
ALTER TABLE "memory_policies"
  ADD CONSTRAINT "memory_policies_importance_score_check"
  CHECK ("importance_score" BETWEEN 1 AND 10);
ALTER TABLE "compiled_behavior_rules"
  ADD CONSTRAINT "compiled_behavior_rules_importance_score_check"
  CHECK ("importance_score" BETWEEN 1 AND 10);

CREATE INDEX "profile_memories_importance_score_idx" ON "profile_memories"("importance_score");
CREATE INDEX "episodic_memories_importance_score_idx" ON "episodic_memories"("importance_score");
CREATE INDEX "semantic_memories_importance_score_idx" ON "semantic_memories"("importance_score");
CREATE INDEX "relational_memories_importance_score_idx" ON "relational_memories"("importance_score");
CREATE INDEX "compiled_behavior_rules_importance_score_idx" ON "compiled_behavior_rules"("importance_score");
