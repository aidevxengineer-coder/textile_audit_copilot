from __future__ import annotations

from typing import Any
import re

from app.services.schemas import ComplianceFinding, ComplianceReport, FindingReference


class ReportGuardrailService:
    """Deterministically prevents unsupported sources and overconfident audit verdicts."""

    def validate(
        self,
        report: ComplianceReport,
        *,
        retrieved_docs: list[dict[str, Any]],
        attachments: list[dict[str, Any]],
        web_findings: list[dict[str, Any]] | None = None,
    ) -> ComplianceReport:
        official_docs = [
            row for row in retrieved_docs
            if row.get("authority_level") == "authoritative"
            and row.get("source_type") != "historical_audit_example"
        ]
        historical_docs = [row for row in retrieved_docs if row.get("authority_level") == "example_not_standard"]
        upload_by_id = {str(row.get("upload_id")): row for row in attachments if row.get("upload_id")}
        upload_by_name = {str(row.get("file_name")): row for row in attachments if row.get("file_name")}
        official_urls = {str(row.get("source_url")) for row in official_docs if row.get("source_url")}
        official_labels = {
            str(value).lower()
            for row in official_docs
            for value in (row.get("title"), row.get("standard_name"), row.get("citation"), row.get("clause_reference"))
            if value
        }
        historical_urls = {str(row.get("source_url")) for row in historical_docs if row.get("source_url")}
        web_urls = {str(row.get("source_url") or row.get("url")) for row in (web_findings or []) if row.get("source_url") or row.get("url")}

        notes: list[str] = []
        guarded_findings: list[ComplianceFinding] = []
        for finding in report.findings:
            accepted: list[FindingReference] = []
            has_standard = False
            has_upload = False
            for reference in finding.references:
                if reference.source_type == "upload":
                    upload = upload_by_id.get(str(reference.upload_id)) or upload_by_name.get(str(reference.file_name))
                    if upload:
                        accepted.append(reference.model_copy(update={"upload_id": upload.get("upload_id"), "file_name": upload.get("file_name")}))
                        has_upload = True
                    else:
                        notes.append(f"Removed unknown upload reference from {finding.category}.")
                elif reference.source_type == "web":
                    if reference.source_url and reference.source_url in web_urls:
                        accepted.append(reference)
                    else:
                        notes.append(f"Removed unverified web reference from {finding.category}.")
                elif reference.source_type == "historical_example":
                    if not reference.source_url or reference.source_url in historical_urls:
                        accepted.append(reference)
                else:
                    reference_text = " ".join(str(value or "") for value in (reference.label, reference.citation)).lower()
                    label_match = any(
                        label in reference_text or reference_text in label
                        for label in official_labels
                        if len(label) > 5 and len(reference_text) > 5
                    )
                    matching_docs = [
                        row for row in official_docs
                        if (reference.source_url and row.get("source_url") == reference.source_url)
                        or any(
                            label in reference_text or reference_text in label
                            for label in (
                                str(row.get("title") or "").lower(),
                                str(row.get("standard_name") or "").lower(),
                                str(row.get("citation") or "").lower(),
                            )
                            if len(label) > 5 and len(reference_text) > 5
                        )
                    ]
                    finding_terms = self._meaningful_terms(
                        " ".join((finding.category, finding.evidence_summary, finding.remediation))
                    )
                    source_relevant = any(
                        len(finding_terms.intersection(self._meaningful_terms(
                            " ".join(str(row.get(key) or "") for key in ("title", "standard_name", "clause_reference", "snippet"))
                        ))) >= 2
                        and self._topics_align(
                            " ".join((finding.category, finding.evidence_summary, finding.remediation)),
                            " ".join(str(row.get(key) or "") for key in ("title", "standard_name", "clause_reference", "snippet")),
                        )
                        for row in matching_docs
                    )
                    if ((reference.source_url and reference.source_url in official_urls) or label_match) and source_relevant:
                        accepted.append(reference)
                        has_standard = True
                    else:
                        notes.append(f"Removed unsupported standard reference from {finding.category}.")

            if not has_upload:
                finding_terms = self._meaningful_terms(finding.evidence_summary)
                candidates = []
                for row in retrieved_docs:
                    if row.get("source_type") != "project_upload" or not row.get("upload_id"):
                        continue
                    overlap = len(finding_terms.intersection(self._meaningful_terms(str(row.get("snippet") or ""))))
                    if overlap >= 2 and str(row.get("upload_id")) in upload_by_id:
                        candidates.append((overlap, row))
                if candidates:
                    row = max(candidates, key=lambda item: item[0])[1]
                    upload = upload_by_id[str(row["upload_id"])]
                    accepted.append(FindingReference(
                        label=f"Uploaded evidence: {upload.get('file_name')}", source_type="upload",
                        upload_id=str(upload.get("upload_id")), file_name=str(upload.get("file_name")),
                        citation=row.get("clause_reference"),
                    ))
                    has_upload = True

            update: dict[str, Any] = {"references": accepted}
            if finding.verdict in {"Major", "Minor", "Compliant"} and not (has_standard and has_upload):
                missing = []
                if not has_standard:
                    missing.append("an applicable authoritative criterion")
                if not has_upload:
                    missing.append("traceable project evidence")
                update.update(
                    verdict="Needs More Evidence",
                    confidence="Low",
                    evidence_gap=f"Guardrail: requires {' and '.join(missing)}. {finding.evidence_gap}",
                )
                notes.append(f"Downgraded {finding.category}: insufficient two-source grounding.")
            guarded_findings.append(finding.model_copy(update=update))

        return report.model_copy(
            update={
                "findings": guarded_findings,
                "guardrail_notes": list(dict.fromkeys([*report.guardrail_notes, *notes])),
            }
        )

    @staticmethod
    def _meaningful_terms(value: str) -> set[str]:
        stop = {
            "about", "after", "audit", "available", "evidence", "factory", "finding", "record",
            "required", "safety", "should", "their", "there", "these", "this", "with", "without",
        }
        return {
            token for token in re.findall(r"[a-z0-9]+", value.lower())
            if len(token) > 3 and token not in stop
        }

    @staticmethod
    def _topics_align(finding_text: str, source_text: str) -> bool:
        topics = {
            "fire": {"fire", "exit", "extinguisher", "evacuation", "alarm", "drill"},
            "electrical": {"electrical", "wiring", "cable", "panel", "earthing"},
            "structural": {"structural", "building", "column", "beam", "crack", "load"},
            "wages": {"wage", "payroll", "overtime", "salary", "attendance"},
            "chemical": {"chemical", "sds", "msds", "solvent", "spill"},
            "worker_rights": {"grievance", "union", "harassment", "forced", "child"},
        }
        finding_words = set(re.findall(r"[a-z0-9]+", finding_text.lower()))
        source_words = set(re.findall(r"[a-z0-9]+", source_text.lower()))
        finding_topics = {name for name, words in topics.items() if finding_words.intersection(words)}
        if not finding_topics:
            return True
        return any(source_words.intersection(topics[name]) for name in finding_topics)
