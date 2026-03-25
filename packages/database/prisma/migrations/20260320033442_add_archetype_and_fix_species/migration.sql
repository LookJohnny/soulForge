-- CreateEnum
CREATE TYPE "CharacterArchetype" AS ENUM ('ANIMAL', 'HUMAN', 'FANTASY', 'ABSTRACT');

-- CreateEnum
CREATE TYPE "MemoryType" AS ENUM ('TOPIC', 'PREFERENCE', 'EVENT');

-- CreateEnum
CREATE TYPE "RelationshipStage" AS ENUM ('STRANGER', 'ACQUAINTANCE', 'FAMILIAR', 'FRIEND', 'BESTFRIEND');

-- AlterTable
ALTER TABLE "characters" ADD COLUMN     "archetype" "CharacterArchetype" NOT NULL DEFAULT 'ANIMAL',
ALTER COLUMN "species" DROP NOT NULL;

-- AlterTable
ALTER TABLE "devices" ADD COLUMN     "device_secret" VARCHAR(200),
ADD COLUMN     "device_type" VARCHAR(20) NOT NULL DEFAULT 'toy';

-- AlterTable
ALTER TABLE "user_customizations" ADD COLUMN     "personality_drift" JSONB;

-- CreateTable
CREATE TABLE "conversation_memories" (
    "id" UUID NOT NULL,
    "end_user_id" UUID NOT NULL,
    "character_id" UUID NOT NULL,
    "type" "MemoryType" NOT NULL,
    "content" VARCHAR(200) NOT NULL,
    "source" TEXT,
    "session_id" VARCHAR(100),
    "confidence" DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "conversation_memories_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "relationship_states" (
    "id" UUID NOT NULL,
    "end_user_id" UUID NOT NULL,
    "character_id" UUID NOT NULL,
    "affinity" INTEGER NOT NULL DEFAULT 0,
    "stage" "RelationshipStage" NOT NULL DEFAULT 'STRANGER',
    "streak_days" INTEGER NOT NULL DEFAULT 0,
    "last_interaction_date" DATE,
    "turn_count_today" INTEGER NOT NULL DEFAULT 0,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "relationship_states_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "conversation_memories_end_user_id_character_id_idx" ON "conversation_memories"("end_user_id", "character_id");

-- CreateIndex
CREATE INDEX "conversation_memories_created_at_idx" ON "conversation_memories"("created_at");

-- CreateIndex
CREATE INDEX "relationship_states_end_user_id_idx" ON "relationship_states"("end_user_id");

-- CreateIndex
CREATE INDEX "relationship_states_character_id_idx" ON "relationship_states"("character_id");

-- CreateIndex
CREATE UNIQUE INDEX "relationship_states_end_user_id_character_id_key" ON "relationship_states"("end_user_id", "character_id");

-- AddForeignKey
ALTER TABLE "conversation_memories" ADD CONSTRAINT "conversation_memories_end_user_id_fkey" FOREIGN KEY ("end_user_id") REFERENCES "end_users"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "conversation_memories" ADD CONSTRAINT "conversation_memories_character_id_fkey" FOREIGN KEY ("character_id") REFERENCES "characters"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "relationship_states" ADD CONSTRAINT "relationship_states_end_user_id_fkey" FOREIGN KEY ("end_user_id") REFERENCES "end_users"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "relationship_states" ADD CONSTRAINT "relationship_states_character_id_fkey" FOREIGN KEY ("character_id") REFERENCES "characters"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
