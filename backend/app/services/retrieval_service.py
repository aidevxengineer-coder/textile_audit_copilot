from __future__ import annotations

import json
import re
from collections import defaultdict
from functools import cached_property
from pathlib import Path
from threading import Lock
from typing import Any

import networkx as nx

from app.config import get_settings
from app.services.schemas import RetrievedDocument


TOKEN_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]+", re.IGNORECASE)
_EMBEDDERS: dict[str, Any] = {}
_EMBEDDER_LOCK = Lock()


def _shared_embedder(model_name: str):
    """Load the embedding model once per API process."""

    with _EMBEDDER_LOCK:
        embedder = _EMBEDDERS.get(model_name)
        if embedder is None:
            from sentence_transformers import SentenceTransformer

            embedder = SentenceTransformer(model_name)
            _EMBEDDERS[model_name] = embedder
        return embedder


class RetrievalService:
    def __init__(self) -> None:
        self.settings = get_settings()
        import chromadb

        self.client = chromadb.PersistentClient(path=str(self.settings.chroma_dir))
        if any(collection.name == "project_evidence" for collection in self.client.list_collections()):
            # Legacy versions persisted confidential project chunks beside the
            # public corpus. ProjectGraphRAGService now uses memory-only storage.
            self.client.delete_collection("project_evidence")
        self.collection = self.client.get_or_create_collection(name="compliance_docs")

    @cached_property
    def embedder(self):
        return _shared_embedder(self.settings.embedding_model)

    def embed_text(self, text: str) -> list[float]:
        return self.embedder.encode(text).tolist()

    def upsert_chunks(self, chunks: list[dict[str, Any]]) -> None:
        if not chunks:
            return
        batch_size = 128
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            ids = [chunk["id"] for chunk in batch]
            documents = [chunk["text"] for chunk in batch]
            metadatas = [chunk["metadata"] for chunk in batch]
            embeddings = self.embedder.encode(documents, batch_size=32, show_progress_bar=False).tolist()
            self.collection.upsert(ids=ids, documents=documents, metadatas=metadatas, embeddings=embeddings)

    def local_search(
        self,
        query: str,
        *,
        query_variant: str,
        top_k: int | None = None,
        authority_level: str | None = None,
    ) -> list[RetrievedDocument]:
        top_k = top_k or self.settings.retrieval_top_k
        query_args: dict[str, Any] = {"query_embeddings": [self.embed_text(query)], "n_results": top_k}
        if authority_level:
            query_args["where"] = {"authority_level": authority_level}
        result = self.collection.query(**query_args)
        documents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        ids = result.get("ids", [[]])[0]
        distances = result.get("distances", [[]])[0]

        retrieved: list[RetrievedDocument] = []
        for doc_id, snippet, metadata, distance in zip(ids, documents, metadatas, distances, strict=False):
            score = max(0.0, 1.0 - float(distance))
            retrieved.append(
                RetrievedDocument(
                    doc_id=doc_id,
                    title=metadata.get("title", "Untitled"),
                    standard_name=metadata.get("standard_name", "Unknown Standard"),
                    citation=metadata.get("citation"),
                    clause_reference=metadata.get("clause_reference"),
                    source_url=metadata.get("source_url"),
                    source_type=metadata.get("source_type", "authoritative_standard"),
                    authority_level=metadata.get("authority_level", "authoritative"),
                    dataset=metadata.get("dataset"),
                    audit_unit=metadata.get("audit_unit"),
                    document_type=metadata.get("document_type"),
                    upload_id=metadata.get("upload_id"),
                    snippet=snippet[:1000],
                    score=score,
                    retrieval_mode="local",
                    query_variant=query_variant,  # type: ignore[arg-type]
                )
            )
        return retrieved

    def balanced_search(self, query: str, *, query_variant: str, top_k: int | None = None) -> list[RetrievedDocument]:
        """Blend semantic matches with reserved authoritative-standard coverage."""
        top_k = top_k or self.settings.retrieval_top_k
        broad = self.local_search(query, query_variant=query_variant, top_k=top_k)
        official = self.local_search(
            query,
            query_variant=query_variant,
            top_k=max(3, top_k // 2),
            authority_level="authoritative",
        )
        combined: list[RetrievedDocument] = []
        seen: set[str] = set()
        # Put the strongest official match first so it survives compact prompt limits.
        for item in [*official[:1], *broad, *official[1:]]:
            if item.doc_id not in seen:
                seen.add(item.doc_id)
                combined.append(item)
        return combined[: top_k + max(2, top_k // 2)]

    def global_search(self, query: str, *, query_variant: str, top_k: int | None = None) -> list[RetrievedDocument]:
        top_k = top_k or self.settings.retrieval_top_k
        graph = self.load_graph()
        if graph.number_of_nodes() == 0:
            return []

        terms = {token.lower() for token in TOKEN_PATTERN.findall(query)}
        if not terms:
            return []

        scored_chunk_ids: dict[str, float] = defaultdict(float)
        for node_id, attrs in graph.nodes(data=True):
            keywords = {
                token.lower()
                for token in TOKEN_PATTERN.findall(
                    " ".join(
                        [
                            str(attrs.get("name", "")),
                            str(attrs.get("topic", "")),
                            " ".join(attrs.get("aliases", [])),
                            " ".join(attrs.get("standards", [])),
                        ]
                    )
                )
            }
            overlap = len(terms.intersection(keywords))
            if overlap == 0:
                continue

            seed_score = overlap / max(1, len(terms))
            neighbors = nx.single_source_shortest_path_length(graph, node_id, cutoff=self.settings.graph_hops)
            for neighbor_id, distance in neighbors.items():
                neighbor_attrs = graph.nodes[neighbor_id]
                decay = 1 / (1 + distance)
                for chunk_id in neighbor_attrs.get("chunk_ids", []):
                    scored_chunk_ids[chunk_id] += seed_score * decay

        if not scored_chunk_ids:
            return []

        ranked_ids = [chunk_id for chunk_id, _ in sorted(scored_chunk_ids.items(), key=lambda item: item[1], reverse=True)]
        ranked_ids = ranked_ids[:top_k]
        payload = self.collection.get(ids=ranked_ids, include=["documents", "metadatas"])
        docs_by_id = {
            doc_id: (document, metadata)
            for doc_id, document, metadata in zip(
                payload.get("ids", []),
                payload.get("documents", []),
                payload.get("metadatas", []),
                strict=False,
            )
        }

        retrieved: list[RetrievedDocument] = []
        for chunk_id in ranked_ids:
            document, metadata = docs_by_id.get(chunk_id, ("", {}))
            retrieved.append(
                RetrievedDocument(
                    doc_id=chunk_id,
                    title=metadata.get("title", "Untitled"),
                    standard_name=metadata.get("standard_name", "Unknown Standard"),
                    citation=metadata.get("citation"),
                    clause_reference=metadata.get("clause_reference"),
                    source_url=metadata.get("source_url"),
                    source_type=metadata.get("source_type", "authoritative_standard"),
                    authority_level=metadata.get("authority_level", "authoritative"),
                    dataset=metadata.get("dataset"),
                    audit_unit=metadata.get("audit_unit"),
                    document_type=metadata.get("document_type"),
                    upload_id=metadata.get("upload_id"),
                    snippet=str(document)[:1000],
                    score=float(scored_chunk_ids[chunk_id]),
                    retrieval_mode="global",
                    query_variant=query_variant,  # type: ignore[arg-type]
                )
            )
        return retrieved

    def save_graph(self, *, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> None:
        self.settings.graph_store_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings.graph_store_path.write_text(json.dumps({"nodes": nodes, "edges": edges}, indent=2), encoding="utf-8")
        index = {node["id"]: node for node in nodes}
        self.settings.graph_index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")
        self.__dict__.pop("_graph_cache", None)

    def load_graph(self) -> nx.Graph:
        cached = self.__dict__.get("_graph_cache")
        if cached is not None:
            return cached
        graph = nx.Graph()
        path = Path(self.settings.graph_store_path)
        if not path.exists():
            return graph
        payload = json.loads(path.read_text(encoding="utf-8"))
        for node in payload.get("nodes", []):
            graph.add_node(node["id"], **{key: value for key, value in node.items() if key != "id"})
        for edge in payload.get("edges", []):
            graph.add_edge(edge["source"], edge["target"], **{key: value for key, value in edge.items() if key not in {"source", "target"}})
        self.__dict__["_graph_cache"] = graph
        return graph

    def list_knowledge_base_documents(self) -> list[dict[str, Any]]:
        payload = self.collection.get(include=["metadatas"])
        results = []
        for doc_id, metadata in zip(payload.get("ids", []), payload.get("metadatas", []), strict=False):
            results.append({"id": doc_id, **(metadata or {})})
        return results


def reciprocal_rank_fusion(result_sets: list[list[RetrievedDocument]], *, k: int = 60) -> tuple[list[RetrievedDocument], dict[str, float]]:
    scores: dict[str, float] = defaultdict(float)
    documents: dict[str, RetrievedDocument] = {}

    for result_set in result_sets:
        for rank, item in enumerate(result_set, start=1):
            scores[item.doc_id] += 1 / (k + rank)
            documents[item.doc_id] = item

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    fused = [documents[doc_id].model_copy(update={"score": score}) for doc_id, score in ranked]
    return fused, dict(scores)
