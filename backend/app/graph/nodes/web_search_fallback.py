from __future__ import annotations

import json

from app.graph.node_utils import emit_complete, emit_start, get_runtime
from app.graph.state import AgentState
from app.mcp.web_sources import build_compliance_web_query


async def web_search_fallback(state: AgentState, config) -> AgentState:
    """Use the web-search MCP only after local retrieval has been exhausted."""
    node_name = "Web Search Fallback"
    await emit_start(config, node_name)
    runtime = get_runtime(config)

    if runtime.mcp_service is None:
        await emit_complete(config, node_name, "Web search is unavailable")
        return {"web_fallback_available": False}

    query = build_compliance_web_query(
        state.get("rewritten_query") or state["original_query"],
        evaluator_feedback=state.get("evaluator_feedback"),
    )
    try:
        if runtime.pipeline_log_service:
            runtime.pipeline_log_service.log_step(
                run_id=runtime.run_id,
                node_name=node_name,
                status="in_progress",
                detail="Local evidence was insufficient; searching verified official sources",
            )
        await runtime.emitter.stage(
            node_name,
            "in_progress",
            "Local evidence was insufficient. Searching verified official sources.",
        )
        findings = await runtime.mcp_service.search_authoritative_sources(query)
        if runtime.pipeline_log_service:
            runtime.pipeline_log_service.log_tool(
                run_id=runtime.run_id,
                tool_name="web_search_mcp",
                tool_kind="mcp",
                status="completed",
                arguments={
                    "query": query,
                    "original_query": state["original_query"],
                    "evaluator_feedback": state.get("evaluator_feedback"),
                    "reason": "local_retrieval_insufficient",
                    "source_policy": "authoritative_domains_only",
                },
                result_preview=json.dumps(findings, ensure_ascii=True),
            )
        available = bool(findings)
        await emit_complete(
            config,
            node_name,
            "Found verified official public sources" if available else "No useful official public sources found",
        )
        return {
            "current_web_findings": findings,
            "web_search_query": query,
            "web_fallback_available": available,
        }
    except Exception as exc:
        if runtime.pipeline_log_service:
            runtime.pipeline_log_service.log_tool(
                run_id=runtime.run_id,
                tool_name="web_search_mcp",
                tool_kind="mcp",
                status="failed",
                arguments={
                    "query": query,
                    "original_query": state["original_query"],
                    "reason": "local_retrieval_insufficient",
                    "source_policy": "authoritative_domains_only",
                },
                result_preview=str(exc),
            )
        await emit_complete(config, node_name, "Web search could not provide sources")
        return {
            "current_web_findings": [],
            "web_search_query": query,
            "web_fallback_available": False,
        }
