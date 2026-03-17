from fastapi import APIRouter

from ai_core.dependencies import get_rag_engine
from ai_core.models.schemas import RagIngestRequest, RagSearchRequest, RagSearchResponse

router = APIRouter(prefix="/rag", tags=["rag"])


@router.post("/ingest")
async def ingest_documents(req: RagIngestRequest):
    engine = await get_rag_engine()
    await engine.ingest(req.character_id, req.documents)
    return {"status": "ok", "count": len(req.documents)}


@router.post("/search", response_model=RagSearchResponse)
async def search_documents(req: RagSearchRequest):
    engine = await get_rag_engine()
    results = await engine.search(req.character_id, req.query, req.top_k)
    return RagSearchResponse(results=results, scores=[1.0] * len(results))
