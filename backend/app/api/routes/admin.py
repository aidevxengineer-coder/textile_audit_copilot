from __future__ import annotations

import json
import subprocess
import sys
import threading
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.schemas import KnowledgeBaseReindexRequest
from app.auth.dependencies import require_role
from app.config import get_settings
from app.core.audit import log_audit_event
from app.db.session import get_db
from app.models.audit import AuditLog
from app.models.pipeline import PipelineRun, PipelineStepLog, ToolInvocationLog
from app.models.upload import KnowledgeBaseDocument
from app.models.user import User
from app.services.upload_service import ALLOWED_MIME_TYPES


router = APIRouter(prefix="/api/admin", tags=["admin"])
settings = get_settings()
_REINDEX_LOCK = threading.Lock()


def _run_ingest(fetch_documents: bool) -> None:
    if not _REINDEX_LOCK.acquire(blocking=False):
        return
    command = [sys.executable, "backend/ingest.py"]
    if not fetch_documents:
        command.append("--skip-fetch")
    try:
        process = subprocess.Popen(command, cwd=Path.cwd(), shell=False)
        process.wait()
    finally:
        _REINDEX_LOCK.release()


@router.get("/knowledge-base/documents")
def knowledge_base_documents(
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(require_role("admin"))],
) -> list[dict]:
    rows = db.query(KnowledgeBaseDocument).order_by(KnowledgeBaseDocument.ingested_at.desc()).all()
    return [
        {
            "id": row.id,
            "title": row.title,
            "standard_name": row.standard_name,
            "citation": row.citation,
            "source_url": row.source_url,
            "version": row.version,
            "ingested_at": row.ingested_at.isoformat(),
        }
        for row in rows
    ]


@router.get("/system-status")
def system_status(
    admin: Annotated[User, Depends(require_role("admin"))],
) -> dict:
    manifest_path = Path("data/source_manifest.json")
    manifest_count = 0
    if manifest_path.exists():
        manifest_count = len(json.loads(manifest_path.read_text(encoding="utf-8")))

    resolved_manifest_path = Path("data/raw/downloads/resolved_manifest.json")
    downloaded_count = 0
    if resolved_manifest_path.exists():
        downloaded_count = len(json.loads(resolved_manifest_path.read_text(encoding="utf-8")))

    return {
        "source_manifest_count": manifest_count,
        "downloaded_source_count": downloaded_count,
        "supported_upload_types": sorted(ALLOWED_MIME_TYPES),
        "mcp_integrations": {
            "filesystem": settings.enable_filesystem_mcp,
            "gmail": settings.enable_gmail_mcp,
            "whatsapp": settings.enable_whatsapp_mcp,
            "web_search": settings.enable_web_search_mcp,
        },
    }


@router.post("/knowledge-base/reindex")
def reindex_knowledge_base(
    payload: KnowledgeBaseReindexRequest,
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
    request: Request,
    admin: Annotated[User, Depends(require_role("admin"))],
) -> dict:
    background_tasks.add_task(_run_ingest, payload.fetch_documents)
    log_audit_event(
        db,
        actor_user_id=admin.id,
        action="knowledge_base_reindex_requested",
        resource_type="knowledge_base",
        resource_id=None,
        ip_address=request.client.host if request.client else None,
        metadata={"fetch_documents": payload.fetch_documents},
    )
    return {"status": "queued"}


@router.get("/audit-logs")
def audit_logs(
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(require_role("admin"))],
) -> list[dict]:
    rows = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(200).all()
    return [
        {
            "id": row.id,
            "actor_user_id": row.actor_user_id,
            "action": row.action,
            "resource_type": row.resource_type,
            "resource_id": row.resource_id,
            "ip_address": row.ip_address,
            "metadata": row.metadata_json,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


@router.get("/pipeline-runs")
def pipeline_runs(
    db: Annotated[Session, Depends(get_db)],
    admin: Annotated[User, Depends(require_role("admin"))],
) -> list[dict]:
    rows = db.query(PipelineRun).order_by(PipelineRun.created_at.desc()).limit(50).all()
    results = []
    for row in rows:
        step_rows = (
            db.query(PipelineStepLog)
            .filter(PipelineStepLog.run_id == row.id)
            .order_by(PipelineStepLog.created_at.asc())
            .all()
        )
        tool_rows = (
            db.query(ToolInvocationLog)
            .filter(ToolInvocationLog.run_id == row.id)
            .order_by(ToolInvocationLog.created_at.asc())
            .all()
        )
        results.append(
            {
                "id": row.id,
                "session_id": row.session_id,
                "project_id": row.project_id,
                "user_id": row.user_id,
                "original_query": row.original_query,
                "status": row.status,
                "error_detail": row.error_detail,
                "created_at": row.created_at.isoformat(),
                "completed_at": row.completed_at.isoformat() if row.completed_at else None,
                "steps": [
                    {
                        "node_name": step.node_name,
                        "status": step.status,
                        "detail": step.detail,
                        "created_at": step.created_at.isoformat(),
                    }
                    for step in step_rows
                ],
                "tools": [
                    {
                        "tool_name": tool.tool_name,
                        "tool_kind": tool.tool_kind,
                        "status": tool.status,
                        "arguments": tool.arguments_json,
                        "result_preview": tool.result_preview,
                        "created_at": tool.created_at.isoformat(),
                    }
                    for tool in tool_rows
                ],
            }
        )
    return results
