from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException, Request
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import reports as reports_route
from app.api.schemas import GenerateReportRequest
from app.db.base import Base
from app.models.conversation import ConversationSession
from app.models.project import Project
from app.models.report import Report
from app.models.upload import Upload
from app.models.user import User
from app.services.pipeline_log_service import PipelineLogService


def _request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/", "headers": [], "client": ("test", 1)})


def _structured_report() -> dict:
    return {
        "executive_summary": "One supported gap requires attention.",
        "disclaimer": "This is a preparation report, not a certification.",
        "findings": [
            {
                "category": "Health and Safety",
                "verdict": "Minor",
                "standard_name": "Buyer code",
                "clause_reference": "H&S 1",
                "evidence_summary": "The uploaded inspection record is incomplete.",
                "remediation": "Complete and approve the inspection record.",
                "confidence": "High",
                "references": [],
            }
        ],
        "next_best_questions": ["Who owns the corrective action?"],
        "recommended_actions": ["Complete the record."],
        "current_web_findings": [],
    }


@pytest.fixture()
def report_db(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    monkeypatch.setattr(reports_route, "SessionLocal", factory)
    monkeypatch.setattr(reports_route, "pipeline_log_service", PipelineLogService(factory))

    owner_id = str(uuid4())
    other_id = str(uuid4())
    project_id = str(uuid4())
    session_id = str(uuid4())
    upload_id = str(uuid4())
    with factory() as db:
        owner = User(id=owner_id, email="owner@example.com", full_name="Owner", password_hash="hash")
        other = User(id=other_id, email="other@example.com", full_name="Other", password_hash="hash")
        project = Project(id=project_id, owner_id=owner_id, name="Factory Review")
        session = ConversationSession(id=session_id, user_id=owner_id, project_id=project_id, title="Review")
        upload = Upload(
            id=upload_id,
            owner_id=owner_id,
            project_id=project_id,
            session_id=session_id,
            original_filename="inspection.txt",
            stored_path="encrypted.bin",
            mime_type="text/plain",
            size_bytes=100,
            sha256="a" * 64,
            extracted_text="Inspection evidence",
            ingestion_status="ready",
            extraction_method="native",
            extraction_message="Ready",
        )
        db.add_all([owner, other, project, session, upload])
        db.commit()

    return factory, owner_id, other_id, session_id, upload_id


def test_generate_report_is_scoped_and_persisted(report_db, monkeypatch) -> None:
    factory, owner_id, _other_id, session_id, upload_id = report_db
    report_payload = _structured_report()
    graph_report_id = str(uuid4())

    class FakeGraph:
        async def ainvoke(self, state, config):
            assert state["attachment_contexts"][0]["upload_id"] == upload_id
            assert config["configurable"]["runtime"].user_id == owner_id
            # The real save-conversation node commits the report before the
            # endpoint receives the graph result.
            with factory() as graph_db:
                session = graph_db.get(ConversationSession, session_id)
                graph_db.add(
                    Report(
                        id=graph_report_id,
                        project_id=session.project_id,
                        session_id=session_id,
                        user_id=owner_id,
                        original_query=state["original_query"],
                        rewritten_query="grounded readiness report",
                        response_text="# Report",
                        structured_report_json=report_payload,
                        response_status="completed",
                    )
                )
                graph_db.commit()
            return {
                "final_response": "# Report",
                "final_report": report_payload,
                "final_report_id": graph_report_id,
                "response_status": "completed",
                "rewritten_query": "grounded readiness report",
            }

    monkeypatch.setattr(reports_route, "report_generation_graph", FakeGraph())
    with factory() as db:
        owner = db.get(User, owner_id)
        response = asyncio.run(
            reports_route.generate_session_report(
                session_id,
                GenerateReportRequest(query="Focus on safety", attachment_ids=[upload_id]),
                db,
                _request(),
                owner,
            )
        )

        assert response["status"] == "generated"
        assert response["structured_report"] == report_payload
        persisted = db.get(Report, response["report_id"])
        assert persisted is not None
        assert persisted.user_id == owner_id
        assert persisted.session_id == session_id
        assert persisted.response_status == "generated"


def test_generate_report_hides_another_users_session(report_db) -> None:
    factory, _owner_id, other_id, session_id, _upload_id = report_db
    with factory() as db:
        other = db.get(User, other_id)
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(
                reports_route.generate_session_report(
                    session_id,
                    GenerateReportRequest(),
                    db,
                    _request(),
                    other,
                )
            )
    assert exc_info.value.status_code == 404


def test_generate_report_returns_clear_insufficient_evidence(report_db, monkeypatch) -> None:
    factory, owner_id, _other_id, session_id, upload_id = report_db

    class FakeGraph:
        async def ainvoke(self, _state, config):
            assert config["configurable"]["runtime"].session_id == session_id
            return {
                "final_response": "The uploaded record does not include payroll evidence.",
                "final_report": None,
                "response_status": "insufficient_coverage",
                "evaluator_feedback": "Upload payroll and overtime records.",
                "cross_reference_result": {"missing_evidence": ["Signed payroll record"]},
            }

    monkeypatch.setattr(reports_route, "report_generation_graph", FakeGraph())
    with factory() as db:
        owner = db.get(User, owner_id)
        response = asyncio.run(
            reports_route.generate_session_report(
                session_id,
                GenerateReportRequest(attachment_ids=[upload_id]),
                db,
                _request(),
                owner,
            )
        )
        reports = db.query(Report).filter(Report.session_id == session_id).all()

    assert response == {
        "status": "insufficient_evidence",
        "detail": "The uploaded record does not include payroll evidence.",
        "missing_evidence": ["Signed payroll record", "Upload payroll and overtime records."],
    }
    assert len(reports) == 1
    assert reports[0].response_status == "insufficient_evidence"
    assert reports[0].structured_report_json is None


def test_download_report_supports_browser_formats_and_owner_check(report_db, monkeypatch, tmp_path) -> None:
    factory, owner_id, other_id, session_id, _upload_id = report_db
    report_id = str(uuid4())
    with factory() as db:
        session = db.get(ConversationSession, session_id)
        db.add(
            Report(
                id=report_id,
                project_id=session.project_id,
                session_id=session_id,
                user_id=owner_id,
                original_query="Generate report",
                response_text="# Report",
                structured_report_json=_structured_report(),
                response_status="generated",
            )
        )
        db.commit()

    monkeypatch.setattr(reports_route.report_service.settings, "report_dir", tmp_path)
    with factory() as db:
        owner = db.get(User, owner_id)
        expected_media_types = {
            "pdf": "application/pdf",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "csv": "text/csv; charset=utf-8",
        }
        for file_format, media_type in expected_media_types.items():
            response = reports_route.download_report(report_id, db, _request(), owner, file_format)
            assert Path(response.path).exists()
            assert response.media_type == media_type

        other = db.get(User, other_id)
        with pytest.raises(HTTPException) as exc_info:
            reports_route.download_report(report_id, db, _request(), other, "csv")
        assert exc_info.value.status_code == 404
