from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import sessionmaker

from app.core.events import PipelineEmitter
from app.services.memory_service import MemoryService
from app.services.ollama_service import OllamaService
from app.services.tool_service import ToolService
from app.services.report_service import ReportService
from app.services.retrieval_service import RetrievalService
from app.services.report_guardrail_service import ReportGuardrailService


@dataclass
class GraphRuntime:
    session_factory: sessionmaker
    emitter: PipelineEmitter
    user_id: str
    session_id: str
    project_id: str | None = None
    run_id: str | None = None
    source_ip: str | None = None
    memory_service: MemoryService = field(default_factory=MemoryService)
    ollama_service: OllamaService = field(default_factory=OllamaService)
    tool_service: ToolService = field(default_factory=ToolService)
    retrieval_service: RetrievalService = field(default_factory=RetrievalService)
    report_service: ReportService = field(default_factory=ReportService)
    report_guardrail_service: ReportGuardrailService = field(default_factory=ReportGuardrailService)
    mcp_service: Any | None = None
    pipeline_log_service: Any | None = None
