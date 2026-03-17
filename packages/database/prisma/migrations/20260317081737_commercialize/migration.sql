-- CreateEnum
CREATE TYPE "LicenseTier" AS ENUM ('FREE', 'TRIAL', 'PRO', 'ENTERPRISE');

-- CreateEnum
CREATE TYPE "UsageType" AS ENUM ('CONVERSATION', 'TTS_CALL', 'LLM_TOKEN');

-- AlterTable
ALTER TABLE "characters" ADD COLUMN     "llm_model" VARCHAR(100),
ADD COLUMN     "llm_provider" VARCHAR(50),
ADD COLUMN     "tts_provider" VARCHAR(50);

-- AlterTable
ALTER TABLE "users" ADD COLUMN     "email_verified" TIMESTAMP(3);

-- CreateTable
CREATE TABLE "licenses" (
    "id" UUID NOT NULL,
    "brand_id" UUID NOT NULL,
    "tier" "LicenseTier" NOT NULL DEFAULT 'FREE',
    "max_characters" INTEGER NOT NULL DEFAULT 3,
    "max_devices" INTEGER NOT NULL DEFAULT 10,
    "max_daily_convos" INTEGER NOT NULL DEFAULT 100,
    "expires_at" TIMESTAMP(3),
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "licenses_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "api_keys" (
    "id" UUID NOT NULL,
    "brand_id" UUID NOT NULL,
    "name" VARCHAR(100) NOT NULL,
    "prefix" VARCHAR(12) NOT NULL,
    "hashed_key" VARCHAR(128) NOT NULL,
    "last_used_at" TIMESTAMP(3),
    "expires_at" TIMESTAMP(3),
    "revoked" BOOLEAN NOT NULL DEFAULT false,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "api_keys_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "usage_records" (
    "id" UUID NOT NULL,
    "brand_id" UUID NOT NULL,
    "type" "UsageType" NOT NULL,
    "count" INTEGER NOT NULL DEFAULT 0,
    "date" DATE NOT NULL,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "usage_records_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "device_activations" (
    "id" UUID NOT NULL,
    "device_id" VARCHAR(100) NOT NULL,
    "action" VARCHAR(20) NOT NULL,
    "reason" VARCHAR(200),
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "device_activations_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "soul_packs" (
    "id" UUID NOT NULL,
    "brand_id" UUID NOT NULL,
    "character_id" UUID NOT NULL,
    "version" VARCHAR(20) NOT NULL,
    "checksum" VARCHAR(64) NOT NULL,
    "file_url" VARCHAR(500) NOT NULL,
    "file_size" INTEGER NOT NULL,
    "metadata" JSONB,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "soul_packs_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "licenses_brand_id_idx" ON "licenses"("brand_id");

-- CreateIndex
CREATE UNIQUE INDEX "api_keys_hashed_key_key" ON "api_keys"("hashed_key");

-- CreateIndex
CREATE INDEX "api_keys_brand_id_idx" ON "api_keys"("brand_id");

-- CreateIndex
CREATE INDEX "api_keys_hashed_key_idx" ON "api_keys"("hashed_key");

-- CreateIndex
CREATE INDEX "usage_records_brand_id_date_idx" ON "usage_records"("brand_id", "date");

-- CreateIndex
CREATE UNIQUE INDEX "usage_records_brand_id_type_date_key" ON "usage_records"("brand_id", "type", "date");

-- CreateIndex
CREATE INDEX "device_activations_device_id_idx" ON "device_activations"("device_id");

-- CreateIndex
CREATE INDEX "device_activations_created_at_idx" ON "device_activations"("created_at");

-- CreateIndex
CREATE INDEX "soul_packs_brand_id_idx" ON "soul_packs"("brand_id");

-- CreateIndex
CREATE INDEX "soul_packs_character_id_idx" ON "soul_packs"("character_id");

-- AddForeignKey
ALTER TABLE "licenses" ADD CONSTRAINT "licenses_brand_id_fkey" FOREIGN KEY ("brand_id") REFERENCES "brands"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "api_keys" ADD CONSTRAINT "api_keys_brand_id_fkey" FOREIGN KEY ("brand_id") REFERENCES "brands"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "device_activations" ADD CONSTRAINT "device_activations_device_id_fkey" FOREIGN KEY ("device_id") REFERENCES "devices"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "soul_packs" ADD CONSTRAINT "soul_packs_brand_id_fkey" FOREIGN KEY ("brand_id") REFERENCES "brands"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
