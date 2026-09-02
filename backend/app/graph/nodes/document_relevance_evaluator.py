from __future__ import annotations

import asyncio
import json
import re

from langchain_core.messages import HumanMessage, SystemMessage

from app.graph.node_utils import compact_attachments, compact_documents, compact_project_context, emit_complete, emit_start, get_runtime
from app.graph.prompts import RELEVANCE_EVALUATOR_PROMPT
from app.graph.state import AgentState
from app.services.schemas import RelevanceVerdict


WORD_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]+", re.IGNORECASE)
STOP_WORDS = {
    "about", "after", "again", "against", "answer", "audit", "before", "could", "documents",
    "evidence", "from", "give", "have", "into", "project", "question", "review", "should", "that",
    "their", "these", "this", "three", "uploaded", "used", "what", "when", "where", "which", "with",
}


def _fallback_relevance_verdict(state: AgentState) -> RelevanceVerdict:
    """Conservative local coverage check used only when the LLM stalls."""

    query = " ".join(
        value for value in (state.get("original_query"), state.get("rewritten_query")) if value
    )
    query_terms = {
        token.lower()
        for token in WORD_PATTERN.findall(query)
        if len(token) > 2 and token.lower() not in STOP_WORDS
    }
    matches = 0
    grounded_matches = 0
    for document in state.get("reranked_docs", [])[:8]:
        haystack = " ".join(
            str(document.get(key) or "")
            for key in ("title", "standard_name", "clause_reference", "citation", "snippet")
        ).lower()
        document_terms = {token.lower() for token in WORD_PATTERN.findall(haystack)}
        overlap = query_terms.intersection(document_terms)
        if len(overlap) >= 2 or (len(query_terms) <= 2 and overlap):
            matches += 1
            if document.get("clause_reference") or document.get("citation") or document.get("source_url"):
                grounded_matches += 1

    relevant = matches > 0
    sufficient = matches >= 3 and grounded_matches >= 2
    if sufficient:
        feedback = "Local relevance fallback found multiple matching, traceable clauses."
    elif relevant:
        feedback = "Some matching clauses were found, but more traceable coverage is needed."
    else:
        feedback = "The retrieved clauses did not contain enough query-specific evidence."
    return RelevanceVerdict(relevant=relevant, sufficient=sufficient, feedback=feedback)


async def document_relevance_evaluator(state: AgentState, config) -> AgentState:
    node_name = "Document Relevance Evaluator"
    await emit_start(config, node_name)
    runtime = get_runtime(config)
    messages = [
        SystemMessage(content=RELEVANCE_EVALUATOR_PROMPT),
        HumanMessage(
            content=json.dumps(
                {
                    "original_query": state["original_query"],
                    "rewritten_query": state.get("rewritten_query"),
                    "project_context": compact_project_context(state.get("project_context")),
                    "cross_reference_result": state.get("cross_reference_result"),
                    "attachment_brief": state.get("attachment_brief"),
                    "uploaded_company_documents": compact_attachments(state.get("attachment_contexts", []), limit=8),
                    "retrieved_docs": compact_documents(state.get("reranked_docs", []), limit=8, snippet_limit=400),
                },
                indent=2,
            )
        ),
    ]
    try:
        verdict = await asyncio.wait_for(
            runtime.ollama_service.invoke_structured(RelevanceVerdict, messages),
            timeout=runtime.retrieval_service.settings.relevance_evaluator_timeout_seconds,
        )
    except (TimeoutError, asyncio.TimeoutError):
        verdict = _fallback_relevance_verdict(state)
        await runtime.emitter.stage(
            node_name,
            "in_progress",
            "The model relevance check was slow, so a conservative local coverage check was used.",
        )
    detail = "sufficient coverage" if verdict.relevant and verdict.sufficient else verdict.feedback
    await emit_complete(config, node_name, detail)
    return {"relevance_verdict": verdict.model_dump(), "evaluator_feedback": verdict.feedback}
