"use client";

import { useDeferredValue, useMemo, useState } from "react";

import { Icon, type IconName } from "@/components/ui/icon";
import type { AdminSystemStatus, AuditLog, KnowledgeBaseDocument, PipelineRunLog } from "@/lib/types";

import styles from "./admin-dashboard.module.css";

type Tab = "documents" | "activity" | "runs";
type Tone = "violet" | "orange" | "green" | "blue";

const PAGE_SIZE = 8;
const dateFormatter = new Intl.DateTimeFormat("en-GB", {
  dateStyle: "medium",
  timeStyle: "short",
  timeZone: "Asia/Karachi",
});

const emptyStateCopy: Record<Tab, { icon: IconName; title: string; description: string }> = {
  documents: {
    icon: "document",
    title: "No knowledge sources yet",
    description: "Ingested standards and guidance will appear here with their version, source, and citation details.",
  },
  activity: {
    icon: "shield",
    title: "No protected activity yet",
    description: "Sign-ins, uploads, exports, and administrative changes will appear here as they happen.",
  },
  runs: {
    icon: "activity",
    title: "No pipeline runs yet",
    description: "Once a review question is submitted, its execution status, steps, and tool calls will appear here.",
  },
};

function formatDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Not available" : dateFormatter.format(date);
}

function MetricCard({ detail, icon, label, tone, value }: { detail: string; icon: IconName; label: string; tone: Tone; value: number | string }) {
  return (
    <article className={`${styles.metricCard} ${styles[tone]}`}>
      <span className={styles.metricIcon}><Icon name={icon} /></span>
      <div className={styles.metricCopy}>
        <span>{label}</span>
        <strong>{value}</strong>
        <small>{detail}</small>
      </div>
    </article>
  );
}

function EmptyState({ hasSearch, tab }: { hasSearch: boolean; tab: Tab }) {
  const copy = emptyStateCopy[tab];
  return (
    <div className={styles.emptyState} role="status">
      <span className={styles.emptyIcon}><Icon name={hasSearch ? "search" : copy.icon} /></span>
      <strong>{hasSearch ? "No matching records" : copy.title}</strong>
      <p>{hasSearch ? "Try another keyword or clear the search to see all records." : copy.description}</p>
    </div>
  );
}

function RunStatus({ status }: { status: string }) {
  const normalized = status.toLowerCase();
  const tone = normalized === "completed" ? styles.badgeSuccess : normalized === "running" || normalized === "processing" ? styles.badgeActive : styles.badgeDanger;
  return <span className={`${styles.tableBadge} ${tone}`}>{status.replaceAll("_", " ")}</span>;
}

export function AdminDashboard({ documents, logs, pipelineRuns, systemStatus }: { documents: KnowledgeBaseDocument[]; logs: AuditLog[]; pipelineRuns: PipelineRunLog[]; systemStatus: AdminSystemStatus | null }) {
  const [tab, setTab] = useState<Tab>("documents");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const deferredSearch = useDeferredValue(search.trim().toLowerCase());

  const filteredRows = useMemo(() => {
    const source = tab === "documents" ? documents : tab === "activity" ? logs : pipelineRuns;
    if (!deferredSearch) return source;
    return source.filter((row) => JSON.stringify(row).toLowerCase().includes(deferredSearch));
  }, [deferredSearch, documents, logs, pipelineRuns, tab]);

  const pageCount = Math.max(1, Math.ceil(filteredRows.length / PAGE_SIZE));
  const safePage = Math.min(page, pageCount);
  const visibleRows = filteredRows.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);
  const successfulRuns = pipelineRuns.filter((run) => run.status === "completed").length;
  const toolCalls = pipelineRuns.reduce((total, run) => total + run.tools.length, 0);
  const successRate = pipelineRuns.length ? Math.round((successfulRuns / pipelineRuns.length) * 100) : 0;
  const sourceProgress = systemStatus?.source_manifest_count
    ? Math.min(100, Math.round((systemStatus.downloaded_source_count / systemStatus.source_manifest_count) * 100))
    : 0;

  function selectTab(nextTab: Tab) {
    setTab(nextTab);
    setPage(1);
    setSearch("");
  }

  const paginationStart = filteredRows.length ? (safePage - 1) * PAGE_SIZE + 1 : 0;
  const paginationEnd = Math.min(safePage * PAGE_SIZE, filteredRows.length);

  return (
    <div className={styles.dashboard}>
      <section className={styles.metricGrid} aria-label="System overview">
        <MetricCard detail={`${sourceProgress}% of the source manifest ready`} icon="document" label="Knowledge sources" tone="violet" value={systemStatus?.downloaded_source_count ?? documents.length} />
        <MetricCard detail={`${successRate}% successful completion rate`} icon="activity" label="Pipeline runs" tone="orange" value={pipelineRuns.length} />
        <MetricCard detail="Across utility and MCP integrations" icon="sparkles" label="Tool calls" tone="green" value={toolCalls} />
        <MetricCard detail="Protected, append-only records" icon="shield" label="Audit events" tone="blue" value={logs.length} />
      </section>

      <section className={styles.overviewGrid} aria-label="Readiness and integration status">
        <article className={`${styles.overviewCard} ${styles.coverageCard}`}>
          <div className={styles.cardHeading}>
            <div>
              <p>Data readiness</p>
              <h2>Knowledge coverage</h2>
            </div>
            <span className={styles.readinessBadge}>{systemStatus ? `${sourceProgress}% ready` : "Status unavailable"}</span>
          </div>
          {systemStatus ? (
            <>
              <div className={styles.progressTrack} aria-label={`${sourceProgress}% of knowledge sources downloaded`} role="progressbar" aria-valuemax={100} aria-valuemin={0} aria-valuenow={sourceProgress}>
                <span style={{ width: `${sourceProgress}%` }} />
              </div>
              <div className={styles.coverageStats}>
                <span><strong>{systemStatus.downloaded_source_count}</strong><small>Downloaded and ready</small></span>
                <span><strong>{systemStatus.source_manifest_count}</strong><small>Sources tracked</small></span>
                <span><strong>{systemStatus.supported_upload_types.length}</strong><small>Upload formats</small></span>
              </div>
            </>
          ) : (
            <p className={styles.inlineEmpty}>System coverage is temporarily unavailable. Existing administrative records remain accessible below.</p>
          )}
        </article>

        <article className={`${styles.overviewCard} ${styles.integrationCard}`}>
          <div className={styles.cardHeading}>
            <div>
              <p>Integrations</p>
              <h2>MCP services</h2>
            </div>
            <span className={styles.liveBadge}><i /> Live status</span>
          </div>
          {systemStatus ? (
            <div className={styles.integrationGrid}>
              {Object.entries(systemStatus.mcp_integrations).map(([name, enabled]) => (
                <div className={styles.integrationRow} key={name}>
                  <span className={`${styles.statusDot} ${enabled ? styles.statusOn : ""}`} />
                  <span>{name.replaceAll("_", " ")}</span>
                  <strong>{enabled ? "Enabled" : "Optional"}</strong>
                </div>
              ))}
            </div>
          ) : (
            <p className={styles.inlineEmpty}>Integration health will appear here when the backend status service reconnects.</p>
          )}
        </article>
      </section>

      <section className={styles.recordsPanel} aria-labelledby="admin-records-title">
        <div className={styles.recordsIntro}>
          <div>
            <p>Operational records</p>
            <h2 id="admin-records-title">Inspect what is happening</h2>
          </div>
          <span>Searchable and audit-ready</span>
        </div>

        <div className={styles.dataToolbar}>
          <div className={styles.dataTabs} role="tablist" aria-label="Administration data">
            <button aria-controls="admin-data-panel" aria-selected={tab === "documents"} className={tab === "documents" ? styles.activeTab : ""} id="admin-tab-documents" onClick={() => selectTab("documents")} role="tab" type="button">Documents <span>{documents.length}</span></button>
            <button aria-controls="admin-data-panel" aria-selected={tab === "activity"} className={tab === "activity" ? styles.activeTab : ""} id="admin-tab-activity" onClick={() => selectTab("activity")} role="tab" type="button">Audit activity <span>{logs.length}</span></button>
            <button aria-controls="admin-data-panel" aria-selected={tab === "runs"} className={tab === "runs" ? styles.activeTab : ""} id="admin-tab-runs" onClick={() => selectTab("runs")} role="tab" type="button">Pipeline runs <span>{pipelineRuns.length}</span></button>
          </div>
          <label className={styles.tableSearch}>
            <Icon name="search" />
            <span className="sr-only">Search {tab}</span>
            <input onChange={(event) => { setSearch(event.target.value); setPage(1); }} placeholder={`Search ${tab}...`} type="search" value={search} />
          </label>
        </div>

        <div aria-labelledby={`admin-tab-${tab}`} className={`${styles.tableShell} ${visibleRows.length ? styles.hasRows : styles.noRows}`} id="admin-data-panel" role="tabpanel">
          {visibleRows.length && tab === "documents" ? (
            <table>
              <caption className="sr-only">Knowledge base documents</caption>
              <thead><tr><th>Document</th><th>Standard</th><th>Version</th><th>Ingested</th><th>Source</th></tr></thead>
              <tbody>{(visibleRows as KnowledgeBaseDocument[]).map((document) => <tr key={document.id}><td><strong>{document.title}</strong><small>{document.citation || document.id}</small></td><td>{document.standard_name}</td><td><span className={styles.tableBadge}>{document.version || "Current"}</span></td><td>{formatDate(document.ingested_at)}</td><td>{document.source_url ? <a className={styles.tableLink} href={document.source_url} rel="noreferrer" target="_blank">Open <Icon name="arrow" /></a> : <span className={styles.mutedValue}>Unavailable</span>}</td></tr>)}</tbody>
            </table>
          ) : null}

          {visibleRows.length && tab === "activity" ? (
            <table>
              <caption className="sr-only">Protected audit activity</caption>
              <thead><tr><th>Timestamp</th><th>Action</th><th>Resource</th><th>Actor</th><th>IP address</th></tr></thead>
              <tbody>{(visibleRows as AuditLog[]).map((log) => <tr key={log.id}><td>{formatDate(log.created_at)}</td><td><span className={styles.tableBadge}>{log.action.replaceAll("_", " ")}</span></td><td><strong>{log.resource_type}</strong><small>{log.resource_id || "System event"}</small></td><td>{log.actor_user_id || "System"}</td><td>{log.ip_address || "Not recorded"}</td></tr>)}</tbody>
            </table>
          ) : null}

          {visibleRows.length && tab === "runs" ? (
            <table>
              <caption className="sr-only">RAG pipeline runs</caption>
              <thead><tr><th>Started</th><th>Status</th><th>Query</th><th>Steps</th><th>Tools</th></tr></thead>
              <tbody>{(visibleRows as PipelineRunLog[]).map((run) => <tr key={run.id}><td>{formatDate(run.created_at)}</td><td><RunStatus status={run.status} /></td><td className={styles.queryCell}>{run.original_query}</td><td>{run.steps.length}</td><td>{run.tools.length}</td></tr>)}</tbody>
            </table>
          ) : null}

          {!visibleRows.length ? <EmptyState hasSearch={Boolean(deferredSearch)} tab={tab} /> : null}
        </div>

        <div className={styles.pagination}>
          <span>Showing {paginationStart}–{paginationEnd} of {filteredRows.length}</span>
          <div>
            <button disabled={safePage <= 1} onClick={() => setPage((value) => Math.max(1, value - 1))} type="button">Previous</button>
            <span>Page {safePage} of {pageCount}</span>
            <button disabled={safePage >= pageCount} onClick={() => setPage((value) => Math.min(pageCount, value + 1))} type="button">Next</button>
          </div>
        </div>
      </section>
    </div>
  );
}
