-- CreateTable
CREATE TABLE "chat_messages" (
    "id" UUID NOT NULL,
    "character_id" UUID NOT NULL,
    "visitor_id" VARCHAR(100) NOT NULL,
    "role" VARCHAR(10) NOT NULL,
    "content" TEXT NOT NULL,
    "action" TEXT,
    "thought" TEXT,
    "emotion" VARCHAR(20),
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "chat_messages_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "chat_messages_character_id_visitor_id_idx" ON "chat_messages"("character_id", "visitor_id");

-- CreateIndex
CREATE INDEX "chat_messages_created_at_idx" ON "chat_messages"("created_at");
