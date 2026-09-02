from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.schemas import DraftEmailRequest, EmailAttachmentRequest, GenerateDocumentRequest, WhatsAppMessageRequest
from app.auth.dependencies import get_current_user, require_role
from app.core.audit import log_audit_event
from app.db.session import get_db
from app.mcp.service import MCPIntegrationError, MCPService
from app.models.user import User

router = APIRouter(prefix="/api/integrations", tags=["integrations"])
mcp_service = MCPService()


def _audit(db: Session, request: Request, user: User, action: str, metadata: dict | None = None) -> None:
    log_audit_event(db, actor_user_id=user.id, action=action, resource_type="mcp", resource_id=None,
                    ip_address=request.client.host if request.client else None, metadata=metadata or {})


@router.get("/mcp/status")
async def mcp_status(user: Annotated[User, Depends(require_role("admin"))]) -> dict:
    return await mcp_service.health()


@router.post("/documents/generate")
async def generate_document(payload: GenerateDocumentRequest, request: Request,
                            db: Annotated[Session, Depends(get_db)],
                            user: Annotated[User, Depends(get_current_user)]) -> dict:
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(payload.filename).name).strip(".-") or "document"
    try:
        result = await mcp_service.generate_document(format=payload.format, title=payload.title,
                                                     content=payload.content, filename=f"{user.id}-{safe_name}")
    except MCPIntegrationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit(db, request, user, "mcp_document_generated", {"format": payload.format, "filename": safe_name})
    return {"status": "generated", "result": result}


@router.post("/email/draft")
async def draft_email(payload: DraftEmailRequest, request: Request,
                      db: Annotated[Session, Depends(get_db)],
                      user: Annotated[User, Depends(require_role("admin"))]) -> dict:
    try:
        result = await mcp_service.draft_email(recipient=str(payload.recipient), subject=payload.subject,
                                               body=payload.body, attachments=payload.attachment_paths)
    except MCPIntegrationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit(db, request, user, "mcp_email_drafted", {"recipient": str(payload.recipient), "subject": payload.subject})
    return {"status": "drafted", "result": result}


@router.get("/email/messages")
async def list_messages(request: Request, db: Annotated[Session, Depends(get_db)],
                        user: Annotated[User, Depends(require_role("admin"))],
                        limit: Annotated[int, Query(ge=1, le=50)] = 10) -> dict:
    try:
        result = await mcp_service.list_email_attachments(limit=limit)
    except MCPIntegrationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit(db, request, user, "mcp_email_listed", {"limit": limit})
    return {"result": result}


@router.post("/email/attachments/download")
async def download_attachment(payload: EmailAttachmentRequest, request: Request,
                              db: Annotated[Session, Depends(get_db)],
                              user: Annotated[User, Depends(require_role("admin"))]) -> dict:
    try:
        result = await mcp_service.download_email_attachment(message_id=payload.message_id,
                                                             attachment_name=payload.attachment_name)
    except MCPIntegrationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit(db, request, user, "mcp_email_attachment_downloaded", {"message_id": payload.message_id,
                                                                  "attachment_name": payload.attachment_name})
    return {"status": "downloaded", "result": result}


@router.get("/whatsapp/messages")
async def list_whatsapp_messages(request: Request, db: Annotated[Session, Depends(get_db)],
                                 user: Annotated[User, Depends(require_role("admin"))],
                                 chat_id: str | None = None,
                                 limit: Annotated[int, Query(ge=1, le=50)] = 20) -> dict:
    try:
        result = await mcp_service.list_whatsapp_messages(chat_id=chat_id, limit=limit)
    except MCPIntegrationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit(db, request, user, "mcp_whatsapp_listed", {"chat_id": chat_id, "limit": limit})
    return {"result": result}


@router.post("/whatsapp/messages")
async def send_whatsapp_message(payload: WhatsAppMessageRequest, request: Request,
                                db: Annotated[Session, Depends(get_db)],
                                user: Annotated[User, Depends(require_role("admin"))]) -> dict:
    try:
        result = await mcp_service.send_whatsapp_message(recipient=payload.recipient, body=payload.body)
    except MCPIntegrationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _audit(db, request, user, "mcp_whatsapp_sent", {"recipient": payload.recipient, "dummy": True})
    return {"status": "simulated", "result": result}
