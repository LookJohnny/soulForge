-- CreateEnum
CREATE TYPE "LanguageMode" AS ENUM ('VERBAL', 'VOCALIZED');

-- AlterTable
ALTER TABLE "characters"
  ADD COLUMN "language_mode" "LanguageMode" NOT NULL DEFAULT 'VERBAL',
  ADD COLUMN "vocalization_palette" TEXT[] DEFAULT ARRAY[]::TEXT[],
  ADD COLUMN "audio_clips" JSONB,
  ADD COLUMN "voice_clone_url" VARCHAR(500),
  ADD COLUMN "voice_clone_ref_id" VARCHAR(64);
