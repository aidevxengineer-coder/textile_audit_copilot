import { ReportActions } from "@/components/report/report-actions";
import { apiBaseUrl } from "@/lib/config";
import type { ComplianceReport, StoredReport } from "@/lib/types";

function buildUploadDownloadUrl(uploadId: string) {
  return `${apiBaseUrl}/api/uploads/${encodeURIComponent(uploadId)}/download`;
}

function groupFindings(report: ComplianceReport) {
  const buckets = {
    Major: report.findings.filter((finding) => finding.verdict === "Major"),
    Minor: report.findings.filter((finding) => finding.verdict === "Minor"),
    Compliant: report.findings.filter((finding) => finding.verdict === "Compliant"),
    "Needs More Evidence": report.findings.filter((finding) => finding.verdict === "Needs More Evidence"),
  };
  return buckets;
}

export function ReportView({ report }: { report: StoredReport }) {
  const structured = report.structured_report;

  if (!structured) {
    return (
      <div className="report-shell">
        <div className="panel">
          <h1>Report unavailable</h1>
          <p>{report.response_text}</p>
        </div>
      </div>
    );
  }

  const grouped = groupFindings(structured);

  return (
    <div className="report-shell">
      <section className="report-hero panel">
        <div className="report-hero-heading"><div><p className="eyebrow">Pre-audit report</p>
        <h1>Gap analysis</h1></div><span className="page-status"><i /> Grounded in retrieved evidence</span></div>
        <p>{structured.executive_summary}</p>
        <small className="report-limitation">Pre-screening only—not a pass guarantee. Confirm findings through records, interviews, and on-site checks.</small>
      </section>
      <section className="report-summary-grid">
        {Object.entries(grouped).map(([label, findings]) => (
          <article key={label} className="metric-card">
            <span>{label}</span>
            <strong>{findings.length}</strong>
          </article>
        ))}
      </section>
      <div className="report-dashboard-grid">
      <section className="report-card-grid" aria-label="Audit findings">
        {structured.findings.map((finding) => (
          <article
            key={`${finding.category}-${finding.clause_reference}`}
            className={`finding-card finding-${finding.verdict.toLowerCase().replaceAll(" ", "-")}`}
          >
            <div className="finding-head">
              <span className="status-pill">{finding.verdict}</span>
              <span className="confidence-pill">{finding.confidence} confidence</span>
            </div>
            <h3>{finding.category}</h3>
            <p className="clause-line">
              {finding.standard_name} · {finding.clause_reference}
            </p>
            <p>{finding.evidence_summary}</p>
            {(finding.references || []).length ? (
              <div className="finding-references">
                <strong>References</strong>
                <div className="reference-chip-list">
                  {(finding.references || []).map((reference, index) => {
                    const href =
                      reference.source_type === "upload" && reference.upload_id
                        ? buildUploadDownloadUrl(reference.upload_id)
                        : reference.source_url;
                    if (href) {
                      return (
                        <a
                          key={`${finding.category}-reference-${index}`}
                          className="file-chip inline-file-link"
                          href={href}
                          rel="noreferrer"
                          target="_blank"
                        >
                          {reference.label}
                        </a>
                      );
                    }
                    return (
                      <span key={`${finding.category}-reference-${index}`} className="file-chip">
                        {reference.label}
                      </span>
                    );
                  })}
                </div>
              </div>
            ) : null}
            <div className="finding-detail-grid">
              <section><strong>Audit risk</strong><p>{finding.audit_risk || "Requires verification during the external audit."}</p></section>
              <section><strong>Evidence gap</strong><p>{finding.evidence_gap || "No additional evidence gap recorded."}</p></section>
              <section><strong>Recommended fix</strong><p>{finding.remediation}</p></section>
              <section><strong>Closure evidence</strong>{finding.recommended_evidence?.length ? <ul className="clean-list">{finding.recommended_evidence.map((item) => <li key={item}>{item}</li>)}</ul> : <p>Documented verification of corrective action.</p>}</section>
            </div>
          </article>
        ))}
      </section>
      <aside className="report-insight-stack" aria-label="Recommended next steps">
        <article className="panel report-next-panel">
          <h2>Next steps</h2>
          <section><h3>Recommended actions</h3><ul className="clean-list">{structured.recommended_actions.map((action) => <li key={action}>{action}</li>)}</ul></section>
          <section><h3>Questions to resolve</h3><ul className="clean-list">{structured.next_best_questions.map((question) => <li key={question}>{question}</li>)}</ul></section>
          {structured.critical_missing_documents?.length ? <section><h3>Missing documents</h3><ul className="clean-list">{structured.critical_missing_documents.map((item) => <li key={item}>{item}</li>)}</ul></section> : null}
          {structured.scope_reviewed?.length ? <section><h3>Scope reviewed</h3><ul className="clean-list">{structured.scope_reviewed.slice(0, 2).map((item) => <li key={item}>{item}</li>)}</ul></section> : null}
        </article>
      </aside>
      </div>
      <div className="report-action-dock"><ReportActions reportId={report.id} executiveSummary={structured.executive_summary} /></div>
      {structured.current_web_findings?.length ? (
        <section className="panel">
          <div className="panel-head">
            <div>
              <p className="eyebrow">Current information check</p>
              <h2>Web-search MCP context used for this report</h2>
            </div>
            <span className="trace-badge">{structured.current_web_findings.length} items</span>
          </div>
          <ul className="clean-list">
            {structured.current_web_findings.map((finding, index) => (
              <li key={`report-web-${index}`}>
                {String(finding.title || finding.name || finding.url || "Current standards update")}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
