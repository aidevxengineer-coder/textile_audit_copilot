from __future__ import annotations

import json
import re

from langchain_core.messages import HumanMessage, SystemMessage

from app.graph.node_utils import compact_history, compact_project_context, emit_complete, emit_start, get_runtime
from app.graph.prompts import ORCHESTRATOR_PROMPT
from app.graph.state import AgentState
from app.services.schemas import OrchestratorDecision


REPORT_REQUEST_PATTERN = re.compile(
    r"\b(?:generate|create|prepare|produce|print|export|write)\b.{0,40}\b(?:audit\s+|pre[- ]?audit\s+)?report\b|"
    r"\b(?:full|complete)\s+(?:audit\s+|pre[- ]?audit\s+)?report\b",
    re.IGNORECASE,
)

DOCUMENT_OPERATION_PATTERN = re.compile(
    r"\b(?:summari[sz]e|summary|explain|simplify|expand|extend|rewrite|edit|improve(?:ments?)?|critique|review|"
    r"shortcomings?|limitations?|weakness(?:es)?|suggestions?|recommendations?|table|tabulate|"
    r"graph|chart|diagram|flowchart|map|outline|key points?|compare)\b",
    re.IGNORECASE,
)
COMPLIANCE_DECISION_PATTERN = re.compile(
    r"\b(?:complian(?:ce|t)|non[- ]?complian(?:ce|t)|violation|conform(?:ity|ance)|legal|law|"
    r"regulation|standard|clause|audit finding|pass(?: an| the)? audit)\b",
    re.IGNORECASE,
)


def is_document_operation(query: str, *, has_documents: bool, response_mode: str = "answer") -> bool:
    """Deterministically keep document transformations out of compliance retrieval."""
    return bool(
        has_documents
        and response_mode == "answer"
        and DOCUMENT_OPERATION_PATTERN.search(query)
        and not COMPLIANCE_DECISION_PATTERN.search(query)
    )


async def orchestrator(state: AgentState, config) -> AgentState:
    node_name = "Orchestrator"
    await emit_start(config, node_name)
    runtime = get_runtime(config)
    decision = await runtime.ollama_service.invoke_structured(
        OrchestratorDecision,
        [
            SystemMessage(content=ORCHESTRATOR_PROMPT),
            HumanMessage(
                content=json.dumps(
                    {
                        "original_query": state["original_query"],
                        "rewritten_query": state.get("rewritten_query"),
                        "conversation_history": compact_history(state.get("conversation_history", [])),
                        "project_context": compact_project_context(state.get("project_context")),
                        "cross_reference_result": state.get("cross_reference_result"),
                        "image_analysis": state.get("image_analysis"),
                        "attachment_brief": state.get("attachment_brief"),
                    },
                    indent=2,
                )
            ),
        ],
    )
    # Small local models can over-select the report schema when they see audit
    # vocabulary. Keep report generation behind an explicit user request.
    requested_mode = "report" if REPORT_REQUEST_PATTERN.search(state["original_query"]) else "answer"
    requested_route = decision.route
    has_documents = bool(state.get("current_attachment_contexts") or state.get("attachment_contexts"))
    if is_document_operation(
        state["original_query"], has_documents=has_documents, response_mode=requested_mode
    ):
        requested_route = "document"
    decision = decision.model_copy(update={"route": requested_route, "response_mode": requested_mode})
    await emit_complete(config, node_name, f"Route={decision.route}")
    return {"orchestrator_decision": decision.model_dump()}
