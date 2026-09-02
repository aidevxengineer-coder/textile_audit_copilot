from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class AttachmentContext(BaseModel):
    upload_id: str
    file_name: str
    mime_type: str
    stored_path: str
    document_type: str | None = None
    extracted_text: str | None = None
    preview_text: str | None = None
    evidence_summary: str | None = None
    ingestion_status: str | None = None
    extraction_method: str | None = None
    extraction_message: str | None = None
    embedded_images: list[dict[str, Any]] = Field(default_factory=list)


class RetrievedDocument(BaseModel):
    doc_id: str
    title: str
    standard_name: str
    citation: str | None = None
    clause_reference: str | None = None
    source_url: str | None = None
    source_type: str = "authoritative_standard"
    authority_level: str = "authoritative"
    dataset: str | None = None
    audit_unit: str | None = None
    document_type: str | None = None
    upload_id: str | None = None
    snippet: str
    score: float
    retrieval_mode: Literal["local", "global"]
    query_variant: Literal["original", "rewritten"]


class OrchestratorDecision(BaseModel):
    route: Literal["direct", "document", "grounded"]
    response_mode: Literal["answer", "report"] = "answer"
    needs_current_web_info: bool = False
    tool_name: Literal["none", "calculator", "weather", "time"] = "none"
    reason: str


class RelevanceVerdict(BaseModel):
    relevant: bool
    sufficient: bool
    feedback: str


class DocumentAnswerVerification(BaseModel):
    verified_answer: str
    removed_or_reclassified_claims: list[str] = Field(default_factory=list)
    all_factual_claims_supported: bool


class CrossReferenceResult(BaseModel):
    summary: str
    consistencies: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    referenced_upload_ids: list[str] = Field(default_factory=list)
    referenced_session_ids: list[str] = Field(default_factory=list)


class FindingReference(BaseModel):
    label: str
    source_type: Literal[
        "standard", "authoritative_standard", "historical_example", "historical_audit_example",
        "upload", "project_upload", "web",
    ] = "standard"
    source_url: str | None = None
    upload_id: str | None = None
    file_name: str | None = None
    citation: str | None = None

    @field_validator("source_type")
    @classmethod
    def normalize_source_type(cls, value: str) -> str:
        return {
            "authoritative_standard": "standard",
            "historical_audit_example": "historical_example",
            "project_upload": "upload",
        }.get(value, value)


class ComplianceFinding(BaseModel):
    category: str
    verdict: Literal["Major", "Minor", "Compliant", "Needs More Evidence"]
    standard_name: str
    clause_reference: str
    evidence_summary: str
    remediation: str
    audit_risk: str = "Potential external-audit concern requiring verification."
    evidence_gap: str = "No additional evidence gap recorded."
    recommended_evidence: list[str] = Field(default_factory=list)
    priority: Literal["Critical", "High", "Medium", "Low"] = "Medium"
    confidence: Literal["High", "Medium", "Low"]
    references: list[FindingReference] = Field(default_factory=list)


class ComplianceReport(BaseModel):
    executive_summary: str
    disclaimer: str = Field(
        default=(
            "This is a pre-screening gap-catcher, not a pass guarantee. Real audits include worker "
            "interviews, payroll verification, and on-site checks this tool cannot fully confirm."
        )
    )
    findings: list[ComplianceFinding]
    scope_reviewed: list[str] = Field(default_factory=list)
    scope_limitations: list[str] = Field(default_factory=list)
    positive_controls: list[str] = Field(default_factory=list)
    critical_missing_documents: list[str] = Field(default_factory=list)
    guardrail_notes: list[str] = Field(default_factory=list)
    next_best_questions: list[str]
    recommended_actions: list[str]
    current_web_findings: list[dict] = Field(default_factory=list)


class GraphExtractionResult(BaseModel):
    entities: list[dict]
    relationships: list[dict]
