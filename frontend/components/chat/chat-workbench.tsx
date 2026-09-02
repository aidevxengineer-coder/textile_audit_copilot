"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { startTransition, useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";

import { ActionDialog } from "@/components/ui/action-dialog";
import { Icon } from "@/components/ui/icon";
import { PipelineStepper } from "@/components/ui/pipeline-stepper";
import {
  buildChatSocketUrl,
  createProject,
  createSession,
  deleteSession,
  ensureAccessToken,
  exportSession,
  fetchProject,
  fetchProjects,
  fetchSession,
  fetchSessions,
  fetchUploadBlob,
  fetchUploadPreviewBlob,
  forceRefreshAccessToken,
  generateSessionReport,
  uploadSessionFile,
} from "@/lib/browser-api";
import { formatPakistanDateTime } from "@/lib/dates";
import type {
  ComplianceReport,
  PipelineEvent,
  ProjectDetail,
  ProjectSummary,
  SessionDetail,
  SessionSummary,
  User,
} from "@/lib/types";

function AssistantMessage({ content }: { content: string }) {
  return <div className="message-markdown"><ReactMarkdown>{content}</ReactMarkdown></div>;
}

type WorkspaceView = "projects" | "review" | "evidence";
type UploadItem = SessionDetail["uploads"][number];
type PendingUpload = { file: File; state: "uploading" | "processing" | "failed"; error?: string };
type ReportFeedback = {
  kind: "success" | "warning";
  message: string;
  missingEvidence?: string[];
};

const starterPrompts = [
  "What should I upload before a buyer audit?",
  "Check my project for likely health and safety gaps.",
  "What records are missing for wages and overtime?",
];

function downloadTextFile(filename: string, content: string) {
  const blob = new Blob([content], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function useEvidencePreview(upload: UploadItem | null) {
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const previewable = Boolean(upload && (upload.mime_type.startsWith("image/") || upload.mime_type === "application/pdf"));

  useEffect(() => {
    if (!upload || (!upload.mime_type.startsWith("image/") && upload.mime_type !== "application/pdf")) return;
    let disposed = false;
    let objectUrl = "";
    void fetchUploadPreviewBlob(upload.id)
      .then((blob) => {
        if (disposed) return;
        objectUrl = URL.createObjectURL(blob);
        setPreviewUrl(objectUrl);
        setFailed(false);
      })
      .catch(() => {
        if (!disposed) setFailed(true);
      });
    return () => {
      disposed = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [upload]);

  return { previewUrl: previewable ? previewUrl : null, failed: previewable ? failed : false };
}

function evidenceState(upload: UploadItem) {
  const status = upload.ingestion_status || upload.extraction_status || "";
  if (status === "failed" || upload.error_message) {
    return { label: "Needs attention", className: "failed", detail: upload.error_message || upload.extraction_message || "Processing failed" };
  }
  if (status === "needs_ocr") {
    return { label: "OCR needed", className: "attention", detail: upload.extraction_message || "This scan is saved, but readable text was not detected" };
  }
  if (status === "ready_for_visual_review") {
    return { label: "Visual ready", className: "ready", detail: upload.extraction_message || "Image stored and available for visual review" };
  }
  if (upload.has_extracted_text || status === "ready" || status === "indexed") {
    const method = upload.extraction_method === "ocr" ? "OCR text extracted and indexed" : "Text extracted and indexed";
    return { label: "Ready", className: "ready", detail: upload.extraction_message || method };
  }
  if (status) {
    return { label: "Processing", className: "processing", detail: upload.extraction_message || "AuditReady is preparing this file" };
  }
  return { label: "Stored", className: "stored", detail: upload.extraction_message || "File is attached to this project" };
}

function fileKind(upload: UploadItem) {
  if (upload.mime_type.startsWith("image/")) return "Image";
  if (upload.mime_type.includes("pdf")) return "PDF";
  if (upload.mime_type.includes("wordprocessingml")) return "Word document";
  if (upload.mime_type.includes("csv") || upload.mime_type.includes("spreadsheetml")) return "Spreadsheet";
  return upload.document_type?.replaceAll("_", " ") || "Document";
}

function EvidenceCard({ upload, onOpen }: { upload: UploadItem; onOpen: (upload: UploadItem) => void }) {
  const { previewUrl, failed } = useEvidencePreview(upload);
  const state = evidenceState(upload);
  return (
    <button className="evidence-file-card" onClick={() => onOpen(upload)} type="button">
      <span className={`evidence-file-preview ${previewUrl && upload.mime_type.startsWith("image/") ? "has-image" : ""}`}>
        {previewUrl && upload.mime_type.startsWith("image/") ? (
          // Authenticated blob URLs cannot be optimized by Next Image.
          // eslint-disable-next-line @next/next/no-img-element
          <img alt={`Preview of ${upload.filename}`} src={previewUrl} />
        ) : <Icon name={failed ? "document" : upload.mime_type.startsWith("image/") ? "eye" : "document"} />}
      </span>
      <span className="evidence-file-copy">
        <span className="evidence-file-meta"><small>{fileKind(upload)}</small><span className={`evidence-status ${state.className}`}><i />{state.label}</span></span>
        <strong title={upload.filename}>{upload.filename}</strong>
        <span>{state.detail}</span>
        {upload.preview_text ? <em>{upload.preview_text.slice(0, 120)}</em> : null}
      </span>
    </button>
  );
}

function ComposerAttachment({ upload, onRemove }: { upload: UploadItem; onRemove: (uploadId: string) => void }) {
  const { previewUrl } = useEvidencePreview(upload);
  return (
    <span className="composer-attachment">
      <span className="composer-attachment-preview">
        {previewUrl && upload.mime_type.startsWith("image/") ? (
          // Authenticated blob URLs cannot be optimized by Next Image.
          // eslint-disable-next-line @next/next/no-img-element
          <img alt="" src={previewUrl} />
        ) : <Icon name="document" />}
      </span>
      <span><strong>{upload.filename}</strong><small>{fileKind(upload)} · ready for this question</small></span>
      <button aria-label={`Remove ${upload.filename} from this question`} onClick={() => onRemove(upload.id)} type="button"><Icon name="close" /></button>
    </span>
  );
}

function EvidencePreview({ upload, onClose }: { upload: UploadItem; onClose: () => void }) {
  const { previewUrl } = useEvidencePreview(upload);
  const state = evidenceState(upload);

  async function download() {
    const blob = await fetchUploadBlob(upload.id);
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = upload.filename;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="evidence-modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section aria-label={`Evidence preview for ${upload.filename}`} aria-modal="true" className="evidence-modal" role="dialog" onMouseDown={(event) => event.stopPropagation()}>
        <header>
          <div><p className="eyebrow">Evidence preview</p><h2>{upload.filename}</h2></div>
          <button aria-label="Close preview" className="icon-button" onClick={onClose} type="button"><Icon name="close" /></button>
        </header>
        <div className="evidence-modal-body">
          {previewUrl && upload.mime_type.startsWith("image/") ? (
            // Authenticated blob URLs cannot be optimized by Next Image.
            // eslint-disable-next-line @next/next/no-img-element
            <img alt={upload.filename} className="evidence-full-image" src={previewUrl} />
          ) : previewUrl && upload.mime_type === "application/pdf" ? (
            <iframe className="evidence-pdf-preview" src={previewUrl} title={`Preview of ${upload.filename}`} />
          ) : (
            <div className="document-preview">
              <Icon name="document" />
              <strong>{fileKind(upload)}</strong>
              <p>{upload.preview_text || state.detail}</p>
            </div>
          )}
        </div>
        <footer>
          <span className={`evidence-status ${state.className}`}><i />{state.label}</span>
          <button className="button button-primary" onClick={() => void download()} type="button">Download original</button>
        </footer>
      </section>
    </div>
  );
}

export function ChatWorkbench({
  initialUser,
  initialProjects,
  initialSessions,
}: {
  initialUser: User;
  initialProjects: ProjectSummary[];
  initialSessions: SessionSummary[];
}) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const requestedView = searchParams.get("view");
  const view: WorkspaceView = requestedView === "review" || requestedView === "evidence" ? requestedView : "projects";
  const initialProjectId = initialSessions[0]?.project_id || initialProjects[0]?.id || "";
  const [projects, setProjects] = useState(initialProjects);
  const [activeProjectId, setActiveProjectId] = useState(initialProjectId);
  const [projectDetail, setProjectDetail] = useState<ProjectDetail | null>(null);
  const [sessions, setSessions] = useState(initialProjectId ? initialSessions.filter((session) => session.project_id === initialProjectId) : initialSessions);
  const [activeSessionId, setActiveSessionId] = useState(initialSessions.find((session) => session.project_id === initialProjectId)?.id || initialSessions[0]?.id || "");
  const [sessionDetail, setSessionDetail] = useState<SessionDetail | null>(null);
  const [query, setQuery] = useState("");
  const [events, setEvents] = useState<PipelineEvent[]>([]);
  const [streamedAnswer, setStreamedAnswer] = useState("");
  const [latestReport, setLatestReport] = useState<ComplianceReport | null>(null);
  const [latestReportId, setLatestReportId] = useState<string | null>(null);
  const [generatingReport, setGeneratingReport] = useState(false);
  const [reportFeedback, setReportFeedback] = useState<ReportFeedback | null>(null);
  const [uploadQueue, setUploadQueue] = useState<PendingUpload[]>([]);
  const [composerAttachmentIds, setComposerAttachmentIds] = useState<string[]>([]);
  const [selectedEvidence, setSelectedEvidence] = useState<UploadItem | null>(null);
  const [busy, setBusy] = useState(false);
  const [loadingProject, setLoadingProject] = useState(Boolean(initialProjectId));
  const [loadingSession, setLoadingSession] = useState(Boolean(initialSessions[0]?.id));
  const [creatingProject, setCreatingProject] = useState(false);
  const [creatingSession, setCreatingSession] = useState(false);
  const [bootstrappingSession, setBootstrappingSession] = useState(initialSessions.length === 0);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [dialog, setDialog] = useState<"project" | "delete" | null>(null);
  const [dialogValue, setDialogValue] = useState("");
  const [dialogBusy, setDialogBusy] = useState(false);
  const [projectQuery, setProjectQuery] = useState("");
  const [projectSort, setProjectSort] = useState<"recent" | "name">("recent");
  const [evidenceQuery, setEvidenceQuery] = useState("");
  const [evidenceType, setEvidenceType] = useState<"all" | "image" | "pdf" | "document" | "spreadsheet">("all");
  const [evidenceStatus, setEvidenceStatus] = useState<"all" | "ready" | "processing" | "attention">("all");
  const [reviewQuery, setReviewQuery] = useState("");
  const [reviewSort, setReviewSort] = useState<"recent" | "name">("recent");
  const socketRef = useRef<WebSocket | null>(null);
  const hasCompletedRef = useRef(true);
  const composerRef = useRef<HTMLTextAreaElement | null>(null);
  const composerUploadRef = useRef<HTMLInputElement | null>(null);

  const activeProject = projects.find((project) => project.id === activeProjectId) || null;
  const activeSession = sessions.find((session) => session.id === activeSessionId) || null;

  const refreshProjectWorkspace = useCallback(async (projectId: string, preferredSessionId?: string) => {
    const [project, sessionRows, projectRows] = await Promise.all([fetchProject(projectId), fetchSessions(projectId), fetchProjects()]);
    setProjects(projectRows);
    setProjectDetail(project);
    setSessions(sessionRows);
    const nextSessionId = preferredSessionId && sessionRows.some((session) => session.id === preferredSessionId)
      ? preferredSessionId
      : sessionRows[0]?.id || "";
    if (!nextSessionId) setSessionDetail(null);
    setActiveSessionId(nextSessionId);
    return { project, sessionRows, nextSessionId };
  }, []);

  useEffect(() => {
    if (!activeProjectId) return;
    startTransition(() => {
      void refreshProjectWorkspace(activeProjectId)
        .catch((loadError) => setError(loadError instanceof Error ? loadError.message : "Unable to load this project."))
        .finally(() => setLoadingProject(false));
    });
  }, [activeProjectId, refreshProjectWorkspace]);

  useEffect(() => {
    if (!activeSessionId) return;
    startTransition(() => {
      void fetchSession(activeSessionId)
        .then((detail) => {
          setSessionDetail(detail);
          setLatestReport(detail.latest_report);
          setLatestReportId(detail.latest_report_id);
        })
        .catch((loadError) => setError(loadError instanceof Error ? loadError.message : "Unable to load this review."))
        .finally(() => setLoadingSession(false));
    });
  }, [activeSessionId]);

  useEffect(() => {
    if (!projects.length && !creatingProject) void handleCreateProject(true);
    // Initial workspace creation only runs when the authenticated user has no projects.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [creatingProject, projects.length]);

  useEffect(() => {
    if (!activeProjectId || loadingProject || sessions.length || creatingSession) return;
    void handleCreateSession("First Review", true);
    // Session bootstrap is keyed to the selected project and its loaded session count.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeProjectId, creatingSession, loadingProject, sessions.length]);

  useEffect(() => () => {
    socketRef.current?.close();
    socketRef.current = null;
  }, [activeSessionId]);

  const connectAndSend = useCallback(async (payload: string) => {
    const openSocket = async (canRetryAuth: boolean) => {
      const token = canRetryAuth ? await ensureAccessToken() : await forceRefreshAccessToken();
      const socket = new WebSocket(buildChatSocketUrl(activeSessionId, token));
      socketRef.current = socket;
      let payloadSent = false;

      socket.onopen = () => {
        payloadSent = true;
        socket.send(payload);
      };
      socket.onmessage = (message) => {
        const event = JSON.parse(message.data) as PipelineEvent;
        if (event.type === "token") {
          setStreamedAnswer((current) => current + (event.value || ""));
          return;
        }
        if (event.type === "stage") {
          setEvents((current) => [...current, event]);
          return;
        }
        if (event.type === "done") {
          hasCompletedRef.current = true;
          setBusy(false);
          setLatestReport(event.payload?.final_report || null);
          setLatestReportId(event.payload?.report_id || null);
          setNotice("Review complete. The answer, evidence, and findings are ready.");
          void fetchSession(activeSessionId).then((detail) => {
            setSessionDetail(detail);
            setStreamedAnswer("");
          });
          if (activeProjectId) void refreshProjectWorkspace(activeProjectId, activeSessionId);
          return;
        }
        if (event.type === "error") {
          hasCompletedRef.current = true;
          setBusy(false);
          setError(event.detail || "The review could not be completed.");
        }
      };
      socket.onclose = (closeEvent) => {
        socketRef.current = null;
        if (hasCompletedRef.current) return;
        if (closeEvent.code === 4401 && !payloadSent && canRetryAuth) {
          void openSocket(false).catch((socketError) => {
            setBusy(false);
            setError(socketError instanceof Error ? socketError.message : "Your secure session expired.");
          });
          return;
        }
        setBusy(false);
        setError("The live review connection ended early. Your question was not sent twice; please try once more.");
      };
    };
    await openSocket(true);
  }, [activeProjectId, activeSessionId, refreshProjectWorkspace]);

  function navigateTo(nextView: WorkspaceView) {
    router.replace(`/chat?view=${nextView}`, { scroll: false });
  }

  function selectProject(projectId: string, nextView: WorkspaceView = "review") {
    if (projectId !== activeProjectId) {
      setLoadingProject(true);
      setLoadingSession(true);
      setActiveProjectId(projectId);
      setProjectDetail(null);
      setSessions([]);
      setActiveSessionId("");
      setSessionDetail(null);
      setLatestReport(null);
      setLatestReportId(null);
      setReportFeedback(null);
      setEvents([]);
    }
    navigateTo(nextView);
  }

  function selectReview(sessionId: string) {
    if (sessionId !== activeSessionId) {
      setLoadingSession(true);
      setSessionDetail(null);
      setLatestReport(null);
      setLatestReportId(null);
      setReportFeedback(null);
      setEvents([]);
      setActiveSessionId(sessionId);
    }
  }

  async function handleCreateProject(bootstrap = false, requestedName?: string) {
    const name = bootstrap ? "General Workspace" : requestedName;
    if (!name) return;
    setCreatingProject(true);
    setError(null);
    try {
      const created = await createProject({
        name,
        description: bootstrap ? "Your first project for evidence, reviews, and reports." : "Evidence, reviews, and reports for this audit project.",
      });
      setProjects(await fetchProjects());
      setLoadingProject(true);
      setLoadingSession(true);
      setActiveProjectId(created.id);
      setNotice("Project created. Add evidence before starting your review.");
      navigateTo("evidence");
    } catch (projectError) {
      setLoadingProject(false);
      setLoadingSession(false);
      setError(projectError instanceof Error ? projectError.message : "Unable to create project.");
    } finally {
      setCreatingProject(false);
    }
  }

  async function handleCreateSession(title = "New Review", bootstrap = false) {
    if (!activeProjectId) {
      setError("Create or select a project first.");
      return;
    }
    const setPending = bootstrap ? setBootstrappingSession : setCreatingSession;
    setPending(true);
    setLoadingSession(true);
    setError(null);
    try {
      const created = await createSession(title, activeProjectId);
      await refreshProjectWorkspace(activeProjectId, created.id);
      setNotice(bootstrap ? "Your first review is ready." : "New review created.");
      if (!bootstrap) navigateTo("review");
    } catch (sessionError) {
      setLoadingSession(false);
      setError(sessionError instanceof Error ? sessionError.message : "Unable to create review.");
    } finally {
      setPending(false);
    }
  }

  async function handleDeleteActiveSession() {
    if (!activeSessionId) return;
    setError(null);
    try {
      await deleteSession(activeSessionId);
      setLoadingSession(true);
      if (activeProjectId) {
        const refreshed = await refreshProjectWorkspace(activeProjectId);
        if (!refreshed.nextSessionId) {
          setSessionDetail(null);
          setLatestReport(null);
          setLatestReportId(null);
          setReportFeedback(null);
        }
      }
      setNotice("Review deleted.");
    } catch (deleteError) {
      setLoadingSession(false);
      setError(deleteError instanceof Error ? deleteError.message : "Unable to delete this review.");
    }
  }

  async function handleExportActiveSession() {
    if (!activeSessionId) return;
    try {
      const payload = await exportSession(activeSessionId);
      downloadTextFile(payload.file_name, payload.transcript_markdown);
      setNotice("Review transcript exported.");
    } catch (exportError) {
      setError(exportError instanceof Error ? exportError.message : "Unable to export this review.");
    }
  }

  async function handleGenerateReport() {
    if (!activeSessionId) {
      setError("Open a review before generating a report.");
      return;
    }
    setGeneratingReport(true);
    setReportFeedback(null);
    setError(null);
    setNotice(null);
    try {
      const result = await generateSessionReport(activeSessionId, {
        attachment_ids: visibleUploads.map((upload) => upload.id),
      });
      if (result.status === "insufficient_evidence") {
        setReportFeedback({
          kind: "warning",
          message: result.detail || "AuditReady needs more evidence before it can create a grounded report.",
          missingEvidence: result.missing_evidence || [],
        });
        return;
      }
      if (!result.report_id || !result.structured_report) {
        throw new Error("The report finished without a saved report record.");
      }
      setLatestReport(result.structured_report);
      setLatestReportId(result.report_id);
      setReportFeedback({ kind: "success", message: "Your readiness report is saved to this review and ready to open." });
      const detail = await fetchSession(activeSessionId);
      setSessionDetail(detail);
      if (activeProjectId) await refreshProjectWorkspace(activeProjectId, activeSessionId);
    } catch (reportError) {
      setError(reportError instanceof Error ? reportError.message : "Unable to generate this report.");
    } finally {
      setGeneratingReport(false);
    }
  }

  async function handleUploadFiles(files: FileList | null, attachToComposer = false) {
    if (!files?.length || !activeSessionId) return;
    setNotice(null);
    setError(null);
    const selected = Array.from(files);
    const uploadedIds: string[] = [];
    setUploadQueue(selected.map((file) => ({ file, state: "uploading" })));
    let completed = 0;
    for (const file of selected) {
      try {
        setUploadQueue((current) => current.map((item) => item.file === file ? { ...item, state: "processing" } : item));
        const uploaded = await uploadSessionFile(activeSessionId, file);
        uploadedIds.push(uploaded.id);
        completed += 1;
        setUploadQueue((current) => current.filter((item) => item.file !== file));
      } catch (uploadError) {
        const message = uploadError instanceof Error ? uploadError.message : "Upload failed.";
        setUploadQueue((current) => current.map((item) => item.file === file ? { ...item, state: "failed", error: message } : item));
        setError(`${file.name}: ${message}`);
      }
    }
    const [detail, project, refreshedProjects] = await Promise.all([
      fetchSession(activeSessionId),
      fetchProject(activeProjectId),
      fetchProjects(),
    ]);
    setSessionDetail(detail);
    setProjectDetail(project);
    setProjects(refreshedProjects);
    if (attachToComposer && uploadedIds.length) {
      setComposerAttachmentIds((current) => Array.from(new Set([...current, ...uploadedIds])));
      composerRef.current?.focus();
    }
    if (completed) setNotice(`${completed} evidence ${completed === 1 ? "file is" : "files are"} attached and available to this project.`);
  }

  async function handleSubmit() {
    if (!activeSessionId || !query.trim()) return;
    try {
      setBusy(true);
      setError(null);
      setNotice(null);
      setEvents([{ type: "stage", node_name: "Load Conversation History", status: "in_progress", detail: "Loading this review's conversation" }]);
      setStreamedAnswer("");
      hasCompletedRef.current = false;
      const refersToCurrentDocument = /\b(this|tis|attached|uploaded|current|latest)\b.{0,16}\b(document|file|pdf|spreadsheet|workbook|report)\b/i.test(query);
      const newestUpload = [...visibleUploads].sort((left, right) =>
        String(right.created_at || "").localeCompare(String(left.created_at || "")),
      )[0];
      const uploadIds = composerAttachmentIds.length
        ? composerAttachmentIds
        : refersToCurrentDocument && newestUpload
          ? [newestUpload.id]
          : [];
      await connectAndSend(JSON.stringify({ query: query.trim(), upload_ids: uploadIds }));
      setQuery("");
      setComposerAttachmentIds([]);
    } catch (submissionError) {
      hasCompletedRef.current = true;
      setBusy(false);
      setError(submissionError instanceof Error ? submissionError.message : "Unable to start the live review.");
    }
  }

  function applyPrompt(prompt: string) {
    setQuery(prompt);
    composerRef.current?.focus();
  }

  function openDialog(kind: "project" | "delete") {
    setDialogValue("");
    setDialog(kind);
  }

  async function confirmDialog() {
    if (!dialog) return;
    setDialogBusy(true);
    try {
      if (dialog === "project") await handleCreateProject(false, dialogValue.trim());
      if (dialog === "delete") await handleDeleteActiveSession();
      setDialog(null);
    } finally {
      setDialogBusy(false);
    }
  }

  const visibleUploads = useMemo(() => {
    const merged = new Map<string, UploadItem>();
    for (const upload of projectDetail?.uploads || []) merged.set(upload.id, upload);
    for (const upload of sessionDetail?.uploads || []) merged.set(upload.id, { ...merged.get(upload.id), ...upload });
    for (const upload of sessionDetail?.project_context?.shared_uploads || []) {
      const current = merged.get(upload.upload_id);
      merged.set(upload.upload_id, {
        id: upload.upload_id,
        filename: upload.file_name,
        mime_type: upload.mime_type,
        document_type: upload.document_type,
        ...current,
        preview_text: current?.preview_text || upload.preview_text,
      });
    }
    return Array.from(merged.values());
  }, [projectDetail?.uploads, sessionDetail?.project_context?.shared_uploads, sessionDetail?.uploads]);

  const messageCount = sessionDetail?.messages.length || 0;
  const canSubmit = !busy && !generatingReport && !bootstrappingSession && Boolean(activeSessionId && query.trim());
  const readyEvidenceCount = visibleUploads.filter((upload) => ["ready", "indexed"].includes(upload.ingestion_status || "") || upload.has_extracted_text).length;
  const composerAttachments = visibleUploads.filter((upload) => composerAttachmentIds.includes(upload.id));
  const filteredProjects = useMemo(() => {
    const needle = projectQuery.trim().toLowerCase();
    return projects
      .filter((project) => !needle || `${project.name} ${project.description || ""}`.toLowerCase().includes(needle))
      .sort((left, right) => projectSort === "name" ? left.name.localeCompare(right.name) : Date.parse(right.updated_at) - Date.parse(left.updated_at));
  }, [projectQuery, projectSort, projects]);
  const filteredEvidence = useMemo(() => {
    const needle = evidenceQuery.trim().toLowerCase();
    return visibleUploads.filter((upload) => {
      const kind = fileKind(upload).toLowerCase();
      const state = evidenceState(upload).className;
      const typeMatches = evidenceType === "all"
        || (evidenceType === "image" && upload.mime_type.startsWith("image/"))
        || (evidenceType === "pdf" && upload.mime_type.includes("pdf"))
        || (evidenceType === "spreadsheet" && (upload.mime_type.includes("csv") || upload.mime_type.includes("spreadsheetml") || kind.includes("spreadsheet")))
        || (evidenceType === "document" && !upload.mime_type.startsWith("image/") && !upload.mime_type.includes("pdf") && !upload.mime_type.includes("csv") && !upload.mime_type.includes("spreadsheetml"));
      const statusMatches = evidenceStatus === "all"
        || (evidenceStatus === "ready" && state === "ready")
        || (evidenceStatus === "processing" && ["processing", "stored"].includes(state))
        || (evidenceStatus === "attention" && ["attention", "failed"].includes(state));
      return typeMatches && statusMatches && (!needle || `${upload.filename} ${kind} ${upload.preview_text || ""}`.toLowerCase().includes(needle));
    });
  }, [evidenceQuery, evidenceStatus, evidenceType, visibleUploads]);
  const filteredReviews = useMemo(() => {
    const needle = reviewQuery.trim().toLowerCase();
    return sessions
      .filter((session) => !needle || session.title.toLowerCase().includes(needle))
      .sort((left, right) => reviewSort === "name" ? left.title.localeCompare(right.title) : Date.parse(right.updated_at) - Date.parse(left.updated_at));
  }, [reviewQuery, reviewSort, sessions]);

  return (
    <div className="project-workspace">
      <ActionDialog
        busy={dialogBusy}
        confirmLabel={dialog === "delete" ? "Delete review" : "Create project"}
        dangerous={dialog === "delete"}
        description={dialog === "delete" ? "This permanently removes the selected review and its messages." : "Create a project to keep its evidence, reviews, and reports together."}
        label={dialog === "project" ? "Project name" : undefined}
        onChange={setDialogValue}
        onClose={() => setDialog(null)}
        onConfirm={() => void confirmDialog()}
        open={dialog !== null}
        title={dialog === "delete" ? "Delete this review?" : "Create a project"}
        value={dialogValue}
      />
      {selectedEvidence ? <EvidencePreview onClose={() => setSelectedEvidence(null)} upload={selectedEvidence} /> : null}

      <header className="workspace-command-bar">
        <div>
          <p className="eyebrow">{view === "projects" ? "Project workspace" : view === "evidence" ? "Project evidence" : "Audit review"}</p>
          <h1>{view === "projects" ? "Choose a project to begin" : view === "evidence" ? activeProject?.name || "Evidence library" : activeSession?.title || "Review workspace"}</h1>
          <p>{view === "projects" ? "Each project keeps its own evidence, review history, and reports." : view === "evidence" ? "See exactly what was uploaded and whether AuditReady could read it." : `${activeProject?.name || "Project"} · Ask questions in plain language and follow the checks live.`}</p>
        </div>
        {view !== "projects" && projects.length > 1 ? (
          <label className="project-switcher"><span>Active project</span><select value={activeProjectId} onChange={(event) => selectProject(event.target.value, view)}>{projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label>
        ) : null}
      </header>

      {error || notice ? (
        <div className={`workspace-feedback ${error ? "error" : "success"}`} role="status">
          <Icon name={error ? "shield" : "activity"} /><span>{error || notice}</span><button aria-label="Dismiss message" onClick={() => { setError(null); setNotice(null); }} type="button"><Icon name="close" /></button>
        </div>
      ) : null}

      {view === "projects" ? (
        <section className="projects-dashboard">
          <div className="dashboard-section-heading">
            <div><h2>Your projects</h2><p>Open a project to continue its latest review, or create a clean workspace for a new audit.</p></div>
            <button className="button button-primary" disabled={creatingProject} onClick={() => openDialog("project")} type="button"><Icon name="folder" />{creatingProject ? "Creating…" : "New project"}</button>
          </div>
          <div className="workspace-filter-bar" role="search">
            <label className="filter-search"><Icon name="search" /><input aria-label="Search projects" placeholder="Search projects" value={projectQuery} onChange={(event) => setProjectQuery(event.target.value)} /></label>
            <label><span>Sort</span><select value={projectSort} onChange={(event) => setProjectSort(event.target.value as "recent" | "name")}><option value="recent">Recently updated</option><option value="name">Project name</option></select></label>
          </div>
          <div className="project-card-grid">
            {filteredProjects.map((project) => (
              <button key={project.id} className={`workspace-project-card ${project.id === activeProjectId ? "active" : ""}`} onClick={() => selectProject(project.id)} type="button">
                <span className="project-card-icon"><Icon name="folder" /></span>
                <span className="project-card-copy"><small>Updated {formatPakistanDateTime(project.updated_at)}</small><strong>{project.name}</strong><span>{project.description || "Evidence, reviews, and reports kept together."}</span></span>
                <span className="project-card-stats"><span><strong>{project.session_count}</strong> reviews</span><span><strong>{project.upload_count}</strong> files</span></span>
              </button>
            ))}
            {!filteredProjects.length ? <div className="filtered-empty">No projects match these filters.</div> : null}
          </div>
        </section>
      ) : null}

      {view === "evidence" ? (
        <section className="evidence-dashboard">
          <div className="evidence-upload-row">
            <label className={`evidence-dropzone ${!activeSessionId ? "disabled" : ""}`}>
              <input hidden multiple accept="image/jpeg,image/png,image/webp,.pdf,.docx,.txt,.csv,.xlsx" disabled={!activeSessionId} type="file" onChange={(event) => void handleUploadFiles(event.target.files)} />
              <span className="evidence-upload-icon"><Icon name="upload" /></span>
              <span><strong>Add evidence</strong><small>Images, PDFs, Word documents, Excel or CSV files, and text records</small></span>
            </label>
            <div className="evidence-summary-card"><span><strong>{visibleUploads.length}</strong>Total files</span><span><strong>{readyEvidenceCount}</strong>Text ready</span><span><strong>{visibleUploads.filter((upload) => upload.mime_type.startsWith("image/")).length}</strong>Images</span></div>
          </div>

          {uploadQueue.length ? <div className="pending-upload-list">{uploadQueue.map((item) => <div key={`${item.file.name}-${item.file.lastModified}`} className={`pending-upload ${item.state}`}><Icon name="document" /><span><strong>{item.file.name}</strong><small>{item.state === "failed" ? item.error : item.state === "processing" ? "Extracting and indexing…" : "Uploading securely…"}</small></span></div>)}</div> : null}

          <div className="dashboard-section-heading compact"><div><h2>Project evidence</h2><p>Select any file to preview it and confirm its extraction status.</p></div></div>
          <div className="workspace-filter-bar evidence-filters" role="search">
            <label className="filter-search"><Icon name="search" /><input aria-label="Search evidence" placeholder="Search file names or extracted text" value={evidenceQuery} onChange={(event) => setEvidenceQuery(event.target.value)} /></label>
            <label><span>Type</span><select value={evidenceType} onChange={(event) => setEvidenceType(event.target.value as typeof evidenceType)}><option value="all">All files</option><option value="image">Images</option><option value="pdf">PDFs</option><option value="document">Documents</option><option value="spreadsheet">Spreadsheets</option></select></label>
            <label><span>Status</span><select value={evidenceStatus} onChange={(event) => setEvidenceStatus(event.target.value as typeof evidenceStatus)}><option value="all">All statuses</option><option value="ready">Ready</option><option value="processing">Processing</option><option value="attention">Needs attention</option></select></label>
          </div>
          {loadingProject ? <div className="workspace-loading">Loading project evidence…</div> : visibleUploads.length ? (
            filteredEvidence.length ? <div className="evidence-grid">{filteredEvidence.map((upload) => <EvidenceCard key={upload.id} onOpen={setSelectedEvidence} upload={upload} />)}</div> : <div className="filtered-empty">No evidence matches these filters.</div>
          ) : (
            <div className="evidence-empty"><Icon name="upload" /><h2>No evidence attached yet</h2><p>Add the first photo, policy, PDF, spreadsheet, or record. It will remain scoped to this project and your account.</p></div>
          )}
        </section>
      ) : null}

      {view === "review" ? (
        <section className="review-dashboard">
          <aside className="review-list-panel">
            <div className="review-list-head"><div><p className="eyebrow">Reviews</p><h2>Conversation history</h2></div><button aria-label="Create a review" className="button button-primary compact-button" disabled={!activeProjectId || creatingSession || bootstrappingSession} onClick={() => void handleCreateSession()} type="button">{creatingSession ? "Creating…" : "+ New"}</button></div>
            <div className="review-list-filters"><label className="filter-search"><Icon name="search" /><input aria-label="Search reviews" placeholder="Search reviews" value={reviewQuery} onChange={(event) => setReviewQuery(event.target.value)} /></label><select aria-label="Sort reviews" value={reviewSort} onChange={(event) => setReviewSort(event.target.value as "recent" | "name")}><option value="recent">Recent first</option><option value="name">Name</option></select></div>
            <div className="review-list-scroll">
              {filteredReviews.map((session) => <button key={session.id} className={`review-list-item ${session.id === activeSessionId ? "active" : ""}`} disabled={busy} onClick={() => selectReview(session.id)} type="button"><Icon name="chat" /><span><strong>{session.title}</strong><small>{formatPakistanDateTime(session.updated_at)}</small></span></button>)}
              {!filteredReviews.length ? <div className="review-list-empty">{bootstrappingSession ? "Preparing your first review…" : sessions.length ? "No reviews match your search." : "No reviews in this project."}</div> : null}
            </div>
            <button className="review-evidence-link" onClick={() => navigateTo("evidence")} type="button"><span className="project-card-icon"><Icon name="document" /></span><span><strong>{visibleUploads.length} evidence files</strong><small>Open previews and extraction status</small></span></button>
            <details className="review-more-menu"><summary>Review options</summary><div><button disabled={!activeSessionId} onClick={() => void handleExportActiveSession()} type="button">Export transcript</button><button className="danger" disabled={!activeSessionId} onClick={() => openDialog("delete")} type="button">Delete review</button></div></details>
          </aside>

          <main className="conversation-panel">
            <header className="conversation-head">
              <div>
                <p className="eyebrow">Conversation</p>
                <h2>{sessionDetail?.title || (loadingSession ? "Opening review…" : "Ready to review")}</h2>
                <p>{initialUser.role === "admin" ? "Administrator" : "Factory user"} · {activeProject?.name}</p>
              </div>
              <div className="conversation-head-actions">
                <button className="conversation-evidence-status" onClick={() => navigateTo("evidence")} type="button"><i />{visibleUploads.length} evidence {visibleUploads.length === 1 ? "file" : "files"}</button>
                <button className="generate-report-button" disabled={!activeSessionId || busy || generatingReport} onClick={() => void handleGenerateReport()} type="button">
                  <Icon name="document" />
                  {generatingReport ? "Generating report…" : latestReportId ? "Update report" : "Generate report"}
                </button>
              </div>
            </header>

            <div className="conversation-thread">
              {!messageCount && !streamedAnswer && !loadingSession ? (
                <div className="review-welcome"><span className="review-welcome-icon"><Icon name="sparkles" /></span><p className="eyebrow">Start with a question</p><h2>What would you like to review?</h2><p>Choose an example or write your own. AuditReady checks the evidence in this project automatically.</p><div className="review-prompt-row">{starterPrompts.map((prompt) => <button key={prompt} onClick={() => applyPrompt(prompt)} type="button">{prompt}</button>)}</div></div>
              ) : null}
              {loadingSession ? <div className="workspace-loading">Loading conversation…</div> : null}
              {(sessionDetail?.messages || []).map((message, index) => (
                <article key={`${message.role}-${index}`} className={`review-message ${message.role}`}><span>{message.role === "user" ? "You" : "AuditReady AI"}</span>{message.role === "assistant" ? <AssistantMessage content={message.content} /> : <p>{message.content}</p>}{message.attachments.length ? <div className="message-attachments">{message.attachments.map((attachment) => <button key={attachment.upload_id} className="attachment-chip" onClick={() => { const upload = visibleUploads.find((item) => item.id === attachment.upload_id); if (upload) setSelectedEvidence(upload); }} type="button"><Icon name="document" />{attachment.file_name}</button>)}</div> : null}</article>
              ))}
              {streamedAnswer ? <article className="review-message assistant streaming"><span>AuditReady AI</span><AssistantMessage content={streamedAnswer} /></article> : null}
              {reportFeedback ? (
                <section className={`report-generation-feedback ${reportFeedback.kind}`} role="status">
                  <span className="report-generation-icon"><Icon name={reportFeedback.kind === "success" ? "document" : "shield"} /></span>
                  <div>
                    <p className="eyebrow">{reportFeedback.kind === "success" ? "Report ready" : "More evidence needed"}</p>
                    <h3>{reportFeedback.message}</h3>
                    {reportFeedback.missingEvidence?.length ? <ul>{reportFeedback.missingEvidence.map((item) => <li key={item}>{item}</li>)}</ul> : null}
                    <div className="report-feedback-actions">
                      {reportFeedback.kind === "warning" ? <button onClick={() => navigateTo("evidence")} type="button">Add missing evidence</button> : null}
                      {latestReportId ? <Link href={`/report/${latestReportId}`}>Open saved report <Icon name="arrow" /></Link> : null}
                    </div>
                  </div>
                  <button aria-label="Dismiss report status" className="report-feedback-close" onClick={() => setReportFeedback(null)} type="button"><Icon name="close" /></button>
                </section>
              ) : null}
              {generatingReport ? <section className="report-generation-progress" role="status"><span className="report-progress-spinner" /><div><strong>Preparing your readiness report</strong><small>AuditReady is checking the review evidence, summarizing findings, and saving the report.</small></div></section> : null}
              {latestReport && !busy ? <section className="inline-report"><div><p className="eyebrow">Latest findings</p><h3>{latestReport.executive_summary}</h3></div><div className="inline-finding-row">{latestReport.findings.slice(0, 4).map((finding) => <span key={`${finding.category}-${finding.clause_reference}`} className={`finding-pill ${finding.verdict.toLowerCase().replaceAll(" ", "-")}`}><strong>{finding.verdict}</strong>{finding.category}</span>)}</div>{latestReportId ? <Link href={`/report/${latestReportId}`}>Open the complete report <Icon name="arrow" /></Link> : null}</section> : null}
            </div>

            <div className="review-composer">
              {events.length ? <PipelineStepper complete={!busy && Boolean(latestReport)} events={events} /> : null}
              <div className="composer-title"><span><Icon name="sparkles" />Ask AuditReady AI</span><small>{composerAttachments.length ? `${composerAttachments.length} file ${composerAttachments.length === 1 ? "is" : "are"} the focus of this question` : visibleUploads.length ? `${visibleUploads.length} project files available as memory` : "You can ask now or add evidence first"}</small></div>
              {uploadQueue.length || composerAttachments.length ? (
                <div className="composer-attachment-tray" aria-live="polite">
                  {uploadQueue.map((item) => <span key={`${item.file.name}-${item.file.lastModified}`} className={`composer-upload-pending ${item.state}`}><Icon name="upload" /><span><strong>{item.file.name}</strong><small>{item.state === "failed" ? item.error : item.state === "processing" ? "Reading evidence…" : "Uploading…"}</small></span></span>)}
                  {composerAttachments.map((upload) => <ComposerAttachment key={upload.id} onRemove={(uploadId) => setComposerAttachmentIds((current) => current.filter((id) => id !== uploadId))} upload={upload} />)}
                </div>
              ) : null}
              <div className="composer-input-shell">
                <input
                  ref={composerUploadRef}
                  hidden
                  multiple
                  accept="image/jpeg,image/png,image/webp,.pdf,.docx,.txt,.csv,.xlsx"
                  disabled={busy || !activeSessionId}
                  type="file"
                  onChange={(event) => { const files = event.currentTarget.files; void handleUploadFiles(files, true); event.currentTarget.value = ""; }}
                />
                <button aria-label="Attach evidence to this question" className="composer-attach-button" disabled={busy || !activeSessionId} onClick={() => composerUploadRef.current?.click()} title="Attach image or document" type="button"><Icon name="plus" /></button>
                <textarea ref={composerRef} className="input textarea" disabled={busy || !activeSessionId} placeholder="Ask about a compliance gap, uploaded policy, factory photo, or current standards update…" value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => { if ((event.ctrlKey || event.metaKey) && event.key === "Enter") { event.preventDefault(); void handleSubmit(); } }} />
              </div>
              <div className="review-composer-actions"><span>Ctrl+Enter to send · Progress appears here live</span><button className="button button-primary" disabled={!canSubmit} onClick={() => void handleSubmit()} type="button">{busy ? "Reviewing…" : "Send question"}<Icon name="arrow" /></button></div>
            </div>
          </main>
        </section>
      ) : null}
    </div>
  );
}
