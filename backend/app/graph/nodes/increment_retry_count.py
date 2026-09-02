from __future__ import annotations

from app.graph.node_utils import emit_complete, emit_start
from app.graph.state import AgentState


async def increment_retry_count(state: AgentState, config) -> AgentState:
    node_name = "Increment Retry Count"
    await emit_start(config, node_name)
    retry_count = state.get("retry_count", 0) + 1
    await emit_complete(config, node_name, f"Retry {retry_count}")
    return {"retry_count": retry_count}
