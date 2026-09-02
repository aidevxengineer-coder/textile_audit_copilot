from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.config import get_settings
from app.services.ollama_service import OllamaService
from app.services.schemas import GraphExtractionResult


GRAPH_EXTRACTION_PROMPT = """
You extract compliance-domain entities and relationships from the supplied text.
Return JSON matching this schema:
{
  "entities": [{"id": "slug", "name": "...", "topic": "...", "aliases": ["..."], "standards": ["..."], "chunk_ids": ["..."]}],
  "relationships": [{"source": "entity-id", "target": "entity-id", "type": "...", "weight": 1.0, "evidence": "..."}]
}
Rules:
- Focus on standards, principles, clauses, hazards, documents, audit themes, Pakistani law references, and remediation concepts.
- Use stable lowercase slug ids.
- Include chunk_ids for every entity mentioned.
- Do not invent unsupported entities or relationships.
"""


class LightRAGCompatibilityService:
    def __init__(self, ollama_service: OllamaService | None = None) -> None:
        self.settings = get_settings()
        self.ollama_service = ollama_service or OllamaService()
        self.use_lightrag_core = self.settings.use_lightrag_core

    async def extract_graph_elements(self, *, chunk_id: str, text: str) -> GraphExtractionResult:
        messages = [
            SystemMessage(content=GRAPH_EXTRACTION_PROMPT),
            HumanMessage(content=f"chunk_id={chunk_id}\n\n{text[:5000]}"),
        ]
        result = await self.ollama_service.invoke_structured(GraphExtractionResult, messages)
        entities = []
        for entity in result.entities:
            entity = dict(entity)
            entity.setdefault("chunk_ids", [])
            if chunk_id not in entity["chunk_ids"]:
                entity["chunk_ids"].append(chunk_id)
            entities.append(entity)
        return GraphExtractionResult(entities=entities, relationships=result.relationships)

    def write_lightrag_manifest(self, metadata: dict[str, Any]) -> None:
        Path(self.settings.lightrag_workdir).mkdir(parents=True, exist_ok=True)
        manifest_path = Path(self.settings.lightrag_workdir) / "compat_manifest.json"
        manifest_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
