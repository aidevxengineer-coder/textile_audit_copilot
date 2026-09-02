from __future__ import annotations

import re

from app.graph.node_utils import emit_complete, emit_start, get_runtime
from app.graph.state import AgentState


TOKEN_CHUNK_PATTERN = re.compile(r"\S+\s*|\n")


async def safe_response(state: AgentState, config) -> AgentState:
    node_name = "Safe Response"
    await emit_start(config, node_name)
    runtime = get_runtime(config)
    feedback = state.get("evaluator_feedback") or "The retrieved material did not cover the question well enough."
    response = (
        "I could not find enough relevant evidence in this project's files, the local compliance library, "
        "or verified official public sources to answer responsibly. "
        f"Helpful next detail or upload: {feedback}"
    )
    # Safe fallbacks are final user-facing answers too. Emit them through the
    # same token channel as model-generated responses so WebSocket clients can
    # render the answer before the terminal `done` event arrives.
    for token in TOKEN_CHUNK_PATTERN.findall(response):
        await runtime.emitter.token(token)
    await emit_complete(config, node_name, "Returned insufficient-coverage response")
    return {"final_response": response, "response_status": "insufficient_coverage", "final_report": None}
