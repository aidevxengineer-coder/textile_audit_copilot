from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.security import sanitize_text


class SessionCreateRequest(BaseModel):
    title: str = Field(default="Factory Audit Session", min_length=2, max_length=120)
    project_id: str | None = Field(default=None, min_length=36, max_length=36)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        return sanitize_text(value)


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=1200)
    domain_name: str = Field(default="supplier_compliance", min_length=2, max_length=120)
    shared_context_notes: str | None = Field(default=None, max_length=1200)

    @field_validator("name", "domain_name")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        return sanitize_text(value)

    @field_validator("description", "shared_context_notes")
    @classmethod
    def validate_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return sanitize_text(value, allow_question_text=True)


class ChatSubmissionPayload(BaseModel):
    query: str = Field(min_length=2, max_length=4000)
    upload_ids: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        return sanitize_text(value, allow_question_text=True)

    @field_validator("upload_ids")
    @classmethod
    def validate_upload_ids(cls, values: list[str]) -> list[str]:
        unique: list[str] = []
        for value in values:
            cleaned = sanitize_text(value)
            if len(cleaned) != 36:
                raise ValueError("Upload IDs must be UUID strings.")
            if cleaned not in unique:
                unique.append(cleaned)
        return unique


class GenerateReportRequest(BaseModel):
    query: str | None = Field(default=None, min_length=2, max_length=4000)
    attachment_ids: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return sanitize_text(value, allow_question_text=True)

    @field_validator("attachment_ids")
    @classmethod
    def validate_attachment_ids(cls, values: list[str]) -> list[str]:
        unique: list[str] = []
        for value in values:
            cleaned = sanitize_text(value)
            if len(cleaned) != 36:
                raise ValueError("Attachment IDs must be UUID strings.")
            if cleaned not in unique:
                unique.append(cleaned)
        return unique


class ExportReportRequest(BaseModel):
    destination_path: str | None = None
    confirm: bool = False

    @field_validator("destination_path")
    @classmethod
    def validate_path(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return sanitize_text(value)


class SendEmailRequest(BaseModel):
    recipient: EmailStr
    subject: str = Field(min_length=3, max_length=160)
    confirm: bool = False

    @field_validator("subject")
    @classmethod
    def validate_subject(cls, value: str) -> str:
        return sanitize_text(value)


class KnowledgeBaseReindexRequest(BaseModel):
    fetch_documents: bool = True


class GenerateDocumentRequest(BaseModel):
    format: str = Field(pattern="^(pdf|docx|csv|txt|md)$")
    title: str = Field(min_length=1, max_length=160)
    content: str = Field(min_length=1, max_length=100_000)
    filename: str = Field(min_length=1, max_length=120)


class DraftEmailRequest(BaseModel):
    recipient: EmailStr
    subject: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=1, max_length=50_000)
    attachment_paths: list[str] = Field(default_factory=list, max_length=10)


class EmailAttachmentRequest(BaseModel):
    message_id: str = Field(min_length=1, max_length=128)
    attachment_name: str = Field(min_length=1, max_length=255)


class WhatsAppMessageRequest(BaseModel):
    recipient: str = Field(min_length=3, max_length=64)
    body: str = Field(min_length=1, max_length=4096)

    @field_validator("recipient", "body")
    @classmethod
    def validate_whatsapp_text(cls, value: str) -> str:
        return sanitize_text(value, allow_question_text=True)
