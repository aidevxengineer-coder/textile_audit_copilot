from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO
from unittest.mock import MagicMock

import fitz
import pytest
from openpyxl import Workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.conversation import ConversationMessage, ConversationSession
from app.models.project import Project
from app.models.upload import Upload
from app.models.user import User
from app.services.memory_service import MemoryScopeError, MemoryService
from app.services.upload_service import UploadService


XLSX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def test_image_upload_serialization_exposes_visual_review_state() -> None:
    upload = Upload(
        id="upload-1",
        owner_id="user-1",
        project_id="project-1",
        session_id="session-1",
        original_filename="factory-floor.png",
        stored_path="encrypted.bin",
        mime_type="image/png",
        size_bytes=2048,
        sha256="a" * 64,
        extracted_text=None,
        ingestion_status="ready_for_visual_review",
        extraction_method="vision",
        extraction_message="Image attached successfully and ready for visual review.",
        metadata_json={"image_width": 1600, "image_height": 900},
        created_at=datetime(2026, 7, 16, tzinfo=UTC),
    )

    payload = UploadService().serialize_upload(upload)

    assert payload["ingestion_status"] == "ready_for_visual_review"
    assert payload["extraction_status"] == "ready_for_visual_review"
    assert payload["extraction_method"] == "vision"
    assert payload["preview_available"] is True
    assert payload["preview_url"] == "/api/uploads/upload-1/preview"
    assert payload["size_bytes"] == 2048
    assert payload["created_at"] == "2026-07-16T00:00:00+00:00"


def test_scanned_pdf_is_transparently_marked_needs_ocr(tmp_path, monkeypatch) -> None:
    document = fitz.open()
    document.new_page()
    raw_pdf = document.tobytes()
    document.close()

    service = UploadService()
    service.settings.upload_dir = tmp_path
    monkeypatch.setattr(service, "try_ocr_pdf", lambda _payload: None)
    db = MagicMock()
    db.refresh.side_effect = lambda upload: setattr(upload, "id", upload.id or "upload-2")

    upload = service.persist_upload(
        db,
        owner_id="user-1",
        project_id="project-1",
        session_id="session-1",
        filename="scanned.pdf",
        mime_type="application/pdf",
        raw_bytes=raw_pdf,
    )

    assert upload.ingestion_status == "needs_ocr"
    assert upload.extraction_method == "ocr"
    assert upload.extracted_text is None
    assert "needs OCR" in (upload.extraction_message or "")
    assert (tmp_path / "session-1").exists()


def test_xlsx_upload_extracts_sheet_names_and_rows(tmp_path) -> None:
    workbook = Workbook()
    electrical = workbook.active
    electrical.title = "Electrical"
    electrical.append(["Finding", "Status", "Deadline"])
    electrical.append(["Unprotected cable", "Open", "2026-08-15"])
    fire = workbook.create_sheet("Fire")
    fire.append(["Finding", "Status"])
    fire.append(["Blocked exit", "Closed"])
    payload = BytesIO()
    workbook.save(payload)
    workbook.close()

    service = UploadService()
    service.settings.upload_dir = tmp_path
    db = MagicMock()

    upload = service.persist_upload(
        db,
        owner_id="user-1",
        project_id="project-1",
        session_id="session-xlsx",
        filename="factory-cap.xlsx",
        mime_type=XLSX_MIME_TYPE,
        raw_bytes=payload.getvalue(),
    )

    assert upload.ingestion_status == "ready"
    assert upload.extraction_method == "native"
    extracted_text = service.read_extracted_text(upload)
    assert "## Sheet: Electrical" in extracted_text
    assert "[Sheet: Electrical | Row: 1]" in extracted_text
    assert "Unprotected cable | Open | 2026-08-15" in extracted_text
    assert "## Sheet: Fire" in extracted_text
    assert upload.metadata_json["extracted_text_encrypted"] is True
    assert "Unprotected cable" not in upload.extracted_text
    assert upload.metadata_json["sheet_count"] == 2
    assert upload.metadata_json["sheet_names"] == ["Electrical", "Fire"]
    assert upload.metadata_json["spreadsheet_rows_read"] == 4


def test_xlsx_octet_stream_is_normalized_from_filename() -> None:
    service = UploadService()

    assert service.normalize_mime_type("factory-cap.xlsx", "application/octet-stream") == XLSX_MIME_TYPE


def test_memory_is_scoped_to_authenticated_user_and_current_project() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        owner = User(id="user-1", email="owner@example.com", full_name="Owner", password_hash="hash")
        other = User(id="user-2", email="other@example.com", full_name="Other", password_hash="hash")
        project = Project(id="project-1", owner_id=owner.id, name="Project One")
        other_project = Project(id="project-2", owner_id=owner.id, name="Project Two")
        current = ConversationSession(id="session-1", user_id=owner.id, project_id=project.id, title="Current")
        sibling = ConversationSession(id="session-2", user_id=owner.id, project_id=project.id, title="Sibling")
        cross_project = ConversationSession(
            id="session-3",
            user_id=owner.id,
            project_id=other_project.id,
            title="Other project",
        )
        db.add_all([owner, other, project, other_project, current, sibling, cross_project])
        db.flush()
        db.add_all(
            [
                ConversationMessage(session_id=sibling.id, role="assistant", content="Same project memory"),
                ConversationMessage(session_id=cross_project.id, role="assistant", content="Must not leak"),
            ]
        )
        db.commit()

        memory = MemoryService()
        context = memory.load_project_context(db, session_id=current.id, user_id=owner.id)

        assert [row["session_id"] for row in context["related_sessions"]] == [sibling.id]
        assert context["cross_project_sessions"] == []
        with pytest.raises(MemoryScopeError):
            memory.load_history(db, session_id=current.id, user_id=other.id)
        with pytest.raises(MemoryScopeError):
            memory.save_message(
                db,
                session_id=current.id,
                user_id=other.id,
                role="user",
                content="Attempted cross-user write",
            )
