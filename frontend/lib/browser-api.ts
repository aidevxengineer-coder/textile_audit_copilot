"use client";

import { apiBaseUrl, wsBaseUrl } from "@/lib/config";
import type {
  AuditLog,
  KnowledgeBaseDocument,
  PipelineRunLog,
  ProjectDetail,
  ProjectSummary,
  SessionDetail,
  SessionSummary,
  StoredReport,
  User,
} from "@/lib/types";

let accessTokenMemory: string | null = null;
const MFA_CHALLENGE_KEY = "auditready_mfa_challenge";
const MFA_SETUP_KEY = "auditready_mfa_setup";
let refreshPromise: Promise<string> | null = null;

type JsonValue = Record<string, unknown> | Array<unknown> | string | number | boolean | null;

export type ReportDownloadFormat = "pdf" | "docx" | "csv";

export type GenerateReportResult =
  | {
      status: "generated";
      report_id: string;
      structured_report: NonNullable<StoredReport["structured_report"]>;
    }
  | {
      status: "insufficient_evidence";
      detail: string;
      missing_evidence: string[];
    };

async function parseJson(response: Response) {
  const text = await response.text();
  if (!text) {
    return null;
  }
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function isAccessTokenFresh(token: string) {
  try {
    const encoded = token.split(".")[1].replaceAll("-", "+").replaceAll("_", "/");
    const payload = JSON.parse(atob(encoded.padEnd(Math.ceil(encoded.length / 4) * 4, "="))) as { exp?: number };
    return !payload.exp || payload.exp * 1000 > Date.now() + 30_000;
  } catch {
    return false;
  }
}

function canRefreshPath(path: string) {
  return ![
    "/api/auth/refresh",
    "/api/auth/login",
    "/api/auth/login/verify-mfa",
    "/api/auth/register",
    "/api/auth/logout",
    "/api/auth/mfa/enroll",
    "/api/auth/mfa/confirm",
  ].some((authPath) => path.startsWith(authPath));
}

async function refreshAccessToken() {
  if (!refreshPromise) {
    refreshPromise = (async () => {
      const response = await fetch(`${apiBaseUrl}/api/auth/refresh`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      const payload = await parseJson(response);
      if (!response.ok || !payload || typeof payload !== "object" || !("access_token" in payload)) {
        setAccessToken(null);
        throw new Error("Your secure session expired. Please sign in again.");
      }
      const token = String((payload as { access_token: unknown }).access_token);
      setAccessToken(token);
      return token;
    })().finally(() => {
      refreshPromise = null;
    });
  }
  return refreshPromise;
}

async function fetchWithSession(path: string, init?: RequestInit, retry = true) {
  const headers = new Headers(init?.headers);
  if (!headers.has("Content-Type") && init?.body != null && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`${apiBaseUrl}${path}`, {
    ...init,
    credentials: "include",
    headers,
  });
  if (response.status === 401 && retry && canRefreshPath(path)) {
    const accessToken = await refreshAccessToken();
    const headers = new Headers(init?.headers);
    headers.set("Authorization", `Bearer ${accessToken}`);
    if (!headers.has("Content-Type") && !(init?.body instanceof FormData)) {
      headers.set("Content-Type", "application/json");
    }
    return fetchWithSession(path, { ...init, headers }, false);
  }
  return response;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetchWithSession(path, init);
  const payload = await parseJson(response);
  if (!response.ok) {
    const detail =
      payload && typeof payload === "object" && "detail" in payload
        ? String((payload as { detail: unknown }).detail)
        : "Request failed";
    throw new Error(detail);
  }
  return payload as T;
}

export function getAccessToken() {
  return accessTokenMemory;
}

export function setAccessToken(token: string | null) {
  if (token) {
    accessTokenMemory = token;
  } else {
    accessTokenMemory = null;
  }
}

export async function ensureAccessToken() {
  const existing = getAccessToken();
  if (existing && isAccessTokenFresh(existing)) {
    return existing;
  }
  return refreshAccessToken();
}

export async function forceRefreshAccessToken() {
  return refreshAccessToken();
}

export async function registerUser(payload: {
  email: string;
  full_name: string;
  password: string;
}) {
  return request<User>("/api/auth/register", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function loginUser(payload: { email: string; password: string }) {
  const result = await request<{
    mfa_required?: boolean;
    mfa_enrollment_required?: boolean;
    challenge_token?: string | null;
    setup_token?: string | null;
    access_token?: string | null;
    refresh_token?: string | null;
    user: User;
  }>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  if (result.access_token) {
    setAccessToken(result.access_token);
  }
  if (result.challenge_token) {
    sessionStorage.setItem(MFA_CHALLENGE_KEY, result.challenge_token);
  }
  if (result.setup_token) {
    sessionStorage.setItem(MFA_SETUP_KEY, result.setup_token);
  }
  return result;
}

export async function logoutUser() {
  try {
    await request<{ status: string }>("/api/auth/logout", {
      method: "POST",
      body: JSON.stringify({}),
    });
  } finally {
    setAccessToken(null);
    clearMfaState();
  }
}

export function getMfaChallengeToken() {
  return sessionStorage.getItem(MFA_CHALLENGE_KEY);
}

export function getMfaSetupToken() {
  return sessionStorage.getItem(MFA_SETUP_KEY);
}

export function clearMfaState() {
  sessionStorage.removeItem(MFA_CHALLENGE_KEY);
  sessionStorage.removeItem(MFA_SETUP_KEY);
}

export async function verifyMfaLogin(code: string) {
  const challengeToken = getMfaChallengeToken();
  if (!challengeToken) {
    throw new Error("MFA challenge token is missing.");
  }
  const result = await request<{ access_token: string }>("/api/auth/login/verify-mfa", {
    method: "POST",
    body: JSON.stringify({ challenge_token: challengeToken, code }),
  });
  setAccessToken(result.access_token);
  clearMfaState();
  return result;
}

export async function beginMfaEnrollment() {
  const accessToken = getMfaSetupToken() || getAccessToken();
  return request<{ secret: string; provisioning_uri: string }>("/api/auth/mfa/enroll", {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}` },
    body: JSON.stringify({}),
  });
}

export async function confirmMfaEnrollment(code: string) {
  const accessToken = getMfaSetupToken() || getAccessToken();
  const result = await request<{ access_token: string }>("/api/auth/mfa/confirm", {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}` },
    body: JSON.stringify({ code }),
  });
  setAccessToken(result.access_token);
  clearMfaState();
  return result;
}

export async function fetchCurrentUser() {
  return request<User>("/api/auth/me", {
    headers: { Authorization: `Bearer ${await ensureAccessToken()}` },
  });
}

export function buildApiUrl(path: string) {
  return `${apiBaseUrl}${path}`;
}

export function buildUploadDownloadUrl(uploadId: string) {
  return buildApiUrl(`/api/uploads/${encodeURIComponent(uploadId)}/download`);
}

export async function createProject(payload: {
  name: string;
  description?: string;
  domain_name?: string;
  shared_context_notes?: string;
}) {
  return request<ProjectSummary>("/api/projects", {
    method: "POST",
    headers: { Authorization: `Bearer ${await ensureAccessToken()}` },
    body: JSON.stringify(payload),
  });
}

export async function fetchProjects() {
  return request<ProjectSummary[]>("/api/projects", {
    headers: { Authorization: `Bearer ${await ensureAccessToken()}` },
  });
}

export async function fetchProject(projectId: string) {
  return request<ProjectDetail>(`/api/projects/${projectId}`, {
    headers: { Authorization: `Bearer ${await ensureAccessToken()}` },
  });
}

export async function createSession(title = "Factory Audit Session", projectId?: string) {
  return request<{ id: string; project_id?: string | null; title: string; created_at: string }>("/api/sessions", {
    method: "POST",
    headers: { Authorization: `Bearer ${await ensureAccessToken()}` },
    body: JSON.stringify({ title, project_id: projectId }),
  });
}

export async function fetchSessions(projectId?: string) {
  const path = projectId ? `/api/sessions?project_id=${encodeURIComponent(projectId)}` : "/api/sessions";
  return request<SessionSummary[]>(path, {
    headers: { Authorization: `Bearer ${await ensureAccessToken()}` },
  });
}

export async function fetchSession(sessionId: string) {
  return request<SessionDetail>(`/api/sessions/${sessionId}`, {
    headers: { Authorization: `Bearer ${await ensureAccessToken()}` },
  });
}

export async function deleteSession(sessionId: string) {
  return request<{ status: string }>(`/api/sessions/${sessionId}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${await ensureAccessToken()}` },
  });
}

export async function exportSession(sessionId: string) {
  return request<{ file_name: string; transcript_markdown: string }>(`/api/sessions/${sessionId}/export`, {
    headers: { Authorization: `Bearer ${await ensureAccessToken()}` },
  });
}

export async function uploadSessionFile(sessionId: string, file: File) {
  const accessToken = await ensureAccessToken();
  const formData = new FormData();
  formData.append("file", file);
  const response = await fetchWithSession(`/api/uploads?session_id=${encodeURIComponent(sessionId)}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}` },
    body: formData,
  });
  const payload = await parseJson(response);
  if (!response.ok) {
    throw new Error(
      payload && typeof payload === "object" && "detail" in payload
        ? String((payload as { detail: unknown }).detail)
        : "Upload failed",
    );
  }
  return payload as {
    id: string;
    filename: string;
    mime_type: string;
    document_type?: string | null;
    has_extracted_text: boolean;
    download_url?: string;
    preview_url?: string;
    preview_available?: boolean;
    ingestion_status?: string;
    extraction_status?: string | null;
    extraction_method?: string | null;
    extraction_message?: string | null;
    preview_text?: string | null;
    size_bytes?: number | null;
    created_at?: string | null;
    error_message?: string | null;
    page_count?: number | null;
    image_width?: number | null;
    image_height?: number | null;
  };
}

async function fetchUploadAsset(uploadId: string, kind: "preview" | "download") {
  const accessToken = await ensureAccessToken();
  const response = await fetchWithSession(`/api/uploads/${encodeURIComponent(uploadId)}/${kind}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!response.ok) {
    const payload = await parseJson(response);
    throw new Error(
      payload && typeof payload === "object" && "detail" in payload
        ? String((payload as { detail: unknown }).detail)
        : "Unable to open this evidence file.",
    );
  }
  return response.blob();
}

export function fetchUploadPreviewBlob(uploadId: string) {
  return fetchUploadAsset(uploadId, "preview");
}

export function fetchUploadBlob(uploadId: string) {
  return fetchUploadAsset(uploadId, "download");
}

export async function fetchReport(reportId: string) {
  return request<StoredReport>(`/api/reports/${reportId}`, {
    headers: { Authorization: `Bearer ${await ensureAccessToken()}` },
  });
}

export async function generateSessionReport(
  sessionId: string,
  payload: { query?: string; attachment_ids?: string[] } = {},
) {
  return request<GenerateReportResult>(`/api/sessions/${encodeURIComponent(sessionId)}/reports/generate`, {
    method: "POST",
    headers: { Authorization: `Bearer ${await ensureAccessToken()}` },
    body: JSON.stringify({
      query: payload.query?.trim() || undefined,
      attachment_ids: payload.attachment_ids ?? [],
    }),
  });
}

export async function downloadReport(reportId: string, format: ReportDownloadFormat) {
  const response = await fetchWithSession(
    `/api/reports/${encodeURIComponent(reportId)}/download?format=${encodeURIComponent(format)}`,
    { headers: { Authorization: `Bearer ${await ensureAccessToken()}` } },
  );
  if (!response.ok) {
    const payload = await parseJson(response);
    throw new Error(
      payload && typeof payload === "object" && "detail" in payload
        ? String((payload as { detail: unknown }).detail)
        : "The report file could not be prepared.",
    );
  }
  const disposition = response.headers.get("Content-Disposition") || "";
  const encodedName = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  const quotedName = disposition.match(/filename="([^"]+)"/i)?.[1];
  return {
    blob: await response.blob(),
    filename: encodedName
      ? decodeURIComponent(encodedName)
      : quotedName || `auditready-${reportId}.${format}`,
  };
}

export async function exportReport(reportId: string, destinationPath?: string) {
  return request<{ pdf_path: string; mcp_result?: JsonValue }>(`/api/reports/${reportId}/export`, {
    method: "POST",
    headers: { Authorization: `Bearer ${await ensureAccessToken()}` },
    body: JSON.stringify({ destination_path: destinationPath, confirm: Boolean(destinationPath) }),
  });
}

export async function sendReportEmail(reportId: string, recipient: string, subject: string) {
  return request<{ status: string; provider_response?: JsonValue }>(`/api/reports/${reportId}/send/email`, {
    method: "POST",
    headers: { Authorization: `Bearer ${await ensureAccessToken()}` },
    body: JSON.stringify({ recipient, subject, confirm: true }),
  });
}

export async function sendReportWhatsApp(reportId: string, recipient: string, summary: string) {
  return request<{ status: string; result?: JsonValue }>("/api/integrations/whatsapp/messages", {
    method: "POST",
    headers: { Authorization: `Bearer ${await ensureAccessToken()}` },
    body: JSON.stringify({
      recipient,
      body: `AuditReady AI report ${reportId}\n\n${summary}\n\nOpen your secure workspace to review the evidence and citations.`,
    }),
  });
}

export async function fetchMcpStatus() {
  return request<Record<string, { ok: boolean; server?: string; error?: string }>>("/api/integrations/mcp/status", {
    headers: { Authorization: `Bearer ${await ensureAccessToken()}` },
  });
}

export async function generateDocument(payload: {
  format: "pdf" | "docx" | "csv" | "txt" | "md";
  title: string;
  content: string;
  filename: string;
}) {
  return request<{ status: string; result: { path: string; format: string; size_bytes: number } }>(
    "/api/integrations/documents/generate",
    { method: "POST", headers: { Authorization: `Bearer ${await ensureAccessToken()}` }, body: JSON.stringify(payload) },
  );
}

export async function draftEmail(payload: {
  recipient: string;
  subject: string;
  body: string;
  attachment_paths?: string[];
}) {
  return request<{ status: string; result: JsonValue }>("/api/integrations/email/draft", {
    method: "POST",
    headers: { Authorization: `Bearer ${await ensureAccessToken()}` },
    body: JSON.stringify(payload),
  });
}

export async function fetchEmailMessages(limit = 10) {
  return request<{ result: JsonValue }>(`/api/integrations/email/messages?limit=${limit}`, {
    headers: { Authorization: `Bearer ${await ensureAccessToken()}` },
  });
}

export async function downloadEmailAttachment(messageId: string, attachmentName: string) {
  return request<{ status: string; result: JsonValue }>("/api/integrations/email/attachments/download", {
    method: "POST",
    headers: { Authorization: `Bearer ${await ensureAccessToken()}` },
    body: JSON.stringify({ message_id: messageId, attachment_name: attachmentName }),
  });
}

export async function fetchKnowledgeBaseDocuments() {
  return request<KnowledgeBaseDocument[]>("/api/admin/knowledge-base/documents", {
    headers: { Authorization: `Bearer ${await ensureAccessToken()}` },
  });
}

export async function fetchAuditLogs() {
  return request<AuditLog[]>("/api/admin/audit-logs", {
    headers: { Authorization: `Bearer ${await ensureAccessToken()}` },
  });
}

export async function fetchPipelineRuns() {
  return request<PipelineRunLog[]>("/api/admin/pipeline-runs", {
    headers: { Authorization: `Bearer ${await ensureAccessToken()}` },
  });
}

export function buildChatSocketUrl(sessionId: string, _token?: string) {
  return `${wsBaseUrl}/ws/chat/${encodeURIComponent(sessionId)}`;
}
