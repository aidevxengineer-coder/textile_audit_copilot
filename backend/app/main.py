from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from sqlalchemy.orm import Session

from app.api.routes.admin import router as admin_router
from app.api.routes.app_data import router as app_router
from app.api.routes.auth import router as auth_router
from app.api.routes.reports import router as reports_router, session_report_router
from app.api.routes.integrations import router as integrations_router
from app.api.schemas import ChatSubmissionPayload
from app.auth.dependencies import require_role
from app.config import get_settings
from app.core.audit import log_audit_event
from app.core.events import PipelineEmitter
from app.core.security import decode_token
from app.core.deployment_security import origin_allowed, rate_limiter
from app.db.session import SessionLocal, create_db_and_seed, get_db
from app.graph.graph import build_graph
from app.graph.runtime import GraphRuntime
from app.mcp.service import MCPService
from app.models.conversation import ConversationSession
from app.models.upload import Upload
from app.models.user import User
from app.services.memory_service import MemoryService
from app.services.pipeline_log_service import PipelineLogService
from app.services.upload_service import UploadService


settings = get_settings()
settings.validate_for_deployment()


def _normalize_origin(value: str) -> str:
    return value.rstrip("/")


def _local_frontend_origin_variants() -> list[str]:
    configured = {
        _normalize_origin(str(settings.frontend_url)),
        _normalize_origin(str(settings.public_app_url)),
    }
    variants = set(configured)
    for origin in configured:
        parsed = urlparse(origin)
        if parsed.scheme not in {"http", "https"} or not parsed.port:
            continue
        if parsed.hostname == "localhost":
            variants.add(f"{parsed.scheme}://127.0.0.1:{parsed.port}")
        if parsed.hostname == "127.0.0.1":
            variants.add(f"{parsed.scheme}://localhost:{parsed.port}")
    return sorted(variants)


app = FastAPI(
    title=settings.app_name,
    docs_url=None if settings.app_env == "production" else "/docs",
    redoc_url=None if settings.app_env == "production" else "/redoc",
    openapi_url=None if settings.app_env == "production" else "/openapi.json",
)
trusted_hosts = {
    value
    for value in (
        urlparse(str(settings.frontend_url)).hostname,
        urlparse(str(settings.public_app_url)).hostname,
        urlparse(str(settings.api_base_url)).hostname if settings.api_base_url else None,
        settings.backend_host,
        "testserver" if settings.app_env != "production" else None,
    )
    if value
}
app.add_middleware(TrustedHostMiddleware, allowed_hosts=sorted(trusted_hosts))
app.add_middleware(
    CORSMiddleware,
    allow_origins=_local_frontend_origin_variants(),
    allow_origin_regex=(
        r"^https?://(?:localhost|127\.0\.0\.1|10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}):\d+$"
        if settings.app_env == "development"
        else None
    ),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
)


@app.middleware("http")
async def deployment_security_middleware(request: Request, call_next):
    allowed_origins = set(_local_frontend_origin_variants())
    origin = request.headers.get("origin")
    if origin and not origin_allowed(origin, allowed_origins):
        return JSONResponse(status_code=403, content={"detail": "Origin is not allowed."})
    cookie_authenticated = bool(
        request.cookies.get(settings.access_token_cookie_name)
        or request.cookies.get(settings.refresh_token_cookie_name)
    ) and not request.headers.get("authorization")
    if settings.app_env == "production" and request.method in {"POST", "PUT", "PATCH", "DELETE"} and cookie_authenticated:
        if not origin_allowed(origin, allowed_origins):
            return JSONResponse(status_code=403, content={"detail": "Origin verification required."})

    peer = request.client.host if request.client else "unknown"
    rate_rules = {
        "/api/auth/login": (10, 300),
        "/api/auth/login/verify-mfa": (10, 300),
        "/api/auth/register": (5, 3600),
        "/api/auth/refresh": (30, 300),
        "/api/uploads": (30, 60),
    }
    rule = rate_rules.get(request.url.path)
    if not rule and request.method == "POST" and request.url.path.startswith("/api/reports"):
        rule = (10, 60)
    if rule and not rate_limiter.allow(f"http:{peer}:{request.url.path}", limit=rule[0], window_seconds=rule[1]):
        return JSONResponse(status_code=429, content={"detail": "Too many requests. Please try again later."})

    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors " + " ".join(sorted(allowed_origins))
    if request.url.path.startswith("/api/auth"):
        response.headers["Cache-Control"] = "no-store"
    if settings.enforce_https:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

upload_service = UploadService()
memory_service = MemoryService()
pipeline_log_service = PipelineLogService(SessionLocal)
mcp_service = MCPService()
compiled_graph = build_graph()


def _get_ws_user(token: str) -> User:
    payload = decode_token(token)
    if payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid websocket token.")
    with SessionLocal() as db:
        user = db.get(User, payload["sub"])
        if not user or not user.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found.")
        return user


@app.on_event("startup")
def on_startup() -> None:
    create_db_and_seed()


@app.get("/")
def root() -> dict:
    return {"name": settings.app_name, "status": "ok"}


app.include_router(auth_router)
app.include_router(app_router)
app.include_router(admin_router)
app.include_router(reports_router)
app.include_router(session_report_router)
app.include_router(integrations_router)


@app.websocket("/ws/chat/{session_id}")
async def chat_ws(websocket: WebSocket, session_id: str) -> None:
    origin = websocket.headers.get("origin")
    if not origin_allowed(origin, set(_local_frontend_origin_variants())):
        await websocket.close(code=4403)
        return
    peer = websocket.client.host if websocket.client else "unknown"
    if not rate_limiter.allow(f"ws-connect:{peer}", limit=10, window_seconds=60):
        await websocket.close(code=4429)
        return
    token = websocket.cookies.get(settings.access_token_cookie_name)
    if not token:
        await websocket.close(code=4401)
        return
    try:
        user = _get_ws_user(token)
    except HTTPException:
        await websocket.close(code=4401)
        return

    await websocket.accept()

    async def emit(event: dict[str, Any]) -> None:
        try:
            await websocket.send_json(event)
        except (WebSocketDisconnect, RuntimeError):
            # Client disconnected mid-pipeline; drop the event so the graph
            # run can finish and persist its results.
            pass

    try:
        while True:
            raw_message = await websocket.receive_text()
            if not rate_limiter.allow(f"ws-message:{user.id}", limit=10, window_seconds=60):
                await emit({"type": "error", "detail": "Message rate limit exceeded. Please wait before retrying."})
                continue
            try:
                payload = ChatSubmissionPayload.model_validate_json(raw_message)
            except Exception as exc:
                await emit({"type": "error", "detail": f"Invalid payload: {exc}"})
                continue

            with SessionLocal() as db:
                session = db.get(ConversationSession, session_id)
                if not session or session.user_id != user.id:
                    await emit({"type": "error", "detail": "Session not found."})
                    continue
                selected_uploads = (
                    db.query(Upload)
                    .filter(
                        Upload.id.in_(payload.upload_ids),
                        Upload.owner_id == user.id,
                        Upload.project_id == session.project_id,
                    )
                    .all()
                    if payload.upload_ids
                    else []
                )
                project_uploads = memory_service.load_project_uploads(
                    db,
                    session_id=session_id,
                    user_id=user.id,
                )
                selected_by_id = {upload.id: upload for upload in selected_uploads}
                ordered_selected = [selected_by_id[upload_id] for upload_id in payload.upload_ids if upload_id in selected_by_id]
                current_attachment_contexts = [
                    {**upload_service.to_context(upload).model_dump(), "context_scope": "current_message"}
                    for upload in ordered_selected
                ]
                selected_ids = set(selected_by_id)
                memory_attachment_contexts = [
                    {**upload_service.to_context(upload).model_dump(), "context_scope": "project_memory"}
                    for upload in project_uploads
                    if upload.id not in selected_ids
                ]
                attachment_contexts = [*current_attachment_contexts, *memory_attachment_contexts]
                run_id = pipeline_log_service.start_run(
                    session_id=session_id,
                    project_id=session.project_id,
                    user_id=user.id,
                    original_query=payload.query,
                )

            runtime = GraphRuntime(
                session_factory=SessionLocal,
                emitter=PipelineEmitter(emit=emit),
                user_id=user.id,
                session_id=session_id,
                project_id=session.project_id,
                run_id=run_id,
                source_ip=websocket.client.host if websocket.client else None,
                mcp_service=mcp_service,
                pipeline_log_service=pipeline_log_service,
            )

            try:
                result = await compiled_graph.ainvoke(
                    {
                        "original_query": payload.query,
                        "project_id": session.project_id,
                        "session_id": session_id,
                        "user_id": user.id,
                        "attachment_contexts": attachment_contexts,
                        "current_attachment_contexts": current_attachment_contexts,
                        "retry_count": 0,
                        "source_ip": websocket.client.host if websocket.client else None,
                    },
                    config={"configurable": {"runtime": runtime}},
                )
                with SessionLocal() as db:
                    log_audit_event(
                        db,
                        actor_user_id=user.id,
                        action="report_generated",
                        resource_type="conversation_session",
                        resource_id=session_id,
                        ip_address=websocket.client.host if websocket.client else None,
                        metadata={
                            "response_status": result.get("response_status"),
                            "report_id": result.get("final_report_id"),
                            "upload_ids": payload.upload_ids,
                            "project_id": session.project_id,
                        },
                    )
                pipeline_log_service.complete_run(
                    run_id=run_id,
                    status=result.get("response_status", "completed"),
                )
                await runtime.emitter.done(
                    {
                        "session_id": session_id,
                        "report_id": result.get("final_report_id"),
                        "response_status": result.get("response_status"),
                        "final_report": result.get("final_report"),
                        "current_web_findings": result.get("current_web_findings"),
                    }
                )
                # The browser opens one socket per question.  Closing only after
                # the terminal `done` event makes completion unambiguous on the
                # client and prevents a stale socket being mistaken for a failed
                # stream.
                await websocket.close(code=1000)
                return
            except Exception as exc:
                pipeline_log_service.complete_run(run_id=run_id, status="failed", error_detail=str(exc))
                await emit({"type": "error", "detail": str(exc)})
                await websocket.close(code=1011)
                return
    except (WebSocketDisconnect, RuntimeError):
        # A browser navigation or hot reload can close a socket between messages.
        # Treat it as a normal disconnect instead of surfacing a server exception.
        return
