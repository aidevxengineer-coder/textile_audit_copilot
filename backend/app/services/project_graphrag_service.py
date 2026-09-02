from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import chromadb

from app.services.retrieval_service import RetrievalService
from app.services.schemas import RetrievedDocument


TOKEN_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]+", re.IGNORECASE)
TOPICS = {
    "fire_safety": ["fire", "exit", "alarm", "extinguisher", "evacuation"],
    "electrical_safety": ["electrical", "wiring", "cable", "panel", "earthing"],
    "structural_safety": ["structural", "column", "beam", "load", "crack"],
    "corrective_action": ["corrective action", "remediation", "target date", "progress", "verification"],
    "wages_hours": ["wage", "payroll", "overtime", "working hours", "attendance"],
    "worker_rights": ["grievance", "union", "harassment", "forced labour", "child labour"],
    "chemical_safety": ["chemical", "msds", "sds", "spill", "solvent"],
    "ppe_training": ["ppe", "training", "helmet", "gloves", "competency"],
}
_PROJECT_CLIENT = chromadb.EphemeralClient()
_PROJECT_GRAPHS: dict[str, dict[str, Any]] = {}


class ProjectGraphRAGService:
    """Project-isolated vector + lightweight evidence graph for uploaded documents."""

    def __init__(self, retrieval_service: RetrievalService) -> None:
        self.retrieval = retrieval_service
        # Project evidence may contain confidential factory data. Keep vectors
        # memory-only and rebuild from encrypted PostgreSQL text after restart.
        self.collection = _PROJECT_CLIENT.get_or_create_collection(name="project_evidence")
        self.graph_dir = Path(retrieval_service.settings.graph_store_path).parent / "project_graphs"

    @staticmethod
    def _chunks(text: str, size: int = 900, overlap: int = 150) -> list[str]:
        cleaned = re.sub(r"\s+", " ", text).strip()
        result: list[str] = []
        start = 0
        while start < len(cleaned):
            end = min(len(cleaned), start + size)
            if cleaned[start:end].strip():
                result.append(cleaned[start:end].strip())
            if end == len(cleaned):
                break
            start = end - overlap
        return result

    def _graph_path(self, project_id: str) -> Path:
        safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", project_id)
        return self.graph_dir / f"{safe_id}.json"

    def _load_graph(self, project_id: str) -> dict[str, Any]:
        return _PROJECT_GRAPHS.setdefault(project_id, {"project_id": project_id, "topics": {}, "uploads": {}})

    def _save_graph(self, project_id: str, graph: dict[str, Any]) -> None:
        _PROJECT_GRAPHS[project_id] = graph

    def ensure_uploads_indexed(self, project_id: str, attachments: list[dict[str, Any]]) -> None:
        graph = self._load_graph(project_id)
        changed = False
        for attachment in attachments:
            upload_id = str(attachment.get("upload_id") or "")
            text = str(attachment.get("extracted_text") or "").strip()
            if not upload_id or not text or upload_id in graph["uploads"]:
                continue
            chunks = self._chunks(text)
            records = []
            topic_map: dict[str, list[str]] = defaultdict(list)
            for index, chunk in enumerate(chunks):
                chunk_id = "project-" + hashlib.sha256(f"{project_id}:{upload_id}:{index}".encode()).hexdigest()
                lowered = chunk.lower()
                topics = [name for name, hints in TOPICS.items() if any(hint in lowered for hint in hints)]
                for topic in topics:
                    topic_map[topic].append(chunk_id)
                location_match = re.search(
                    r"\[(Page\s+\d+(?:\s*\|\s*OCR)?|Sheet:\s*[^\]|]+\s*\|\s*Row:\s*\d+|Row\s+\d+|Paragraph\s+\d+|Table\s+\d+\s*\|\s*Row\s+\d+)\]",
                    chunk,
                    re.IGNORECASE,
                )
                location = location_match.group(1).strip() if location_match else f"Evidence chunk {index + 1}"
                records.append(
                    {
                        "id": chunk_id,
                        "text": chunk,
                        "metadata": {
                            "project_id": project_id,
                            "upload_id": upload_id,
                            "title": str(attachment.get("file_name") or "Uploaded evidence"),
                            "standard_name": "User Project Evidence",
                            "citation": f"Uploaded file: {attachment.get('file_name') or upload_id}",
                            "clause_reference": location,
                            "source_url": "",
                            "source_type": "project_upload",
                            "authority_level": "user_evidence",
                            "dataset": "project_uploads",
                            "audit_unit": project_id,
                            "document_type": str(attachment.get("document_type") or "general"),
                        },
                    }
                )
            self._upsert(records)
            graph["uploads"][upload_id] = {
                "file_name": attachment.get("file_name"),
                "document_type": attachment.get("document_type"),
                "chunk_ids": [record["id"] for record in records],
                "topics": sorted(topic_map),
            }
            for topic, chunk_ids in topic_map.items():
                current = set(graph["topics"].get(topic, []))
                graph["topics"][topic] = sorted(current | set(chunk_ids))
            changed = True
        if changed:
            self._save_graph(project_id, graph)

    def _upsert(self, records: list[dict[str, Any]]) -> None:
        for start in range(0, len(records), 128):
            batch = records[start : start + 128]
            documents = [record["text"] for record in batch]
            encoded = self.retrieval.embedder.encode(documents, batch_size=32, show_progress_bar=False)
            embeddings = encoded.tolist() if hasattr(encoded, "tolist") else encoded
            self.collection.upsert(
                ids=[record["id"] for record in batch],
                documents=documents,
                metadatas=[record["metadata"] for record in batch],
                embeddings=embeddings,
            )

    def search(
        self,
        project_id: str,
        query: str,
        *,
        query_variant: str,
        top_k: int = 6,
        upload_ids: list[str] | None = None,
    ) -> list[RetrievedDocument]:
        where: dict[str, Any]
        if upload_ids:
            where = {"$and": [{"project_id": project_id}, {"upload_id": {"$in": upload_ids}}]}
        else:
            where = {"project_id": project_id}
        result = self.collection.query(
            query_embeddings=[self.retrieval.embed_text(query)],
            n_results=top_k,
            where=where,
        )
        candidates: dict[str, RetrievedDocument] = {}
        for doc_id, text, metadata, distance in zip(
            result.get("ids", [[]])[0], result.get("documents", [[]])[0],
            result.get("metadatas", [[]])[0], result.get("distances", [[]])[0], strict=False,
        ):
            candidates[doc_id] = self._document(doc_id, text, metadata, max(0.0, 1.0 - float(distance)), query_variant)

        graph = self._load_graph(project_id)
        query_terms = {token.lower() for token in TOKEN_PATTERN.findall(query)}
        graph_ids: list[str] = []
        for topic, hints in TOPICS.items():
            if topic in query_terms or query_terms.intersection(hints):
                graph_ids.extend(graph.get("topics", {}).get(topic, []))
        graph_ids = list(dict.fromkeys(graph_ids))[:top_k]
        if graph_ids and not upload_ids:
            payload = self.collection.get(ids=graph_ids, include=["documents", "metadatas"])
            for doc_id, text, metadata in zip(payload["ids"], payload["documents"], payload["metadatas"], strict=False):
                if metadata.get("project_id") == project_id and doc_id not in candidates:
                    candidates[doc_id] = self._document(doc_id, text, metadata, 0.5, query_variant)
        return sorted(candidates.values(), key=lambda item: item.score, reverse=True)[:top_k]

    @staticmethod
    def _document(doc_id: str, text: str, metadata: dict[str, Any], score: float, query_variant: str) -> RetrievedDocument:
        return RetrievedDocument(
            doc_id=doc_id, title=metadata.get("title", "Uploaded evidence"),
            standard_name="User Project Evidence", citation=metadata.get("citation"),
            clause_reference=metadata.get("clause_reference"), source_url=None,
            source_type="project_upload", authority_level="user_evidence",
            dataset="project_uploads", audit_unit=metadata.get("project_id"),
            document_type=metadata.get("document_type"), snippet=str(text)[:1000], score=score,
            upload_id=metadata.get("upload_id"),
            retrieval_mode="local", query_variant=query_variant,
        )
