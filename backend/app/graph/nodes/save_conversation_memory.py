from __future__ import annotations

from app.graph.node_utils import emit_complete, emit_start, get_runtime
from app.graph.state import AgentState
from app.models.conversation import ConversationSession
from app.models.report import Report


async def save_conversation_memory(state: AgentState, config) -> AgentState:
    node_name = "Save Query and Response to Conversation Memory"
    await emit_start(config, node_name)
    runtime = get_runtime(config)

    with runtime.session_factory() as db:
        runtime.memory_service.save_message(
            db,
            session_id=runtime.session_id,
            user_id=runtime.user_id,
            role="user",
            content=state["original_query"],
            attachments=state.get("current_attachment_contexts", []),
        )
        runtime.memory_service.save_message(
            db,
            session_id=runtime.session_id,
            user_id=runtime.user_id,
            role="assistant",
            content=state["final_response"],
            attachments=[],
        )
        if state.get("final_report"):
            persisted_session = db.get(ConversationSession, runtime.session_id)
            db.add(
                Report(
                    id=state.get("final_report_id"),
                    project_id=persisted_session.project_id if persisted_session else state.get("project_id"),
                    session_id=runtime.session_id,
                    user_id=runtime.user_id,
                    original_query=state["original_query"],
                    rewritten_query=state.get("rewritten_query"),
                    response_text=state["final_response"],
                    structured_report_json=state["final_report"],
                    response_status=state.get("response_status", "completed"),
                )
            )
            db.commit()

    await emit_complete(config, node_name, "Conversation persisted")
    return {}
