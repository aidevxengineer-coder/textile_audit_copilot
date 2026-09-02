from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AnyHttpUrl, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    app_name: str = "AuditReady AI"
    backend_host: str = "127.0.0.1"
    backend_port: int = 8010
    frontend_url: AnyHttpUrl = "http://localhost:3000"
    public_app_url: AnyHttpUrl = "http://localhost:3000"
    api_base_url: AnyHttpUrl | None = None

    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    database_url: str
    file_encryption_key: str
    enforce_https: bool = False

    admin_email: str
    admin_password: str
    admin_full_name: str = "Audit Administrator"

    chroma_dir: Path = Path("backend/storage/chroma")
    graph_store_path: Path = Path("data/processed/knowledge_graph.json")
    graph_index_path: Path = Path("data/processed/knowledge_graph_index.json")
    lightrag_workdir: Path = Path("backend/storage/lightrag")
    upload_dir: Path = Path("backend/uploads")
    report_dir: Path = Path("backend/reports")
    max_upload_mb: int = 15
    max_project_files: int = 200
    max_project_storage_mb: int = 500

    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_text_model: str = "llama3.1:8b"
    ollama_vision_model: str = "qwen2.5vl:7b"
    ollama_request_timeout_seconds: int = 180
    # Text and vision can use different providers.  A Groq text deployment can
    # therefore keep sensitive factory photos on the local Ollama runtime.
    vision_provider: str = "ollama"
    vision_fallback_provider: str = "groq"
    vision_request_timeout_seconds: float = 30.0
    vision_max_images: int = 3
    # Relevance scoring is an interactive routing decision, not the final
    # answer. Fall back conservatively if a provider stalls.
    relevance_evaluator_timeout_seconds: float = 8.0
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    ai_provider: str = "ollama"
    groq_api_key: str | None = None
    groq_text_model: str = "llama-3.3-70b-versatile"
    groq_vision_model: str = "meta-llama/llama-4-scout-17b-16e-instruct"

    # Keep enough candidates for RRF while avoiding unnecessary local-model work.
    retrieval_top_k: int = 6
    graph_hops: int = 2
    # One relevance retry preserves the recovery path while keeping interactive runs responsive.
    max_retries: int = 1
    use_lightrag_core: bool = True

    enable_filesystem_mcp: bool = False
    filesystem_mcp_url: str | None = None
    enable_gmail_mcp: bool = False
    gmail_mcp_url: str | None = None
    enable_web_search_mcp: bool = True
    # The public-web fallback is an optional recovery path, so it must never
    # hold an interactive WebSocket open for tens of seconds.  This budget
    # covers MCP startup, provider search, normalization, and link checks.
    web_search_timeout_seconds: float = 5.0
    enable_whatsapp_mcp: bool = False
    web_search_mcp_url: str | None = None

    documents_mcp_command: str | None = None
    email_mcp_command: str | None = None
    utilities_mcp_command: str | None = None
    whatsapp_mcp_command: str | None = None
    use_dummy_communications: bool = True

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    imap_host: str | None = None
    imap_port: int = 993
    imap_username: str | None = None
    imap_password: str | None = None
    imap_folder: str = "INBOX"

    filesystem_mcp_command: str | None = None
    gmail_mcp_command: str | None = None
    web_search_mcp_command: str | None = None

    access_token_cookie_name: str = Field(default="auditready_access")
    refresh_token_cookie_name: str = Field(default="auditready_refresh")

    @model_validator(mode="after")
    def derive_backend_urls(self) -> "Settings":
        if self.api_base_url is None:
            self.api_base_url = f"http://{self.backend_host}:{self.backend_port}"
        return self

    def validate_for_deployment(self) -> None:
        if self.app_env != "production":
            return
        problems: list[str] = []
        if not self.enforce_https:
            problems.append("ENFORCE_HTTPS must be true")
        if len(self.jwt_secret) < 32:
            problems.append("JWT_SECRET must contain at least 32 characters")
        if len(self.file_encryption_key) < 32:
            problems.append("FILE_ENCRYPTION_KEY must contain at least 32 characters")
        if self.jwt_secret == self.file_encryption_key:
            problems.append("JWT_SECRET and FILE_ENCRYPTION_KEY must be different")
        if self.jwt_algorithm not in {"HS256", "HS384", "HS512"}:
            problems.append("JWT_ALGORITHM must be HS256, HS384, or HS512")
        if len(self.admin_password) < 14:
            problems.append("ADMIN_PASSWORD must contain at least 14 characters")
        if str(self.public_app_url).startswith("http://"):
            problems.append("PUBLIC_APP_URL must use HTTPS")
        if self.api_base_url and str(self.api_base_url).startswith("http://"):
            problems.append("API_BASE_URL must use HTTPS")
        if self.enable_filesystem_mcp:
            problems.append("filesystem MCP must remain disabled in production")
        if problems:
            raise RuntimeError("Unsafe production configuration: " + "; ".join(problems))

    def ensure_directories(self) -> None:
        for path in (
            self.chroma_dir,
            self.graph_store_path.parent,
            self.lightrag_workdir,
            self.upload_dir,
            self.report_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings
