from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.audit import AuditLog  # noqa: F401 - registers metadata
from app.models.conversation import ConversationSession
from app.models.pipeline import PipelineRun, PipelineStepLog, ToolInvocationLog
from app.models.project import Project  # noqa: F401 - registers metadata
from app.models.report import Report  # noqa: F401 - registers metadata
from app.models.upload import KnowledgeBaseDocument, Upload  # noqa: F401 - registers metadata
from app.models.user import RefreshToken, User
from app.services.pipeline_log_service import PipelineLogService


def test_pipeline_run_steps_and_tools_are_persisted_in_normalized_tables(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'pipeline.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    with factory() as db:
        user = User(
            email="logger@example.test",
            full_name="Pipeline Logger",
            password_hash="not-used-in-this-test",
            role="factory_user",
            is_active=True,
            mfa_enabled=False,
            must_enroll_mfa=False,
        )
        db.add(user)
        db.flush()
        session = ConversationSession(user_id=user.id, title="Logging test")
        db.add(session)
        db.commit()
        user_id, session_id = user.id, session.id

    service = PipelineLogService(factory)
    run_id = service.start_run(
        session_id=session_id,
        project_id=None,
        user_id=user_id,
        original_query="Check fire safety evidence",
    )
    service.log_step(run_id=run_id, node_name="Retrieve Documents", status="started")
    service.log_step(run_id=run_id, node_name="Retrieve Documents", status="completed", detail="8 clauses")
    service.log_tool(
        run_id=run_id,
        tool_name="web_search_mcp",
        tool_kind="mcp",
        status="completed",
        arguments={"query": "latest fire safety rules"},
        result_preview="one result",
    )
    service.complete_run(run_id=run_id, status="completed")

    with factory() as db:
        run = db.get(PipelineRun, run_id)
        steps = db.scalars(select(PipelineStepLog).where(PipelineStepLog.run_id == run_id)).all()
        tools = db.scalars(select(ToolInvocationLog).where(ToolInvocationLog.run_id == run_id)).all()
        assert run is not None and run.status == "completed" and run.completed_at is not None
        assert [(step.node_name, step.status) for step in steps] == [
            ("Retrieve Documents", "started"),
            ("Retrieve Documents", "completed"),
        ]
        assert len(tools) == 1
        assert tools[0].arguments_json == {"query": "latest fire safety rules"}
