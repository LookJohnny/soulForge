-- Semantic memory: pgvector embeddings on the four memory layers.
-- Requires the pgvector extension (docker image pgvector/pgvector:pg16).

CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE profile_memories    ADD COLUMN IF NOT EXISTS embedding vector(512), ADD COLUMN IF NOT EXISTS embedding_model TEXT;
ALTER TABLE episodic_memories   ADD COLUMN IF NOT EXISTS embedding vector(512), ADD COLUMN IF NOT EXISTS embedding_model TEXT;
ALTER TABLE semantic_memories   ADD COLUMN IF NOT EXISTS embedding vector(512), ADD COLUMN IF NOT EXISTS embedding_model TEXT;
ALTER TABLE relational_memories ADD COLUMN IF NOT EXISTS embedding vector(512), ADD COLUMN IF NOT EXISTS embedding_model TEXT;

CREATE INDEX IF NOT EXISTS idx_profile_memories_embedding    ON profile_memories    USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_episodic_memories_embedding   ON episodic_memories   USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_semantic_memories_embedding   ON semantic_memories   USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_relational_memories_embedding ON relational_memories USING hnsw (embedding vector_cosine_ops);
