from __future__ import annotations

import asyncio

from app.graph.node_utils import emit_complete, emit_start, get_runtime
from app.graph.state import AgentState
from app.services.project_graphrag_service import ProjectGraphRAGService


async def retrieve_documents(state: AgentState, config) -> AgentState:
    node_name = "Retrieve Documents"
    await emit_start(config, node_name, "Running local and global graph-aware retrieval")
    runtime = get_runtime(config)

    original_query = state["original_query"]
    rewritten_query = state.get("rewritten_query", original_query)
    project_id = state.get("project_id")
    primary_upload_ids = [
        str(row.get("upload_id"))
        for row in state.get("current_attachment_contexts", [])
        if row.get("upload_id")
    ]
    project_service = ProjectGraphRAGService(runtime.retrieval_service) if project_id else None
    if project_service:
        await asyncio.to_thread(project_service.ensure_uploads_indexed, project_id, state.get("attachment_contexts", []))

    local_original, local_rewritten, global_original, global_rewritten = await asyncio.gather(
        asyncio.to_thread(runtime.retrieval_service.balanced_search, original_query, query_variant="original"),
        asyncio.to_thread(runtime.retrieval_service.balanced_search, rewritten_query, query_variant="rewritten"),
        asyncio.to_thread(runtime.retrieval_service.global_search, original_query, query_variant="original"),
        asyncio.to_thread(runtime.retrieval_service.global_search, rewritten_query, query_variant="rewritten"),
    )
    local_results = {
        "original": [item.model_dump() for item in local_original],
        "rewritten": [item.model_dump() for item in local_rewritten],
    }
    global_results = {
        "original": [item.model_dump() for item in global_original],
        "rewritten": [item.model_dump() for item in global_rewritten],
    }
    project_results = {"original": [], "rewritten": []}
    if project_service and project_id:
        project_original, project_rewritten = await asyncio.gather(
            asyncio.to_thread(project_service.search, project_id, original_query, query_variant="original", upload_ids=primary_upload_ids),
            asyncio.to_thread(project_service.search, project_id, rewritten_query, query_variant="rewritten", upload_ids=primary_upload_ids),
        )
        project_results = {
            "original": [item.model_dump() for item in project_original],
            "rewritten": [item.model_dump() for item in project_rewritten],
        }

    await emit_complete(
        config,
        node_name,
        f"Standards={sum(len(v) for v in local_results.values())}, Graph={sum(len(v) for v in global_results.values())}, Project={sum(len(v) for v in project_results.values())}",
    )
    return {"retrieved_docs_local": local_results, "retrieved_docs_global": global_results, "retrieved_docs_project": project_results}
