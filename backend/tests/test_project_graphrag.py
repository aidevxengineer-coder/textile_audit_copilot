from __future__ import annotations

from pathlib import Path

import chromadb

from app.services.project_graphrag_service import ProjectGraphRAGService


class FakeEmbedder:
    def encode(self, texts, **kwargs):
        if isinstance(texts, str):
            texts = [texts]
        return [[float("fire" in text.lower()), float("wage" in text.lower()), 0.5] for text in texts]


class FakeRetrieval:
    def __init__(self, path: Path):
        self.client = chromadb.PersistentClient(path=str(path))
        self.embedder = FakeEmbedder()
        self.settings = type("Settings", (), {"graph_store_path": path / "knowledge_graph.json"})()

    def embed_text(self, text: str):
        return self.embedder.encode([text])[0]


def test_project_graphrag_isolates_projects_and_builds_topics(tmp_path: Path) -> None:
    service = ProjectGraphRAGService(FakeRetrieval(tmp_path))
    service.ensure_uploads_indexed(
        "project-a",
        [{"upload_id": "a1", "file_name": "fire-cap.xlsx", "document_type": "safety", "extracted_text": "[Sheet: Fire CAP | Row: 12] Blocked fire exit. Corrective action target date is August."}],
    )
    service.ensure_uploads_indexed(
        "project-b",
        [{"upload_id": "b1", "file_name": "payroll.csv", "document_type": "payroll", "extracted_text": "Worker wage and overtime payroll records."}],
    )

    fire_results = service.search("project-a", "fire exit", query_variant="original")
    other_results = service.search("project-b", "fire exit", query_variant="original")

    assert fire_results
    assert all(result.audit_unit == "project-a" for result in fire_results)
    assert all(result.source_type == "project_upload" for result in fire_results)
    assert fire_results[0].clause_reference == "Sheet: Fire CAP | Row: 12"
    assert all(result.audit_unit == "project-b" for result in other_results)
    graph = service._load_graph("project-a")
    assert "fire_safety" in graph["topics"]
    assert "corrective_action" in graph["topics"]
