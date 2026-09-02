from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.core.events import PipelineEmitter
from app.graph.nodes.safe_response import safe_response


def test_safe_response_streams_visible_tokens_before_completion() -> None:
    events: list[dict] = []

    async def record(event: dict) -> None:
        events.append(event)

    runtime = SimpleNamespace(
        emitter=PipelineEmitter(emit=record),
        pipeline_log_service=None,
        run_id="safe-response-test",
    )
    result = asyncio.run(
        safe_response(
            {"evaluator_feedback": "Upload a current fire-safety inspection record."},
            {"configurable": {"runtime": runtime}},
        )
    )

    assert events[0]["type"] == "stage"
    assert events[0]["status"] == "started"
    assert events[-1]["type"] == "stage"
    assert events[-1]["status"] == "completed"

    token_events = [event for event in events if event["type"] == "token"]
    assert token_events
    assert "".join(event["value"] for event in token_events) == result["final_response"]
    assert max(events.index(event) for event in token_events) < len(events) - 1
    assert result["response_status"] == "insufficient_coverage"
