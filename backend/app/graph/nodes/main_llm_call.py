from __future__ import annotations

import json
import re
from uuid import uuid4

from langchain_core.messages import HumanMessage, SystemMessage

from app.graph.node_utils import compact_attachments, compact_documents, compact_history, compact_project_context, document_workspace_attachments, emit_complete, emit_start, get_runtime, project_completeness
from app.graph.prompts import DIRECT_RESPONSE_PROMPT, DOCUMENT_ANSWER_VERIFIER_PROMPT, DOCUMENT_WORKSPACE_PROMPT, GROUNDED_ANSWER_PROMPT, GROUNDED_REPORT_PROMPT
from app.graph.state import AgentState
from app.mcp.web_sources import build_compliance_web_query
from app.services.schemas import ComplianceReport, DocumentAnswerVerification
from app.services.tool_service import ToolServiceError


TOKEN_CHUNK_PATTERN = re.compile(r"\S+\s*|\n")


def normalize_markdown_tables(value: str) -> str:
    """Keep verifier deletions from leaving visually broken empty table cells."""
    lines: list[str] = []
    for line in value.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = line.split("|")
            cells[1:-1] = [cell if cell.strip() else " — " for cell in cells[1:-1]]
            line = "|".join(cells)
        lines.append(line)
    return "\n".join(lines)


async def main_llm_call(state: AgentState, config) -> AgentState:
    node_name = "Main LLM Call"
    await emit_start(config, node_name)
    runtime = get_runtime(config)
    decision = state.get("orchestrator_decision") or {"route": "grounded", "needs_current_web_info": False}

    # A failed local retrieval may already have populated these through the
    # web-search fallback node. Reuse them rather than issuing a duplicate MCP
    # call.
    current_web_findings = state.get("current_web_findings")
    web_query = state.get("web_search_query")
    tool_output = None

    if decision.get("route") == "document":
        targets = state.get("current_attachment_contexts") or state.get("attachment_contexts", [])
        source_documents = document_workspace_attachments(targets)
        messages = [
            SystemMessage(content=DOCUMENT_WORKSPACE_PROMPT),
            HumanMessage(
                content=json.dumps(
                    {
                        "query": state["original_query"],
                        "history": compact_history(state.get("conversation_history", [])),
                        "target_documents": source_documents,
                    },
                    indent=2,
                )
            ),
        ]
        draft = (await runtime.ollama_service.invoke_text(messages)).strip()
        verification = await runtime.ollama_service.invoke_structured(
            DocumentAnswerVerification,
            [
                SystemMessage(content=DOCUMENT_ANSWER_VERIFIER_PROMPT),
                HumanMessage(
                    content=json.dumps(
                        {
                            "user_request": state["original_query"],
                            "source_documents": source_documents,
                            "draft_answer": draft,
                        },
                        indent=2,
                    )
                ),
            ],
        )
        response = normalize_markdown_tables(verification.verified_answer.strip())
        for token in TOKEN_CHUNK_PATTERN.findall(response):
            await runtime.emitter.token(token)
        await emit_complete(config, node_name, "Document operation completed")
        return {"final_response": response, "final_report": None, "response_status": "completed"}

    if decision.get("route") == "direct" and decision.get("tool_name") not in {None, "none"}:
        tool_name = decision["tool_name"]
        if runtime.pipeline_log_service:
            runtime.pipeline_log_service.log_step(
                run_id=runtime.run_id,
                node_name=node_name,
                status="in_progress",
                detail=f"Invoking {tool_name} tool",
            )
        await runtime.emitter.stage(node_name, "in_progress", f"Invoking {tool_name} tool")
        try:
            tool_output = await runtime.tool_service.invoke(tool_name, state["original_query"])
            if runtime.pipeline_log_service:
                runtime.pipeline_log_service.log_tool(
                    run_id=runtime.run_id,
                    tool_name=tool_name,
                    tool_kind="utility",
                    status="completed",
                    arguments={"query": state["original_query"]},
                    result_preview=json.dumps(tool_output, ensure_ascii=True),
                )
        except ToolServiceError as exc:
            tool_output = {"tool_name": tool_name, "error": str(exc)}
            if runtime.pipeline_log_service:
                runtime.pipeline_log_service.log_tool(
                    run_id=runtime.run_id,
                    tool_name=tool_name,
                    tool_kind="utility",
                    status="failed",
                    arguments={"query": state["original_query"]},
                    result_preview=str(exc),
                )

    if decision.get("needs_current_web_info") and not current_web_findings and runtime.mcp_service:
        if runtime.pipeline_log_service:
            runtime.pipeline_log_service.log_step(
                run_id=runtime.run_id,
                node_name=node_name,
                status="in_progress",
                detail="Checking current web updates via MCP",
            )
        await runtime.emitter.stage(node_name, "in_progress", "Checking current web updates via MCP")
        web_query = build_compliance_web_query(state["original_query"])
        try:
            current_web_findings = await runtime.mcp_service.search_authoritative_sources(web_query)
            if runtime.pipeline_log_service:
                runtime.pipeline_log_service.log_tool(
                    run_id=runtime.run_id,
                    tool_name="web_search_mcp",
                    tool_kind="mcp",
                    status="completed",
                    arguments={
                        "query": web_query,
                        "original_query": state["original_query"],
                        "reason": "explicit_current_information_request",
                        "source_policy": "authoritative_domains_only",
                    },
                    result_preview=json.dumps(current_web_findings, ensure_ascii=True),
                )
        except Exception as exc:
            current_web_findings = []
            if runtime.pipeline_log_service:
                runtime.pipeline_log_service.log_tool(
                    run_id=runtime.run_id,
                    tool_name="web_search_mcp",
                    tool_kind="mcp",
                    status="failed",
                    arguments={
                        "query": web_query,
                        "original_query": state["original_query"],
                        "reason": "explicit_current_information_request",
                        "source_policy": "authoritative_domains_only",
                    },
                    result_preview=str(exc),
                )
            await runtime.emitter.stage(
                node_name,
                "in_progress",
                "Current official sources could not be verified; using only available local evidence.",
            )

    if decision.get("route") == "direct":
        messages = [
            SystemMessage(content=DIRECT_RESPONSE_PROMPT),
            HumanMessage(
                content=json.dumps(
                    {
                        "query": state["original_query"],
                        "history": compact_history(state.get("conversation_history", [])),
                        "project_context": compact_project_context(state.get("project_context")),
                        "cross_reference_result": state.get("cross_reference_result"),
                        "image_analysis": state.get("image_analysis"),
                        "attachment_brief": state.get("attachment_brief"),
                        "tool_output": tool_output,
                    },
                    indent=2,
                )
            ),
        ]
        # Stream direct answers as they are generated. This makes simple guidance feel
        # immediate instead of making the interface wait for the full model response.
        response_parts: list[str] = []
        async for token in runtime.ollama_service.stream_text(messages):
            response_parts.append(token)
            await runtime.emitter.token(token)
        response = "".join(response_parts)
        await emit_complete(config, node_name, "Direct response generated")
        return {
            "final_response": response,
            "final_report": None,
            "response_status": "completed",
            "current_web_findings": current_web_findings,
            "web_search_query": web_query,
        }

    if decision.get("response_mode", "answer") == "answer":
        messages = [
            SystemMessage(content=GROUNDED_ANSWER_PROMPT),
            HumanMessage(
                content=json.dumps(
                    {
                        "query": state["original_query"],
                        "rewritten_query": state.get("rewritten_query"),
                        "history": compact_history(state.get("conversation_history", [])),
                        "primary_message_attachments": compact_attachments(state.get("current_attachment_contexts", [])),
                        "project_memory_files": compact_attachments(state.get("attachment_contexts", [])),
                        "retrieved_sources": compact_documents(state.get("reranked_docs", []), limit=6, snippet_limit=650),
                        "current_web_findings": current_web_findings,
                    },
                    indent=2,
                )
            ),
        ]
        response_parts: list[str] = []
        async for token in runtime.ollama_service.stream_text(messages):
            response_parts.append(token)
            await runtime.emitter.token(token)
        response = "".join(response_parts).strip()
        await emit_complete(config, node_name, "Grounded answer generated")
        return {
            "final_response": response,
            "final_report": None,
            "response_status": "completed",
            "current_web_findings": current_web_findings,
            "web_search_query": web_query,
        }

    report = await runtime.ollama_service.invoke_structured(
        ComplianceReport,
        [
            SystemMessage(content=GROUNDED_REPORT_PROMPT),
            HumanMessage(
                content=json.dumps(
                    {
                        "original_query": state["original_query"],
                        "rewritten_query": state.get("rewritten_query"),
                        "history": compact_history(state.get("conversation_history", [])),
                        "project_context": compact_project_context(state.get("project_context")),
                        "cross_reference_result": state.get("cross_reference_result"),
                        "image_analysis": state.get("image_analysis"),
                        "attachment_brief": state.get("attachment_brief"),
                        "uploaded_company_documents": compact_attachments(state.get("attachment_contexts", [])),
                        "project_evidence_completeness": project_completeness(state.get("attachment_contexts", [])),
                        "retrieved_docs": compact_documents(state.get("reranked_docs", []), limit=8, snippet_limit=500),
                        "current_web_findings": current_web_findings,
                    },
                    indent=2,
                )
            ),
        ],
    )
    if current_web_findings:
        report = report.model_copy(update={"current_web_findings": current_web_findings})
    report = runtime.report_guardrail_service.validate(
        report,
        retrieved_docs=state.get("reranked_docs", []),
        attachments=state.get("attachment_contexts", []),
        web_findings=current_web_findings,
    )
    markdown = runtime.report_service.render_markdown(report)
    for token in TOKEN_CHUNK_PATTERN.findall(markdown):
        await runtime.emitter.token(token)

    report_id = str(uuid4())
    await emit_complete(config, node_name, "Grounded report generated")
    return {
        "final_response": markdown,
        "final_report": report.model_dump(),
        "final_report_id": report_id,
        "response_status": "completed",
        "current_web_findings": current_web_findings,
        "web_search_query": web_query,
    }
