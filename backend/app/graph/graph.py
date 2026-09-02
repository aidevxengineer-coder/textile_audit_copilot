from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.config import get_settings
from app.graph.nodes.document_relevance_evaluator import document_relevance_evaluator
from app.graph.nodes.cross_reference_evaluator import cross_reference_evaluator
from app.graph.nodes.increment_retry_count import increment_retry_count
from app.graph.nodes.load_conversation_history import load_conversation_history
from app.graph.nodes.main_llm_call import main_llm_call
from app.graph.nodes.orchestrator import orchestrator
from app.graph.nodes.query_rewriter import query_rewriter
from app.graph.nodes.rerank_documents import rerank_documents
from app.graph.nodes.retrieve_documents import retrieve_documents
from app.graph.nodes.safe_response import safe_response
from app.graph.nodes.save_conversation_memory import save_conversation_memory
from app.graph.nodes.web_search_fallback import web_search_fallback
from app.graph.state import AgentState


def route_after_query_rewriter(state: AgentState) -> str:
    return "retry_retrieval"


def route_after_orchestrator(state: AgentState) -> str:
    decision = state.get("orchestrator_decision") or {}
    route = decision.get("route")
    return route if route in {"direct", "document", "grounded"} else "grounded"


def route_after_rerank(state: AgentState) -> str:
    decision = state.get("orchestrator_decision") or {}
    return "answer" if decision.get("response_mode", "answer") == "answer" else "report"


def route_after_relevance_evaluator(state: AgentState) -> str:
    verdict = state.get("relevance_verdict") or {}
    if verdict.get("relevant") and verdict.get("sufficient"):
        return "main"
    # If the user's own evidence is relevant, synthesis is still valuable even
    # when closure proof or criterion coverage is incomplete. The deterministic
    # report guardrail will downgrade unsupported findings and state the gaps.
    has_project_evidence = any(
        row.get("source_type") == "project_upload"
        for row in state.get("reranked_docs", [])
    )
    if verdict.get("relevant") and has_project_evidence:
        return "main"
    retries = state.get("retry_count", 0)
    if retries < get_settings().max_retries:
        return "retry"
    return "web" if get_settings().enable_web_search_mcp else "safe"


def route_after_web_search_fallback(state: AgentState) -> str:
    return "main" if state.get("web_fallback_available") else "safe"


def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("load_conversation_history", load_conversation_history)
    graph.add_node("query_rewriter", query_rewriter)
    graph.add_node("cross_reference_evaluator", cross_reference_evaluator)
    graph.add_node("orchestrator", orchestrator)
    graph.add_node("retrieve_documents", retrieve_documents)
    graph.add_node("rerank_documents", rerank_documents)
    graph.add_node("document_relevance_evaluator", document_relevance_evaluator)
    graph.add_node("increment_retry_count", increment_retry_count)
    graph.add_node("main_llm_call", main_llm_call)
    graph.add_node("safe_response", safe_response)
    graph.add_node("web_search_fallback", web_search_fallback)
    graph.add_node("save_conversation_memory", save_conversation_memory)

    graph.add_edge(START, "load_conversation_history")
    graph.add_edge("load_conversation_history", "orchestrator")
    graph.add_conditional_edges(
        "query_rewriter",
        route_after_query_rewriter,
        {
            "initial_orchestrator": "retrieve_documents",
            "retry_retrieval": "retrieve_documents",
        },
    )
    graph.add_conditional_edges(
        "orchestrator",
        route_after_orchestrator,
        {
            "direct": "main_llm_call",
            "document": "main_llm_call",
            "grounded": "cross_reference_evaluator",
        },
    )
    graph.add_edge("cross_reference_evaluator", "query_rewriter")
    graph.add_edge("retrieve_documents", "rerank_documents")
    graph.add_conditional_edges(
        "rerank_documents",
        route_after_rerank,
        {"answer": "main_llm_call", "report": "document_relevance_evaluator"},
    )
    graph.add_conditional_edges(
        "document_relevance_evaluator",
        route_after_relevance_evaluator,
        {
            "main": "main_llm_call",
            "retry": "increment_retry_count",
            "web": "web_search_fallback",
            "safe": "safe_response",
        },
    )
    graph.add_conditional_edges(
        "web_search_fallback",
        route_after_web_search_fallback,
        {"main": "main_llm_call", "safe": "safe_response"},
    )
    graph.add_edge("increment_retry_count", "query_rewriter")
    graph.add_edge("main_llm_call", "save_conversation_memory")
    graph.add_edge("safe_response", "save_conversation_memory")
    graph.add_edge("save_conversation_memory", END)

    return graph.compile()
