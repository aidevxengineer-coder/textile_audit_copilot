from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable


EmitFn = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass
class PipelineEmitter:
    emit: EmitFn | None = None

    async def stage(self, node_name: str, status: str, detail: str | None = None) -> None:
        if not self.emit:
            return
        await self.emit(
            {
                "type": "stage",
                "node_name": node_name,
                "status": status,
                "detail": detail,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )

    async def token(self, value: str) -> None:
        if not self.emit:
            return
        await self.emit(
            {
                "type": "token",
                "value": value,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )

    async def done(self, payload: dict[str, Any]) -> None:
        if not self.emit:
            return
        await self.emit(
            {
                "type": "done",
                "payload": payload,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )
