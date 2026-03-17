"""RAG Engine - Vector retrieval using Milvus + DashScope embedding."""

import dashscope
from pymilvus import MilvusClient

from ai_core.config import settings


class RagEngine:
    def __init__(self):
        self.client: MilvusClient | None = None
        self.collection_prefix = "soulforge_rag_"

    async def connect(self):
        self.client = MilvusClient(
            uri=f"http://{settings.milvus_host}:{settings.milvus_port}",
            timeout=5,
        )

    def _collection_name(self, character_id: str) -> str:
        # Milvus collection names must be alphanumeric + underscore
        safe_id = character_id.replace("-", "_")
        return f"{self.collection_prefix}{safe_id}"

    async def ensure_collection(self, character_id: str):
        """Create collection for a character if it doesn't exist."""
        if not self.client:
            await self.connect()

        name = self._collection_name(character_id)
        if not self.client.has_collection(name):
            self.client.create_collection(
                collection_name=name,
                dimension=settings.rag_embedding_dim,
                metric_type="COSINE",
            )

    async def ingest(self, character_id: str, documents: list[str]):
        """Embed and store documents for a character."""
        if not documents:
            return

        await self.ensure_collection(character_id)
        embeddings = await self._embed(documents)

        data = [
            {"id": i, "vector": emb, "text": doc}
            for i, (doc, emb) in enumerate(zip(documents, embeddings, strict=True))
        ]
        self.client.insert(
            collection_name=self._collection_name(character_id),
            data=data,
        )

    async def search(
        self,
        character_id: str,
        query: str,
        top_k: int | None = None,
    ) -> list[str]:
        """Search for relevant context given a user query."""
        if not self.client:
            await self.connect()

        name = self._collection_name(character_id)
        if not self.client.has_collection(name):
            return []

        k = top_k or settings.rag_top_k
        query_embedding = await self._embed([query])

        results = self.client.search(
            collection_name=name,
            data=query_embedding,
            limit=k,
            output_fields=["text"],
        )

        texts = []
        for hits in results:
            for hit in hits:
                if hit["distance"] >= settings.rag_score_threshold:
                    texts.append(hit["entity"]["text"])
        return texts

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        """Get embeddings from DashScope."""
        resp = dashscope.TextEmbedding.call(
            model=settings.rag_embedding_model,
            input=texts,
            api_key=settings.dashscope_api_key,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Embedding failed: {resp.message}")
        return [item["embedding"] for item in resp.output["embeddings"]]
