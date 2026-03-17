-- CreateEnum
CREATE TYPE "CharacterStatus" AS ENUM ('DRAFT', 'PUBLISHED', 'ARCHIVED');

-- CreateEnum
CREATE TYPE "ResponseLength" AS ENUM ('SHORT', 'MEDIUM', 'LONG');

-- CreateEnum
CREATE TYPE "DeviceStatus" AS ENUM ('ACTIVE', 'OFFLINE', 'MAINTENANCE');

-- CreateTable
CREATE TABLE "brands" (
    "id" UUID NOT NULL,
    "name" VARCHAR(100) NOT NULL,
    "slug" VARCHAR(50) NOT NULL,
    "logo" VARCHAR(200),
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "brands_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "users" (
    "id" UUID NOT NULL,
    "brand_id" UUID NOT NULL,
    "email" VARCHAR(200) NOT NULL,
    "name" VARCHAR(100) NOT NULL,
    "hashed_password" VARCHAR(200) NOT NULL,
    "role" VARCHAR(20) NOT NULL DEFAULT 'designer',
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "users_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "end_users" (
    "id" UUID NOT NULL,
    "open_id" VARCHAR(100),
    "union_id" VARCHAR(100),
    "nickname" VARCHAR(50),
    "avatar" VARCHAR(200),
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "end_users_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "characters" (
    "id" UUID NOT NULL,
    "brand_id" UUID NOT NULL,
    "name" VARCHAR(50) NOT NULL,
    "species" VARCHAR(30) NOT NULL,
    "age_setting" INTEGER,
    "backstory" TEXT,
    "relationship" VARCHAR(20),
    "personality" JSONB NOT NULL DEFAULT '{}',
    "catchphrases" TEXT[] DEFAULT ARRAY[]::TEXT[],
    "suffix" VARCHAR(20),
    "topics" TEXT[] DEFAULT ARRAY[]::TEXT[],
    "forbidden" TEXT[] DEFAULT ARRAY[]::TEXT[],
    "response_length" "ResponseLength" NOT NULL DEFAULT 'SHORT',
    "voice_id" UUID,
    "voice_speed" DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    "emotion_config" JSONB,
    "avatar" VARCHAR(200),
    "status" "CharacterStatus" NOT NULL DEFAULT 'DRAFT',
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "characters_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "voice_profiles" (
    "id" UUID NOT NULL,
    "name" VARCHAR(50) NOT NULL,
    "reference_audio" VARCHAR(200) NOT NULL,
    "description" TEXT,
    "tags" TEXT[] DEFAULT ARRAY[]::TEXT[],
    "dashscope_voice_id" VARCHAR(100),
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "voice_profiles_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "user_customizations" (
    "id" UUID NOT NULL,
    "end_user_id" UUID NOT NULL,
    "character_id" UUID NOT NULL,
    "device_id" VARCHAR(100),
    "nickname" VARCHAR(30),
    "user_title" VARCHAR(20),
    "personality_offsets" JSONB,
    "interest_topics" TEXT[] DEFAULT ARRAY[]::TEXT[],
    "is_active" BOOLEAN NOT NULL DEFAULT true,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "user_customizations_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "devices" (
    "id" VARCHAR(100) NOT NULL,
    "character_id" UUID,
    "end_user_id" UUID,
    "firmware_ver" VARCHAR(20),
    "hardware_model" VARCHAR(50),
    "last_seen" TIMESTAMP(3),
    "status" "DeviceStatus" NOT NULL DEFAULT 'OFFLINE',
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "devices_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "conversation_logs" (
    "id" UUID NOT NULL,
    "device_id" VARCHAR(100) NOT NULL,
    "character_id" UUID NOT NULL,
    "session_id" VARCHAR(100),
    "user_input" TEXT NOT NULL,
    "ai_response" TEXT NOT NULL,
    "latency_ms" INTEGER,
    "flagged" BOOLEAN NOT NULL DEFAULT false,
    "flag_reason" VARCHAR(200),
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "conversation_logs_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "brands_slug_key" ON "brands"("slug");

-- CreateIndex
CREATE UNIQUE INDEX "users_email_key" ON "users"("email");

-- CreateIndex
CREATE UNIQUE INDEX "end_users_open_id_key" ON "end_users"("open_id");

-- CreateIndex
CREATE INDEX "characters_brand_id_idx" ON "characters"("brand_id");

-- CreateIndex
CREATE INDEX "characters_status_idx" ON "characters"("status");

-- CreateIndex
CREATE INDEX "user_customizations_end_user_id_idx" ON "user_customizations"("end_user_id");

-- CreateIndex
CREATE INDEX "user_customizations_character_id_idx" ON "user_customizations"("character_id");

-- CreateIndex
CREATE UNIQUE INDEX "user_customizations_end_user_id_character_id_device_id_key" ON "user_customizations"("end_user_id", "character_id", "device_id");

-- CreateIndex
CREATE INDEX "devices_character_id_idx" ON "devices"("character_id");

-- CreateIndex
CREATE INDEX "devices_end_user_id_idx" ON "devices"("end_user_id");

-- CreateIndex
CREATE INDEX "conversation_logs_device_id_idx" ON "conversation_logs"("device_id");

-- CreateIndex
CREATE INDEX "conversation_logs_character_id_idx" ON "conversation_logs"("character_id");

-- CreateIndex
CREATE INDEX "conversation_logs_created_at_idx" ON "conversation_logs"("created_at");

-- CreateIndex
CREATE INDEX "conversation_logs_flagged_idx" ON "conversation_logs"("flagged");

-- AddForeignKey
ALTER TABLE "users" ADD CONSTRAINT "users_brand_id_fkey" FOREIGN KEY ("brand_id") REFERENCES "brands"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "characters" ADD CONSTRAINT "characters_brand_id_fkey" FOREIGN KEY ("brand_id") REFERENCES "brands"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "characters" ADD CONSTRAINT "characters_voice_id_fkey" FOREIGN KEY ("voice_id") REFERENCES "voice_profiles"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "user_customizations" ADD CONSTRAINT "user_customizations_end_user_id_fkey" FOREIGN KEY ("end_user_id") REFERENCES "end_users"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "user_customizations" ADD CONSTRAINT "user_customizations_character_id_fkey" FOREIGN KEY ("character_id") REFERENCES "characters"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "devices" ADD CONSTRAINT "devices_character_id_fkey" FOREIGN KEY ("character_id") REFERENCES "characters"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "devices" ADD CONSTRAINT "devices_end_user_id_fkey" FOREIGN KEY ("end_user_id") REFERENCES "end_users"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "conversation_logs" ADD CONSTRAINT "conversation_logs_device_id_fkey" FOREIGN KEY ("device_id") REFERENCES "devices"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "conversation_logs" ADD CONSTRAINT "conversation_logs_character_id_fkey" FOREIGN KEY ("character_id") REFERENCES "characters"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
