from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.conversation import ConversationMessage, ConversationSession
from app.models.project import Project
from app.models.upload import Upload
from app.services.upload_service import UploadService


class MemoryScopeError(PermissionError):
    """Raised when conversation memory is requested outside its owner/project."""


class MemoryService:
    @staticmethod
    def _owned_session(db: Session, *, session_id: str, user_id: str) -> ConversationSession | None:
        return (
            db.query(ConversationSession)
            .filter(ConversationSession.id == session_id, ConversationSession.user_id == user_id)
            .first()
        )

    @staticmethod
    def _owned_project(db: Session, *, project_id: str, user_id: str) -> Project | None:
        return db.query(Project).filter(Project.id == project_id, Project.owner_id == user_id).first()

    def get_or_create_session(
        self,
        db: Session,
        *,
        session_id: str,
        user_id: str,
        project_id: str | None = None,
    ) -> ConversationSession:
        session = db.get(ConversationSession, session_id)
        if session:
            if session.user_id != user_id:
                raise MemoryScopeError("Conversation memory does not belong to the authenticated user.")
            if project_id and session.project_id != project_id:
                raise MemoryScopeError("Conversation memory does not belong to the requested project.")
            return session
        if project_id and not self._owned_project(db, project_id=project_id, user_id=user_id):
            raise MemoryScopeError("Project does not belong to the authenticated user.")
        session = ConversationSession(
            id=session_id,
            user_id=user_id,
            project_id=project_id,
            title="Factory Audit Session",
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        return session

    def load_history(self, db: Session, *, session_id: str, user_id: str) -> list[dict]:
        if not self._owned_session(db, session_id=session_id, user_id=user_id):
            raise MemoryScopeError("Conversation memory does not belong to the authenticated user.")
        rows = (
            db.query(ConversationMessage)
            .filter(ConversationMessage.session_id == session_id)
            .order_by(ConversationMessage.created_at.asc())
            .all()
        )
        return [
            {"role": row.role, "content": row.content, "attachments": row.attachments_json or []}
            for row in rows
        ]

    def save_message(
        self,
        db: Session,
        *,
        session_id: str,
        user_id: str,
        role: str,
        content: str,
        attachments: list[dict] | None = None,
    ) -> ConversationMessage:
        session = self._owned_session(db, session_id=session_id, user_id=user_id)
        if not session:
            raise MemoryScopeError("Conversation memory does not belong to the authenticated user.")
        message = ConversationMessage(
            session_id=session_id,
            role=role,
            content=content,
            attachments_json=attachments or [],
        )
        db.add(message)
        session.updated_at = datetime.now(UTC)
        db.add(session)
        project = (
            self._owned_project(db, project_id=session.project_id, user_id=user_id)
            if session.project_id
            else None
        )
        if project:
            project.updated_at = session.updated_at
            db.add(project)
        db.commit()
        db.refresh(message)
        return message

    def load_project_uploads(
        self,
        db: Session,
        *,
        session_id: str,
        user_id: str,
        limit: int = 12,
    ) -> list[Upload]:
        session = self._owned_session(db, session_id=session_id, user_id=user_id)
        if not session or not session.project_id:
            return []
        if not self._owned_project(db, project_id=session.project_id, user_id=user_id):
            return []
        return (
            db.query(Upload)
            .filter(Upload.project_id == session.project_id, Upload.owner_id == user_id)
            .order_by(Upload.created_at.desc())
            .limit(limit)
            .all()
        )

    def load_project_context(self, db: Session, *, session_id: str, user_id: str) -> dict:
        session = self._owned_session(db, session_id=session_id, user_id=user_id)
        if not session or not session.project_id:
            return {
                "project": None,
                "shared_uploads": [],
                "related_sessions": [],
                "cross_project_sessions": [],
            }

        project = self._owned_project(db, project_id=session.project_id, user_id=user_id)
        if not project:
            return {
                "project": None,
                "shared_uploads": [],
                "related_sessions": [],
                "cross_project_sessions": [],
            }
        shared_uploads = (
            db.query(Upload)
            .filter(Upload.project_id == session.project_id, Upload.owner_id == user_id)
            .order_by(Upload.created_at.desc())
            .limit(8)
            .all()
        )
        related_sessions = (
            db.query(ConversationSession)
            .filter(
                ConversationSession.project_id == session.project_id,
                ConversationSession.user_id == user_id,
                ConversationSession.id != session_id,
            )
            .order_by(ConversationSession.updated_at.desc())
            .limit(5)
            .all()
        )
        def latest_message_summary(target_session_id: str) -> dict | None:
            row = (
                db.query(ConversationMessage)
                .filter(ConversationMessage.session_id == target_session_id)
                .order_by(ConversationMessage.created_at.desc())
                .first()
            )
            if not row:
                return None
            return {"role": row.role, "content": row.content[:320], "created_at": row.created_at.isoformat()}

        upload_serializer = UploadService()

        def shared_upload_summary(upload: Upload) -> dict:
            serialized = upload_serializer.serialize_upload(upload)
            return {
                "upload_id": upload.id,
                "file_name": upload.original_filename,
                "mime_type": upload.mime_type,
                "document_type": serialized["document_type"],
                "size_bytes": serialized["size_bytes"],
                "created_at": serialized["created_at"],
                "preview_text": serialized["preview_text"],
                "ingestion_status": serialized["ingestion_status"],
                "extraction_method": serialized["extraction_method"],
                "extraction_message": serialized["extraction_message"],
                "error_message": serialized["error_message"],
                "preview_url": serialized["preview_url"],
                "download_url": serialized["download_url"],
            }

        return {
            "project": {
                "id": project.id if project else session.project_id,
                "name": project.name if project else "Project Workspace",
                "description": project.description if project else None,
                "domain_name": project.domain_name if project else None,
                "shared_context_notes": project.shared_context_notes if project else None,
            },
            "shared_uploads": [shared_upload_summary(upload) for upload in shared_uploads],
            "related_sessions": [
                {
                    "session_id": row.id,
                    "title": row.title,
                    "updated_at": row.updated_at.isoformat(),
                    "latest_message": latest_message_summary(row.id),
                }
                for row in related_sessions
            ],
            # Project memory is isolated by default. Cross-project recall must
            # be an explicit future user action, never an automatic prompt input.
            "cross_project_sessions": [],
        }
