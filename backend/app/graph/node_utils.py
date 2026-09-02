from __future__ import annotations

import base64
import io
import re
from pathlib import Path

from PIL import Image

from app.core.encryption import read_encrypted_file
from app.graph.runtime import GraphRuntime


EMBEDDED_INSTRUCTION_PATTERN = re.compile(
    r"(?i)(ignore\s+(?:all\s+)?(?:previous|prior)\s+instructions|system\s+prompt|developer\s+message|"
    r"act\s+as\s+(?:the\s+)?(?:system|assistant)|do\s+not\s+follow\s+(?:the\s+)?instructions)"
)


def neutralize_embedded_instructions(value: str) -> str:
    return EMBEDDED_INSTRUCTION_PATTERN.sub("[embedded instruction ignored]", value)


def get_runtime(config) -> GraphRuntime:
    return config["configurable"]["runtime"]


async def emit_start(config, node_name: str, detail: str | None = None) -> None:
    runtime = get_runtime(config)
    if runtime.pipeline_log_service:
        runtime.pipeline_log_service.log_step(run_id=runtime.run_id, node_name=node_name, status="started", detail=detail)
    await runtime.emitter.stage(node_name, "started", detail)


async def emit_complete(config, node_name: str, detail: str | None = None) -> None:
    runtime = get_runtime(config)
    if runtime.pipeline_log_service:
        runtime.pipeline_log_service.log_step(run_id=runtime.run_id, node_name=node_name, status="completed", detail=detail)
    await runtime.emitter.stage(node_name, "completed", detail)


def read_attachment_bytes(path: str) -> bytes:
    try:
        return read_encrypted_file(Path(path))
    except Exception:
        return Path(path).read_bytes()


def image_to_data_url(mime_type: str, payload: bytes, *, max_edge: int = 1600) -> str:
    """Create a bounded vision payload without changing the stored evidence.

    Factory photos can be many megapixels. Sending those bytes unchanged makes
    local vision unnecessarily slow and can exceed hosted provider limits. The
    encrypted original remains untouched; only the model payload is resized.
    """

    prepared = payload
    prepared_mime = mime_type
    try:
        image = Image.open(io.BytesIO(payload))
        image.load()
        if max(image.size) > max_edge:
            image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            if image.mode in {"RGBA", "LA"}:
                image.save(output, format="PNG", optimize=True)
                prepared_mime = "image/png"
            else:
                image.convert("RGB").save(output, format="JPEG", quality=88, optimize=True)
                prepared_mime = "image/jpeg"
            prepared = output.getvalue()
    except Exception:
        # Upload validation has already checked supported image files. Keep the
        # original payload here so an adapter can still attempt analysis.
        pass

    encoded = base64.b64encode(prepared).decode("utf-8")
    return f"data:{prepared_mime};base64,{encoded}"


def compact_history(history: list[dict], limit: int = 8) -> str:
    rows = history[-limit:]
    return "\n".join(f"{row['role']}: {row['content']}" for row in rows)


def compact_project_context(context: dict | None) -> dict:
    """Keep model prompts bounded while retaining the evidence needed for routing."""
    context = context or {}

    def compact_session(row: dict) -> dict:
        latest = row.get("latest_message") or {}
        return {
            "session_id": row.get("session_id"),
            "title": row.get("title"),
            "latest_message": {
                "role": latest.get("role"),
                "content": str(latest.get("content") or "")[:180],
            } if latest else None,
        }

    return {
        "project": context.get("project"),
        "shared_uploads": [
            {
                "upload_id": row.get("upload_id"),
                "file_name": row.get("file_name"),
                "document_type": row.get("document_type"),
                "preview_text": str(row.get("preview_text") or "")[:180],
            }
            for row in context.get("shared_uploads", [])[:6]
        ],
        "related_sessions": [compact_session(row) for row in context.get("related_sessions", [])[:4]],
        "cross_project_sessions": [compact_session(row) for row in context.get("cross_project_sessions", [])[:3]],
    }


def compact_documents(documents: list[dict], limit: int = 4, snippet_limit: int = 260) -> list[dict]:
    return [
        {
            "doc_id": row.get("doc_id"),
            "title": row.get("title"),
            "standard_name": row.get("standard_name"),
            "citation": row.get("citation"),
            "clause_reference": row.get("clause_reference"),
            "source_url": row.get("source_url"),
            "source_type": row.get("source_type", "authoritative_standard"),
            "authority_level": row.get("authority_level", "authoritative"),
            "dataset": row.get("dataset"),
            "audit_unit": row.get("audit_unit"),
            "document_type": row.get("document_type"),
            "upload_id": row.get("upload_id"),
            "snippet": neutralize_embedded_instructions(str(row.get("snippet") or ""))[:snippet_limit],
            "score": row.get("score"),
        }
        for row in documents[:limit]
    ]


def compact_attachments(attachments: list[dict], limit: int = 12) -> list[dict]:
    """Exclude full extracted documents; relevant chunks arrive through project GraphRAG."""
    return [
        {
            "upload_id": row.get("upload_id"),
            "file_name": row.get("file_name"),
            "mime_type": row.get("mime_type"),
            "document_type": row.get("document_type"),
            "evidence_summary": neutralize_embedded_instructions(str(row.get("evidence_summary") or "")),
            "ingestion_status": row.get("ingestion_status"),
            "extraction_method": row.get("extraction_method"),
            "context_scope": row.get("context_scope", "project_memory"),
        }
        for row in attachments[:limit]
    ]


def document_workspace_attachments(
    attachments: list[dict], *, limit: int = 4, per_document_limit: int = 30_000
) -> list[dict]:
    """Supply document operations with source content, while keeping prompts bounded."""
    result = []
    for row in attachments[:limit]:
        extracted = str(row.get("extracted_text") or "")
        truncated = len(extracted) > per_document_limit
        result.append(
            {
                "upload_id": row.get("upload_id"),
                "file_name": row.get("file_name"),
                "mime_type": row.get("mime_type"),
                "document_type": row.get("document_type"),
                "ingestion_status": row.get("ingestion_status"),
                "extraction_method": row.get("extraction_method"),
                "content_truncated": truncated,
                "extracted_content": neutralize_embedded_instructions(extracted[:per_document_limit]),
            }
        )
    return result


def project_completeness(attachments: list[dict]) -> dict:
    """Deterministic pre-audit evidence inventory; absence means unverified, not noncompliant."""
    checklist = {
        "policies_and_procedures": {"policy"},
        "payroll_and_wages": {"wages"},
        "time_and_attendance": {"attendance"},
        "employment_contracts": {"contracts"},
        "health_and_safety": {"safety"},
        "chemical_management": {"chemical"},
        "grievance_and_worker_voice": {"grievance"},
        "worker_welfare": {"welfare"},
    }
    supplied = {str(row.get("document_type") or "general") for row in attachments}
    unreadable = [
        str(row.get("file_name") or row.get("upload_id"))
        for row in attachments
        if row.get("ingestion_status") in {"failed", "needs_ocr"}
    ]
    covered = [name for name, types in checklist.items() if supplied.intersection(types)]
    missing = [name for name, types in checklist.items() if not supplied.intersection(types)]
    return {
        "uploaded_file_count": len(attachments),
        "covered_evidence_areas": covered,
        "unverified_evidence_areas": missing,
        "unreadable_or_unsearchable_files": unreadable,
        "interpretation": "Unverified means the project has not supplied recognizable evidence; it is not proof of noncompliance.",
    }
