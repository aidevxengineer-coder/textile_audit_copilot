from __future__ import annotations

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    project_id: str | None
    session_id: str
    user_id: str
    original_query: str
    rewritten_query: str
    image_analysis: str | None
    conversation_history: list[dict[str, Any]]
    project_context: dict[str, Any] | None
    cross_reference_result: dict[str, Any] | None
    attachment_contexts: list[dict[str, Any]]
    current_attachment_contexts: list[dict[str, Any]]
    attachment_brief: str | None
    retrieved_docs_local: dict[str, list[Any]]
    retrieved_docs_global: dict[str, list[Any]]
    retrieved_docs_project: dict[str, list[Any]]
    rerank_scores: dict[str, float]
    reranked_docs: list[Any]
    relevance_verdict: dict[str, Any] | None
    retry_count: int
    final_response: str
    final_report: dict[str, Any] | None
    final_report_id: str | None
    response_status: str
    evaluator_feedback: str | None
    orchestrator_decision: dict[str, Any] | None
    current_web_findings: list[dict[str, Any]] | None
    web_search_query: str | None
    web_fallback_available: bool
    source_ip: str | None
