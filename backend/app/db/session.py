from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.core.security import hash_password
from app.core.encryption import encrypt_text
from app.db.base import Base
from app.models.audit import AuditLog
from app.models.conversation import ConversationMessage, ConversationSession
from app.models.pipeline import PipelineRun, PipelineStepLog, ToolInvocationLog
from app.models.project import Project
from app.models.report import Report
from app.models.upload import KnowledgeBaseDocument, Upload
from app.models.user import RefreshToken, User

settings = get_settings()
engine = create_engine(
    settings.database_url,
    future=True,
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def create_db_and_seed() -> None:
    Base.metadata.create_all(bind=engine)
    _apply_project_schema_updates()
    _create_append_only_trigger()

    with SessionLocal() as session:
        admin = session.query(User).filter(User.email == settings.admin_email).first()
        if not admin:
            session.add(
                User(
                    email=settings.admin_email,
                    full_name=settings.admin_full_name,
                    password_hash=hash_password(settings.admin_password),
                    role="admin",
                    mfa_enabled=False,
                    must_enroll_mfa=True,
                    is_active=True,
                )
            )
            session.commit()
        _ensure_default_projects(session)
        _encrypt_legacy_upload_text(session)


def _encrypt_legacy_upload_text(session: Session) -> None:
    changed = False
    for upload in session.query(Upload).filter(Upload.extracted_text.is_not(None)).all():
        metadata = dict(upload.metadata_json or {})
        if metadata.get("extracted_text_encrypted"):
            continue
        upload.extracted_text = encrypt_text(upload.extracted_text or "")
        metadata["extracted_text_encrypted"] = True
        upload.metadata_json = metadata
        session.add(upload)
        changed = True
    if changed:
        session.commit()


def _apply_project_schema_updates() -> None:
    statements = [
        "ALTER TABLE users ALTER COLUMN mfa_secret TYPE TEXT;",
        """
        CREATE TABLE IF NOT EXISTS projects (
            id VARCHAR(36) PRIMARY KEY,
            owner_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name VARCHAR(160) NOT NULL,
            description TEXT NULL,
            domain_name VARCHAR(120) NOT NULL DEFAULT 'supplier_compliance',
            shared_context_notes TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """,
        """
        ALTER TABLE conversation_sessions
        ADD COLUMN IF NOT EXISTS project_id VARCHAR(36) REFERENCES projects(id) ON DELETE SET NULL;
        """,
        """
        ALTER TABLE uploads
        ADD COLUMN IF NOT EXISTS project_id VARCHAR(36) REFERENCES projects(id) ON DELETE SET NULL;
        """,
        """
        ALTER TABLE uploads
        ADD COLUMN IF NOT EXISTS ingestion_status VARCHAR(40) NOT NULL DEFAULT 'ready';
        """,
        """
        ALTER TABLE uploads
        ADD COLUMN IF NOT EXISTS extraction_method VARCHAR(40) NULL;
        """,
        """
        ALTER TABLE uploads
        ADD COLUMN IF NOT EXISTS extraction_message TEXT NULL;
        """,
        """
        ALTER TABLE uploads
        ADD COLUMN IF NOT EXISTS error_message TEXT NULL;
        """,
        """
        UPDATE uploads
        SET ingestion_status = 'ready_for_visual_review',
            extraction_method = COALESCE(extraction_method, 'vision'),
            extraction_message = COALESCE(
                extraction_message,
                'Image attached successfully and ready for visual review.'
            )
        WHERE mime_type LIKE 'image/%'
          AND ingestion_status = 'ready'
          AND extracted_text IS NULL;
        """,
        """
        UPDATE uploads
        SET ingestion_status = 'needs_ocr',
            extraction_method = COALESCE(extraction_method, 'ocr'),
            extraction_message = COALESCE(
                extraction_message,
                'This PDF appears to be scanned and needs OCR before its text can be searched.'
            )
        WHERE mime_type = 'application/pdf'
          AND ingestion_status = 'ready'
          AND (extracted_text IS NULL OR BTRIM(extracted_text) = '');
        """,
        """
        UPDATE uploads
        SET extraction_method = COALESCE(extraction_method, 'native'),
            extraction_message = COALESCE(
                extraction_message,
                'Text extracted successfully and ready for project questions.'
            )
        WHERE ingestion_status = 'ready'
          AND extracted_text IS NOT NULL
          AND BTRIM(extracted_text) <> '';
        """,
        """
        ALTER TABLE reports
        ADD COLUMN IF NOT EXISTS project_id VARCHAR(36) REFERENCES projects(id) ON DELETE SET NULL;
        """,
        "CREATE INDEX IF NOT EXISTS ix_projects_owner_id ON projects (owner_id);",
        "CREATE INDEX IF NOT EXISTS ix_conversation_sessions_project_id ON conversation_sessions (project_id);",
        "CREATE INDEX IF NOT EXISTS ix_uploads_project_id ON uploads (project_id);",
        "CREATE INDEX IF NOT EXISTS ix_reports_project_id ON reports (project_id);",
    ]
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def _ensure_default_projects(session: Session) -> None:
    users = session.query(User).all()
    changed = False

    for user in users:
        project = (
            session.query(Project)
            .filter(Project.owner_id == user.id, Project.name == "General Workspace")
            .order_by(Project.created_at.asc())
            .first()
        )
        if not project:
            project = Project(
                owner_id=user.id,
                name="General Workspace",
                description="Default workspace for chats, files, and shared project memory.",
                domain_name="supplier_compliance",
            )
            session.add(project)
            session.flush()
            changed = True

        session_rows = (
            session.query(ConversationSession)
            .filter(ConversationSession.user_id == user.id, ConversationSession.project_id.is_(None))
            .all()
        )
        for row in session_rows:
            row.project_id = project.id
            session.add(row)
            changed = True

        upload_rows = session.query(Upload).filter(Upload.owner_id == user.id, Upload.project_id.is_(None)).all()
        for row in upload_rows:
            row.project_id = project.id
            session.add(row)
            changed = True

        report_rows = session.query(Report).filter(Report.user_id == user.id, Report.project_id.is_(None)).all()
        for row in report_rows:
            row.project_id = project.id
            session.add(row)
            changed = True

    if changed:
        session.commit()


def _create_append_only_trigger() -> None:
    statements = [
        """
        CREATE OR REPLACE FUNCTION prevent_audit_logs_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_logs is append-only';
        END;
        $$ LANGUAGE plpgsql;
        """,
        """
        DROP TRIGGER IF EXISTS audit_logs_no_update ON audit_logs;
        """,
        """
        CREATE TRIGGER audit_logs_no_update
        BEFORE UPDATE ON audit_logs
        FOR EACH ROW
        EXECUTE FUNCTION prevent_audit_logs_mutation();
        """,
        """
        DROP TRIGGER IF EXISTS audit_logs_no_delete ON audit_logs;
        """,
        """
        CREATE TRIGGER audit_logs_no_delete
        BEFORE DELETE ON audit_logs
        FOR EACH ROW
        EXECUTE FUNCTION prevent_audit_logs_mutation();
        """,
    ]
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
