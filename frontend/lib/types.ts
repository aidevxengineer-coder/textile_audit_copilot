export type User = {
  id: string;
  email: string;
  full_name: string;
  role: "factory_user" | "admin";
  mfa_enabled: boolean;
  must_enroll_mfa: boolean;
};

export type ProjectSummary = {
  id: string;
  name: string;
  description?: string | null;
  domain_name: string;
  shared_context_notes?: string | null;
  session_count: number;
  upload_count: number;
  updated_at: string;
};

export type SessionSummary = {
  id: string;
  project_id?: string | null;
  title: string;
  updated_at: string;
};

export type SessionDetail = {
  id: string;
  project_id?: string | null;
  title: string;
  project?: {
    id: string;
    name: string;
    domain_name: string;
    description?: string | null;
    shared_context_notes?: string | null;
  };
  messages: Array<{
    role: "user" | "assistant";
    content: string;
    attachments: Array<{
      upload_id: string;
      file_name: string;
      mime_type: string;
    }>;
  }>;
  uploads: Array<{
    id: string;
    filename: string;
    mime_type: string;
    document_type?: string | null;
    has_extracted_text?: boolean;
    download_url?: string;
    preview_url?: string;
    preview_available?: boolean;
    ingestion_status?: "uploading" | "extracting" | "ocr" | "indexed" | "ready" | "failed" | string;
    extraction_status?: string | null;
    extraction_method?: "native" | "ocr" | "vision" | string | null;
    extraction_message?: string | null;
    preview_text?: string | null;
    size_bytes?: number | null;
    created_at?: string | null;
    error_message?: string | null;
    page_count?: number | null;
    image_width?: number | null;
    image_height?: number | null;
  }>;
  project_context?: {
    project?: {
      id: string;
      name: string;
      description?: string | null;
      domain_name?: string | null;
      shared_context_notes?: string | null;
    } | null;
    shared_uploads: Array<{
      upload_id: string;
      file_name: string;
      mime_type: string;
      document_type?: string | null;
      preview_text?: string | null;
    }>;
    related_sessions: Array<{
      session_id: string;
      title: string;
      updated_at: string;
      latest_message?: {
        role: "user" | "assistant";
        content: string;
        created_at: string;
      } | null;
    }>;
    cross_project_sessions: Array<{
      session_id: string;
      project_id?: string | null;
      title: string;
      updated_at: string;
      latest_message?: {
        role: "user" | "assistant";
        content: string;
        created_at: string;
      } | null;
    }>;
  };
  latest_report: ComplianceReport | null;
  latest_report_id: string | null;
};

export type ProjectDetail = ProjectSummary & {
  sessions: SessionSummary[];
  uploads: SessionDetail["uploads"];
};

export type PipelineEvent = {
  type: "stage" | "token" | "done" | "error";
  node_name?: string;
  status?: string;
  detail?: string;
  value?: string;
  payload?: {
    session_id: string;
    report_id?: string | null;
    response_status?: string;
    final_report?: ComplianceReport | null;
    current_web_findings?: Array<Record<string, unknown>> | null;
  };
};

export type ComplianceFinding = {
  category: string;
  verdict: "Major" | "Minor" | "Compliant" | "Needs More Evidence";
  standard_name: string;
  clause_reference: string;
  evidence_summary: string;
  remediation: string;
  audit_risk?: string;
  evidence_gap?: string;
  recommended_evidence?: string[];
  priority?: "Critical" | "High" | "Medium" | "Low";
  confidence: "High" | "Medium" | "Low";
  references: FindingReference[];
};

export type FindingReference = {
  label: string;
  source_type: "standard" | "upload" | "web";
  source_url?: string | null;
  upload_id?: string | null;
  file_name?: string | null;
  citation?: string | null;
};

export type ComplianceReport = {
  executive_summary: string;
  disclaimer: string;
  findings: ComplianceFinding[];
  scope_reviewed?: string[];
  scope_limitations?: string[];
  positive_controls?: string[];
  critical_missing_documents?: string[];
  next_best_questions: string[];
  recommended_actions: string[];
  current_web_findings?: Array<Record<string, unknown>>;
};

export type StoredReport = {
  id: string;
  response_text: string;
  structured_report: ComplianceReport | null;
  response_status: string;
  created_at: string;
};

export type KnowledgeBaseDocument = {
  id: string;
  title: string;
  standard_name: string;
  citation?: string | null;
  source_url: string;
  version?: string | null;
  ingested_at: string;
};

export type AuditLog = {
  id: string;
  actor_user_id?: string | null;
  action: string;
  resource_type: string;
  resource_id?: string | null;
  ip_address?: string | null;
  metadata?: Record<string, unknown> | null;
  created_at: string;
};

export type PipelineRunLog = {
  id: string;
  session_id: string;
  project_id?: string | null;
  user_id: string;
  original_query: string;
  status: string;
  error_detail?: string | null;
  created_at: string;
  completed_at?: string | null;
  steps: Array<{
    node_name: string;
    status: string;
    detail?: string | null;
    created_at: string;
  }>;
  tools: Array<{
    tool_name: string;
    tool_kind: string;
    status: string;
    arguments?: Record<string, unknown> | null;
    result_preview?: string | null;
    created_at: string;
  }>;
};

export type AdminSystemStatus = {
  source_manifest_count: number;
  downloaded_source_count: number;
  supported_upload_types: string[];
  mcp_integrations: {
    filesystem: boolean;
    gmail: boolean;
    whatsapp: boolean;
    web_search: boolean;
  };
};
