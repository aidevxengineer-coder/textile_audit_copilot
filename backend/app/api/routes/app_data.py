from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.schemas import ProjectCreateRequest, SessionCreateRequest
from app.auth.dependencies import get_current_user
from app.core.audit import log_audit_event
from app.core.encryption import read_encrypted_file
from app.config import get_settings
from app.db.session import get_db
from app.models.conversation import ConversationSession
from app.models.project import Project
from app.models.report import Report
from app.models.upload import Upload
from app.models.user import User
from app.services.memory_service import MemoryService
from app.services.upload_service import UploadService, UploadValidationError


router = APIRouter(prefix="/api", tags=["app"])
memory_service = MemoryService()
upload_service = UploadService()


def _serialize_project(project: Project, *, session_count: int, upload_count: int) -> dict:
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "domain_name": project.domain_name,
        "shared_context_notes": project.shared_context_notes,
        "session_count": session_count,
        "upload_count": upload_count,
        "updated_at": project.updated_at.isoformat(),
    }


def _serialize_session(session: ConversationSession) -> dict:
    return {
        "id": session.id,
        "project_id": session.project_id,
        "title": session.title,
        "updated_at": session.updated_at.isoformat(),
    }


def _get_or_create_default_project(db: Session, user: User) -> Project:
    project = (
        db.query(Project)
        .filter(Project.owner_id == user.id)
        .order_by(Project.updated_at.desc(), Project.created_at.desc())
        .first()
    )
    if project:
        return project

    project = Project(
        id=str(uuid4()),
        owner_id=user.id,
        name="General Workspace",
        description="Default workspace for chats, files, and shared project memory.",
        domain_name="supplier_compliance",
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def _resolve_project(db: Session, user: User, project_id: str | None) -> Project:
    if not project_id:
        return _get_or_create_default_project(db, user)
    project = db.get(Project, project_id)
    if not project or project.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found.")
    return project


def _get_user_session(db: Session, session_id: str, user: User) -> ConversationSession:
    session = db.get(ConversationSession, session_id)
    if not session or session.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")
    return session


def _get_user_upload(db: Session, upload_id: str, user: User) -> Upload:
    upload = (
        db.query(Upload)
        .filter(Upload.id == upload_id, Upload.owner_id == user.id)
        .first()
    )
    if not upload:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload not found.")
    return upload


def _serialize_upload(upload: Upload) -> dict:
    return upload_service.serialize_upload(upload)


def _build_session_export_markdown(
    *,
    session: ConversationSession,
    messages: list[dict],
    uploads: list[Upload],
    latest_report: Report | None,
) -> str:
    lines = [
        f"# {session.title}",
        "",
        f"- Session ID: `{session.id}`",
        f"- Project ID: `{session.project_id or 'none'}`",
        f"- Created: {session.created_at.isoformat()}",
        f"- Updated: {session.updated_at.isoformat()}",
        "",
        "## Uploaded Evidence",
    ]
    if uploads:
        for upload in uploads:
            document_type = (upload.metadata_json or {}).get("document_type") or "general"
            lines.append(f"- {upload.original_filename} ({upload.mime_type}, {document_type})")
    else:
        lines.append("- No uploaded files")

    lines.extend(["", "## Conversation"])
    for message in messages:
        lines.append(f"### {message['role'].title()}")
        lines.append(message["content"])
        attachments = message.get("attachments", [])
        if attachments:
            lines.append("")
            lines.append("Attachments:")
            for attachment in attachments:
                lines.append(f"- {attachment.get('file_name') or attachment.get('upload_id')}")
        lines.append("")

    if latest_report and latest_report.structured_report_json:
        lines.extend(["## Latest Structured Report", "", latest_report.response_text])

    return "\n".join(lines).strip() + "\n"


@router.get("/health")
def health() -> dict:
    settings = get_settings()
    vision_model = (
        settings.groq_vision_model
        if settings.vision_provider.lower() == "groq"
        else settings.ollama_vision_model
    )
    return {
        "status": "ok",
        "text_provider": settings.ai_provider,
        "text_model": settings.groq_text_model if settings.ai_provider.lower() == "groq" else settings.ollama_text_model,
        "vision_provider": settings.vision_provider,
        "vision_model": vision_model,
        "vision_fallback_provider": settings.vision_fallback_provider,
    }


@router.post("/projects")
def create_project(
    payload: ProjectCreateRequest,
    db: Annotated[Session, Depends(get_db)],
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> dict:
    project = Project(
        id=str(uuid4()),
        owner_id=user.id,
        name=payload.name,
        description=payload.description,
        domain_name=payload.domain_name,
        shared_context_notes=payload.shared_context_notes,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    log_audit_event(
        db,
        actor_user_id=user.id,
        action="project_created",
        resource_type="project",
        resource_id=project.id,
        ip_address=request.client.host if request.client else None,
        metadata={"domain_name": project.domain_name},
    )
    return _serialize_project(project, session_count=0, upload_count=0)


@router.get("/projects")
def list_projects(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> list[dict]:
    projects = (
        db.query(Project)
        .filter(Project.owner_id == user.id)
        .order_by(Project.updated_at.desc(), Project.created_at.desc())
        .all()
    )
    if not projects:
        project = _get_or_create_default_project(db, user)
        projects = [project]

    results = []
    for project in projects:
        session_count = (
            db.query(ConversationSession)
            .filter(ConversationSession.project_id == project.id, ConversationSession.user_id == user.id)
            .count()
        )
        upload_count = db.query(Upload).filter(Upload.project_id == project.id, Upload.owner_id == user.id).count()
        results.append(_serialize_project(project, session_count=session_count, upload_count=upload_count))
    return results


@router.get("/projects/{project_id}")
def get_project(
    project_id: str,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict:
    project = _resolve_project(db, user, project_id)
    sessions = (
        db.query(ConversationSession)
        .filter(ConversationSession.project_id == project.id, ConversationSession.user_id == user.id)
        .order_by(ConversationSession.updated_at.desc())
        .all()
    )
    uploads = (
        db.query(Upload)
        .filter(Upload.project_id == project.id, Upload.owner_id == user.id)
        .order_by(Upload.created_at.desc())
        .limit(20)
        .all()
    )
    return {
        **_serialize_project(project, session_count=len(sessions), upload_count=len(uploads)),
        "sessions": [_serialize_session(session) for session in sessions],
        "uploads": [_serialize_upload(upload) for upload in uploads],
    }


@router.post("/sessions")
def create_session(
    payload: SessionCreateRequest,
    db: Annotated[Session, Depends(get_db)],
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> dict:
    project = _resolve_project(db, user, payload.project_id)
    session = ConversationSession(id=str(uuid4()), user_id=user.id, project_id=project.id, title=payload.title)
    db.add(session)
    project.updated_at = datetime.now(UTC)
    db.add(project)
    db.commit()
    db.refresh(session)
    log_audit_event(
        db,
        actor_user_id=user.id,
        action="session_created",
        resource_type="conversation_session",
        resource_id=session.id,
        ip_address=request.client.host if request.client else None,
        metadata={"title": session.title, "project_id": session.project_id},
    )
    return {
        "id": session.id,
        "project_id": session.project_id,
        "title": session.title,
        "created_at": session.created_at.isoformat(),
    }


@router.get("/sessions")
def list_sessions(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    project_id: Annotated[str | None, Query()] = None,
) -> list[dict]:
    query = db.query(ConversationSession).filter(ConversationSession.user_id == user.id)
    if project_id:
        query = query.filter(ConversationSession.project_id == project_id)
    rows = query.order_by(ConversationSession.updated_at.desc()).all()
    return [_serialize_session(row) for row in rows]


@router.get("/sessions/{session_id}")
def get_session(
    session_id: str,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict:
    session = _get_user_session(db, session_id, user)
    messages = memory_service.load_history(db, session_id=session_id, user_id=user.id)
    uploads = db.query(Upload).filter(Upload.session_id == session_id, Upload.owner_id == user.id).all()
    project = _resolve_project(db, user, session.project_id)
    latest_report = (
        db.query(Report)
        .filter(Report.session_id == session_id, Report.user_id == user.id)
        .order_by(Report.created_at.desc())
        .first()
    )
    safe_messages = []
    for message in messages:
        safe_messages.append(
            {
                "role": message["role"],
                "content": message["content"],
                "attachments": [
                    {
                        "upload_id": attachment.get("upload_id"),
                        "file_name": attachment.get("file_name"),
                        "mime_type": attachment.get("mime_type"),
                    }
                    for attachment in message.get("attachments", [])
                ],
            }
        )
    return {
        "id": session.id,
        "project_id": session.project_id,
        "title": session.title,
        "project": {
            "id": project.id,
            "name": project.name,
            "domain_name": project.domain_name,
            "description": project.description,
            "shared_context_notes": project.shared_context_notes,
        },
        "messages": safe_messages,
        "uploads": [_serialize_upload(upload) for upload in uploads],
        "project_context": memory_service.load_project_context(db, session_id=session_id, user_id=user.id),
        "latest_report": latest_report.structured_report_json if latest_report else None,
        "latest_report_id": latest_report.id if latest_report else None,
    }


@router.delete("/sessions/{session_id}")
def delete_session(
    session_id: str,
    db: Annotated[Session, Depends(get_db)],
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> dict:
    session = _get_user_session(db, session_id, user)
    db.delete(session)
    db.commit()
    log_audit_event(
        db,
        actor_user_id=user.id,
        action="session_deleted",
        resource_type="conversation_session",
        resource_id=session_id,
        ip_address=request.client.host if request.client else None,
        metadata={"project_id": session.project_id},
    )
    return {"status": "deleted"}


@router.get("/sessions/{session_id}/export")
def export_session_transcript(
    session_id: str,
    db: Annotated[Session, Depends(get_db)],
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> dict:
    session = _get_user_session(db, session_id, user)
    messages = memory_service.load_history(db, session_id=session_id, user_id=user.id)
    uploads = db.query(Upload).filter(Upload.session_id == session_id, Upload.owner_id == user.id).all()
    latest_report = (
        db.query(Report)
        .filter(Report.session_id == session_id, Report.user_id == user.id)
        .order_by(Report.created_at.desc())
        .first()
    )
    transcript = _build_session_export_markdown(
        session=session,
        messages=messages,
        uploads=uploads,
        latest_report=latest_report,
    )
    log_audit_event(
        db,
        actor_user_id=user.id,
        action="session_exported",
        resource_type="conversation_session",
        resource_id=session_id,
        ip_address=request.client.host if request.client else None,
        metadata={"project_id": session.project_id},
    )
    file_stem = session.title.lower().replace(" ", "-")[:40] or "chat-export"
    return {"file_name": f"{file_stem}.md", "transcript_markdown": transcript}


@router.post("/uploads")
async def upload_file(
    session_id: str,
    request: Request,
    file: Annotated[UploadFile, File(...)],
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict:
    session = _get_user_session(db, session_id, user)

    project_file_count = db.query(Upload).filter(Upload.project_id == session.project_id, Upload.owner_id == user.id).count()
    project_storage = (
        db.query(func.coalesce(func.sum(Upload.size_bytes), 0))
        .filter(Upload.project_id == session.project_id, Upload.owner_id == user.id)
        .scalar()
    ) or 0
    if project_file_count >= upload_service.settings.max_project_files:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Project file limit reached.")

    max_file_bytes = upload_service.settings.max_upload_mb * 1024 * 1024
    chunks: list[bytes] = []
    received = 0
    while chunk := await file.read(1024 * 1024):
        received += len(chunk)
        if received > max_file_bytes:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="File exceeds upload limit.")
        chunks.append(chunk)
    raw_bytes = b"".join(chunks)
    project_limit = upload_service.settings.max_project_storage_mb * 1024 * 1024
    if project_storage + len(raw_bytes) > project_limit:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Project storage limit reached.")
    try:
        upload = upload_service.persist_upload(
            db,
            owner_id=user.id,
            project_id=session.project_id,
            session_id=session_id,
            filename=file.filename or "upload.bin",
            mime_type=file.content_type or "application/octet-stream",
            raw_bytes=raw_bytes,
        )
    except UploadValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    log_audit_event(
        db,
        actor_user_id=user.id,
        action="upload_created",
        resource_type="upload",
        resource_id=upload.id,
        ip_address=request.client.host if request.client else None,
        metadata={"session_id": session_id, "project_id": session.project_id, "mime_type": upload.mime_type},
    )
    return _serialize_upload(upload)


@router.get("/uploads/{upload_id}")
def get_upload_detail(
    upload_id: str,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict:
    return _serialize_upload(_get_user_upload(db, upload_id, user))


@router.get("/uploads/{upload_id}/preview")
def preview_upload(
    upload_id: str,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> Response:
    upload = _get_user_upload(db, upload_id, user)
    previewable = upload.mime_type.startswith("image/") or upload.mime_type in {
        "application/pdf",
        "text/plain",
        "text/csv",
        "application/csv",
    }
    if not previewable:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="This file type can be downloaded, but it cannot be previewed in the browser.",
        )

    payload = read_encrypted_file(Path(upload.stored_path))
    safe_name = quote(upload.original_filename, safe="")
    headers = {
        "Content-Disposition": f"inline; filename*=UTF-8''{safe_name}",
        "Cache-Control": "private, max-age=60",
        "Content-Security-Policy": "sandbox",
        "X-Content-Type-Options": "nosniff",
    }
    return Response(content=payload, media_type=upload.mime_type, headers=headers)


@router.get("/uploads/{upload_id}/download")
def download_upload(
    upload_id: str,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> Response:
    upload = _get_user_upload(db, upload_id, user)

    payload = read_encrypted_file(Path(upload.stored_path))
    safe_name = quote(upload.original_filename, safe="")
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{safe_name}",
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    }
    return Response(content=payload, media_type=upload.mime_type, headers=headers)
