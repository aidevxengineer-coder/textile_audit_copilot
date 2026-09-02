import { cookies } from "next/headers";
import { forbidden, notFound, redirect } from "next/navigation";

import { apiBaseUrl, publicAppUrl } from "@/lib/config";
import type {
  AdminSystemStatus,
  AuditLog,
  KnowledgeBaseDocument,
  PipelineRunLog,
  ProjectSummary,
  SessionSummary,
  StoredReport,
  User,
} from "@/lib/types";

async function cookieHeader() {
  const cookieStore = await cookies();
  return cookieStore
    .getAll()
    .map(({ name, value }) => `${name}=${value}`)
    .join("; ");
}

async function baseServerRequest(path: string, init?: RequestInit): Promise<Response> {
  const headers = new Headers(init?.headers || {});
  headers.set("cookie", await cookieHeader());
  if (init?.method && !["GET", "HEAD", "OPTIONS"].includes(init.method.toUpperCase())) {
    headers.set("Origin", publicAppUrl);
  }
  return fetch(`${apiBaseUrl}${path}`, {
    ...init,
    headers,
    cache: "no-store",
  });
}

async function authorizedServerRequest(path: string, init?: RequestInit): Promise<Response> {
  const initial = await baseServerRequest(path, init);
  if (initial.status !== 401) {
    return initial;
  }

  const refreshResponse = await baseServerRequest("/api/auth/refresh", {
    method: "POST",
    body: JSON.stringify({}),
    headers: { "Content-Type": "application/json" },
  });

  if (!refreshResponse.ok) {
    return initial;
  }

  const refreshPayload = (await refreshResponse.json()) as { access_token: string };
  const headers = new Headers(init?.headers || {});
  headers.set("cookie", await cookieHeader());
  headers.set("Authorization", `Bearer ${refreshPayload.access_token}`);

  return fetch(`${apiBaseUrl}${path}`, {
    ...init,
    headers,
    cache: "no-store",
  });
}

export async function requireServerUser(role?: User["role"]) {
  const response = await authorizedServerRequest("/api/auth/me");
  if (response.status === 401) {
    redirect("/login");
  }
  if (!response.ok) {
    redirect("/login");
  }
  const user = (await response.json()) as User;
  if (role && user.role !== role) {
    forbidden();
  }
  return user;
}

export async function getOptionalServerUser() {
  const response = await authorizedServerRequest("/api/auth/me");
  if (!response.ok) {
    return null;
  }
  return (await response.json()) as User;
}

export async function getServerSessions() {
  const response = await authorizedServerRequest("/api/sessions");
  if (!response.ok) {
    return [];
  }
  return (await response.json()) as SessionSummary[];
}

export async function getServerProjects() {
  const response = await authorizedServerRequest("/api/projects");
  if (!response.ok) {
    return [];
  }
  return (await response.json()) as ProjectSummary[];
}

export async function getServerReport(reportId: string) {
  const response = await authorizedServerRequest(`/api/reports/${reportId}`);
  if (response.status === 404) {
    notFound();
  }
  if (!response.ok) {
    redirect("/chat");
  }
  return (await response.json()) as StoredReport;
}

export async function getAdminScreenData() {
  const [documentsResponse, auditResponse, statusResponse, pipelineRunsResponse] = await Promise.all([
    authorizedServerRequest("/api/admin/knowledge-base/documents"),
    authorizedServerRequest("/api/admin/audit-logs"),
    authorizedServerRequest("/api/admin/system-status"),
    authorizedServerRequest("/api/admin/pipeline-runs"),
  ]);

  return {
    documents: documentsResponse.ok ? ((await documentsResponse.json()) as KnowledgeBaseDocument[]) : [],
    logs: auditResponse.ok ? ((await auditResponse.json()) as AuditLog[]) : [],
    systemStatus: statusResponse.ok ? ((await statusResponse.json()) as AdminSystemStatus) : null,
    pipelineRuns: pipelineRunsResponse.ok ? ((await pipelineRunsResponse.json()) as PipelineRunLog[]) : [],
  };
}
