from __future__ import annotations

from app.graph.node_utils import emit_complete, emit_start
from app.graph.state import AgentState
from app.services.retrieval_service import reciprocal_rank_fusion
from app.services.schemas import RetrievedDocument


async def rerank_documents(state: AgentState, config) -> AgentState:
    node_name = "Re-rank Documents"
    await emit_start(config, node_name, "Applying Reciprocal Rank Fusion")

    result_sets: list[list[RetrievedDocument]] = []
    for bucket in ("retrieved_docs_project", "retrieved_docs_local", "retrieved_docs_global"):
        for variant in ("original", "rewritten"):
            docs = [RetrievedDocument.model_validate(item) for item in state.get(bucket, {}).get(variant, [])]
            result_sets.append(docs)

    fused, scores = reciprocal_rank_fusion(result_sets)
    authority_weights = {
        "user_evidence": 1.35,
        "authoritative": 1.20,
        "example_not_standard": 0.70,
    }
    fused = [
        item.model_copy(update={"score": item.score * authority_weights.get(item.authority_level, 1.0)})
        for item in fused
    ]
    fused.sort(key=lambda item: item.score, reverse=True)
    await emit_complete(config, node_name, f"Reranked {len(fused)} unique clauses")
    return {"reranked_docs": [item.model_dump() for item in fused], "rerank_scores": scores}
