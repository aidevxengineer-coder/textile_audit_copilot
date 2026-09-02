from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import sessionmaker

from app.models.pipeline import PipelineRun, PipelineStepLog, ToolInvocationLog


class PipelineLogService:
    def __init__(self, session_factory: sessionmaker) -> None:
        self.session_factory = session_factory

    def start_run(
        self,
        *,
        session_id: str,
        project_id: str | None,
        user_id: str,
        original_query: str,
    ) -> str:
        with self.session_factory() as db:
            run = PipelineRun(
                session_id=session_id,
                project_id=project_id,
                user_id=user_id,
                original_query=original_query,
                status="running",
            )
            db.add(run)
            db.commit()
            db.refresh(run)
            return run.id

    def log_step(self, *, run_id: str | None, node_name: str, status: str, detail: str | None = None) -> None:
        if not run_id:
            return
        with self.session_factory() as db:
            db.add(PipelineStepLog(run_id=run_id, node_name=node_name, status=status, detail=detail))
            db.commit()

    def log_tool(
        self,
        *,
        run_id: str | None,
        tool_name: str,
        tool_kind: str,
        status: str,
        arguments: dict[str, Any] | None = None,
        result_preview: str | None = None,
    ) -> None:
        if not run_id:
            return
        with self.session_factory() as db:
            db.add(
                ToolInvocationLog(
                    run_id=run_id,
                    tool_name=tool_name,
                    tool_kind=tool_kind,
                    status=status,
                    arguments_json=arguments or {},
                    result_preview=(result_preview or "")[:1000] or None,
                )
            )
            db.commit()

    def complete_run(self, *, run_id: str | None, status: str, error_detail: str | None = None) -> None:
        if not run_id:
            return
        with self.session_factory() as db:
            run = db.get(PipelineRun, run_id)
            if not run:
                return
            run.status = status
            run.error_detail = error_detail
            run.completed_at = datetime.now(UTC)
            db.add(run)
            db.commit()
