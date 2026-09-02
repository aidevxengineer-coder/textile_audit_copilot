from __future__ import annotations

from app.graph.node_utils import emit_complete, emit_start, get_runtime
from app.graph.state import AgentState


async def load_conversation_history(state: AgentState, config) -> AgentState:
    node_name = "Load Conversation History"
    await emit_start(config, node_name)
    runtime = get_runtime(config)
    with runtime.session_factory() as db:
        runtime.memory_service.get_or_create_session(
            db,
            session_id=runtime.session_id,
            user_id=runtime.user_id,
            project_id=state.get("project_id"),
        )
        history = runtime.memory_service.load_history(
            db,
            session_id=runtime.session_id,
            user_id=runtime.user_id,
        )
        project_context = runtime.memory_service.load_project_context(
            db,
            session_id=runtime.session_id,
            user_id=runtime.user_id,
        )
    await emit_complete(config, node_name, f"Loaded {len(history)} prior messages")
    return {
        "conversation_history": history,
        "project_context": project_context,
        "retry_count": state.get("retry_count", 0),
    }
