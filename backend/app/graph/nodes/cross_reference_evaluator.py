from __future__ import annotations

import json
import re

from langchain_core.messages import HumanMessage, SystemMessage

from app.graph.node_utils import compact_project_context, emit_complete, emit_start, get_runtime
from app.graph.prompts import CROSS_REFERENCE_PROMPT
from app.graph.state import AgentState
from app.services.schemas import CrossReferenceResult


async def cross_reference_evaluator(state: AgentState, config) -> AgentState:
    node_name = "Cross Reference Evaluator"
    await emit_start(config, node_name, "Comparing uploads and related chat context")
    runtime = get_runtime(config)
    project_context = state.get("project_context") or {}
    attachments = state.get("attachment_contexts", [])
    has_context = bool(
        attachments
        or project_context.get("shared_uploads")
        or project_context.get("related_sessions")
        or project_context.get("cross_project_sessions")
    )
    comparison_requested = bool(re.search(
        r"\b(compare|comparison|contradict|conflict|consistent|difference|across files)\b",
        state["original_query"],
        re.IGNORECASE,
    ))
    response_mode = (state.get("orchestrator_decision") or {}).get("response_mode", "answer")
    if not has_context:
        result = CrossReferenceResult(summary="No prior project evidence was available for comparison.")
    elif response_mode == "answer" and not comparison_requested:
        result = CrossReferenceResult(
            summary="Cross-document comparison was not needed for this question."
        )
    else:
        result = await runtime.ollama_service.invoke_structured(
            CrossReferenceResult,
            [
                SystemMessage(content=CROSS_REFERENCE_PROMPT),
                HumanMessage(
                    content=json.dumps(
                        {
                            "query": state["original_query"],
                            "current_uploads": [
                                {
                                    "upload_id": row.get("upload_id"),
                                    "file_name": row.get("file_name"),
                                    "document_type": row.get("document_type"),
                                    "evidence_summary": str(row.get("evidence_summary") or "")[:260],
                                    "preview_text": str(row.get("preview_text") or "")[:260],
                                }
                                for row in attachments[:8]
                            ],
                            "project_context": compact_project_context(project_context),
                        },
                        indent=2,
                    )
                ),
            ],
        )
    detail = f"{len(result.consistencies)} consistent, {len(result.contradictions)} contradictory"
    await emit_complete(config, node_name, detail)
    return {"cross_reference_result": result.model_dump()}
