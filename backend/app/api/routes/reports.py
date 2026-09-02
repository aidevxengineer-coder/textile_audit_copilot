from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.schemas import ExportReportRequest, GenerateReportRequest, SendEmailRequest
from app.auth.dependencies import get_current_user
from app.core.audit import log_audit_event
from app.core.events import PipelineEmitter
from app.db.session import SessionLocal, get_db
from app.graph.graph import build_graph
from app.graph.runtime import GraphRuntime
from app.mcp.service import MCPIntegrationError, MCPService
from app.models.conversation import ConversationSession
from app.models.report import Report
from app.models.upload import Upload
from app.models.user import User
from app.services.memory_service import MemoryService
from app.services.pipeline_log_service import PipelineLogService
from app.services.report_service import ReportService
from app.services.schemas import ComplianceReport
from app.services.upload_service import UploadService


router = APIRouter(prefix="/api/reports", tags=["reports"])
session_report_router = APIRouter(prefix="/api/sessions", tags=["reports"])
report_service = ReportService()
mcp_service = MCPService()
memory_service = MemoryService()
upload_service = UploadService()
pipeline_log_service = PipelineLogService(SessionLocal)
report_generation_graph = build_graph()

DEFAULT_REPORT_QUERY = (
    "Generate a complete grounded supplier readiness report from this project's evidence. "
    "Identify supported gaps, cite the evidence used, and recommend practical next steps."
)


def _get_user_report(db: Session, report_id: str, user: User) -> Report:
    report = db.get(Report, report_id)
    if not report or report.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found.")
    return report


def _get_user_session(db: Session, session_id: str, user: User) -> ConversationSession:
    session = db.get(ConversationSession, session_id)
    if not session or session.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found.")
    return session


def _load_report_attachment_contexts(
    db: Session,
    *,
    session: ConversationSession,
    user: User,
    attachment_ids: list[str],
) -> list[dict[str, Any]]:
    selected_uploads: list[Upload] = []
    if attachment_ids:
        selected_uploads = (
            db.query(Upload)
            .filter(
                Upload.id.in_(attachment_ids),
                Upload.owner_id == user.id,
                Upload.project_id == session.project_id,
            )
            .all()
        )
        if len(selected_uploads) != len(attachment_ids):
            # Keep the response deliberately generic so another user's upload
            # identifiers cannot be enumerated through this endpoint.
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="One or more evidence attachments were not found in this project.",
            )

    project_uploads = memory_service.load_project_uploads(
        db,
        session_id=session.id,
        user_id=user.id,
    )
    upload_map = {upload.id: upload for upload in [*project_uploads, *selected_uploads]}
    return [upload_service.to_context(upload).model_dump() for upload in upload_map.values()]


def _save_explicit_report_result(
    db: Session,
    *,
    session: ConversationSession,
    user: User,
    query: str,
    result: dict[str, Any],
    normalized_status: str,
) -> Report:
    report_id = result.get("final_report_id") or str(uuid4())
    report = db.get(Report, report_id)
    if report is None:
        report = Report(
            id=report_id,
            project_id=session.project_id,
            session_id=session.id,
            user_id=user.id,
            original_query=query,
            rewritten_query=result.get("rewritten_query"),
            response_text=result.get("final_response") or "",
            structured_report_json=result.get("final_report"),
            response_status=normalized_status,
        )
        db.add(report)
        db.commit()
        db.refresh(report)
    else:
        if report.user_id != user.id or report.session_id != session.id:
            raise RuntimeError("The generated report identifier did not belong to the active session.")
        # The graph persists successful reports as `completed`; normalize the
        # explicit workflow to the public API status used by the frontend.
        report.response_status = normalized_status
        report.response_text = result.get("final_response") or report.response_text
        report.structured_report_json = result.get("final_report") or report.structured_report_json
        db.add(report)
        db.commit()
        db.refresh(report)
    return report


def _missing_evidence_from_result(result: dict[str, Any]) -> list[str]:
    values: list[str] = []
    cross_reference = result.get("cross_reference_result") or {}
    for item in cross_reference.get("missing_evidence") or []:
        text = str(item).strip()
        if text and text not in values:
            values.append(text)
    feedback = str(result.get("evaluator_feedback") or "").strip()
    if feedback and feedback not in values:
        values.append(feedback)
    return values[:8]


@session_report_router.post("/{session_id}/reports/generate")
async def generate_session_report(
    session_id: str,
    payload: GenerateReportRequest,
    db: Annotated[Session, Depends(get_db)],
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> dict:
    """Generate and persist a grounded report for a user-owned review session."""

    session = _get_user_session(db, session_id, user)
    attachment_contexts = _load_report_attachment_contexts(
        db,
        session=session,
        user=user,
        attachment_ids=payload.attachment_ids,
    )
    focus = payload.query.strip() if payload.query else None
    query = DEFAULT_REPORT_QUERY if not focus else f"{DEFAULT_REPORT_QUERY} User focus: {focus}"
    source_ip = request.client.host if request.client else None
    run_id = pipeline_log_service.start_run(
        session_id=session.id,
        project_id=session.project_id,
        user_id=user.id,
        original_query=query,
    )

    if not attachment_contexts:
        detail = "Add at least one photo, policy, certificate, or record before generating a readiness report."
        result: dict[str, Any] = {
            "final_response": detail,
            "final_report": None,
            "response_status": "insufficient_coverage",
            "evaluator_feedback": "Upload evidence that describes the factory or the audit area to review.",
        }
        report = _save_explicit_report_result(
            db,
            session=session,
            user=user,
            query=query,
            result=result,
            normalized_status="insufficient_evidence",
        )
        pipeline_log_service.complete_run(run_id=run_id, status="insufficient_evidence")
        log_audit_event(
            db,
            actor_user_id=user.id,
            action="report_generation_insufficient",
            resource_type="report",
            resource_id=report.id,
            ip_address=source_ip,
            metadata={"session_id": session.id, "project_id": session.project_id, "reason": "no_evidence"},
        )
        return {
            "status": "insufficient_evidence",
            "detail": detail,
            "missing_evidence": _missing_evidence_from_result(result),
        }

    runtime = GraphRuntime(
        session_factory=SessionLocal,
        emitter=PipelineEmitter(),
        user_id=user.id,
        session_id=session.id,
        project_id=session.project_id,
        run_id=run_id,
        source_ip=source_ip,
        mcp_service=mcp_service,
        pipeline_log_service=pipeline_log_service,
    )
    try:
        result = await report_generation_graph.ainvoke(
            {
                "original_query": query,
                "project_id": session.project_id,
                "session_id": session.id,
                "user_id": user.id,
                "attachment_contexts": attachment_contexts,
                "retry_count": 0,
                "source_ip": source_ip,
            },
            config={"configurable": {"runtime": runtime}},
        )
    except Exception as exc:
        pipeline_log_service.complete_run(run_id=run_id, status="failed", error_detail=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Report generation could not be completed. Please try again.",
        ) from exc

    structured_report = result.get("final_report")
    generated = bool(structured_report)
    normalized_status = "generated" if generated else "insufficient_evidence"
    report = _save_explicit_report_result(
        db,
        session=session,
        user=user,
        query=query,
        result=result,
        normalized_status=normalized_status,
    )
    pipeline_log_service.complete_run(run_id=run_id, status=normalized_status)
    log_audit_event(
        db,
        actor_user_id=user.id,
        action="report_generated" if generated else "report_generation_insufficient",
        resource_type="report",
        resource_id=report.id,
        ip_address=source_ip,
        metadata={
            "session_id": session.id,
            "project_id": session.project_id,
            "attachment_ids": payload.attachment_ids,
            "response_status": normalized_status,
        },
    )
    if generated:
        return {
            "status": "generated",
            "report_id": report.id,
            "structured_report": structured_report,
        }

    return {
        "status": "insufficient_evidence",
        "detail": result.get("final_response")
        or "The available evidence was not sufficient to produce a responsible readiness report.",
        "missing_evidence": _missing_evidence_from_result(result),
    }


@router.get("/{report_id}")
def get_report(
    report_id: str,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict:
    report = _get_user_report(db, report_id, user)
    return {
        "id": report.id,
        "response_text": report.response_text,
        "structured_report": report.structured_report_json,
        "response_status": report.response_status,
        "created_at": report.created_at.isoformat(),
    }


@router.get("/{report_id}/download")
def download_report(
    report_id: str,
    db: Annotated[Session, Depends(get_db)],
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    format: Literal["pdf", "docx", "csv"] = "pdf",
) -> FileResponse:
    report = _get_user_report(db, report_id, user)
    if not report.structured_report_json:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A downloadable file is not available because the evidence was insufficient for a report.",
        )

    structured = ComplianceReport.model_validate(report.structured_report_json)
    generators = {
        "pdf": (report_service.generate_pdf, "application/pdf"),
        "docx": (
            report_service.generate_docx,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        "csv": (report_service.generate_csv, "text/csv; charset=utf-8"),
    }
    generator, media_type = generators[format]
    target = generator(structured, report.id)
    log_audit_event(
        db,
        actor_user_id=user.id,
        action="report_downloaded",
        resource_type="report",
        resource_id=report.id,
        ip_address=request.client.host if request.client else None,
        metadata={"format": format},
    )
    return FileResponse(
        path=target,
        media_type=media_type,
        filename=f"auditready-{report.id}.{format}",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.post("/{report_id}/export")
async def export_report(
    report_id: str,
    payload: ExportReportRequest,
    db: Annotated[Session, Depends(get_db)],
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> dict:
    report = _get_user_report(db, report_id, user)
    if not report.structured_report_json:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Structured report data not available.")
    structured = ComplianceReport.model_validate(report.structured_report_json)
    pdf_path = report_service.generate_pdf(structured, report.id)

    mcp_result = None
    if payload.confirm and payload.destination_path:
        try:
            mcp_result = await mcp_service.export_report_via_filesystem(
                report_bytes=pdf_path.read_bytes(),
                destination_path=payload.destination_path,
            )
        except MCPIntegrationError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    log_audit_event(
        db,
        actor_user_id=user.id,
        action="report_exported",
        resource_type="report",
        resource_id=report.id,
        ip_address=request.client.host if request.client else None,
        metadata={"destination_path": payload.destination_path, "used_filesystem_mcp": bool(mcp_result)},
    )
    return {"pdf_path": str(pdf_path), "mcp_result": mcp_result}


@router.post("/{report_id}/send/email")
async def send_email(
    report_id: str,
    payload: SendEmailRequest,
    db: Annotated[Session, Depends(get_db)],
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
) -> dict:
    if not payload.confirm:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Explicit confirmation is required.")
    report = _get_user_report(db, report_id, user)
    if not report.structured_report_json:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Structured report data not available.")
    pdf_path = report_service.generate_pdf(ComplianceReport.model_validate(report.structured_report_json), report.id)
    try:
        result = await mcp_service.send_email_report(
            recipient=str(payload.recipient),
            subject=payload.subject,
            body="AuditReady AI pre-audit report attached.",
            report_path=str(pdf_path),
        )
    except MCPIntegrationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    log_audit_event(
        db,
        actor_user_id=user.id,
        action="report_sent_email",
        resource_type="report",
        resource_id=report.id,
        ip_address=request.client.host if request.client else None,
        metadata={"recipient": str(payload.recipient)},
    )
    return {"status": "sent", "provider_response": result}
