from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import typer

from app.core.events import PipelineEmitter
from app.core.security import hash_password
from app.db.session import SessionLocal, create_db_and_seed
from app.graph.graph import build_graph
from app.graph.runtime import GraphRuntime
from app.models.user import User
from app.services.retrieval_service import RetrievalService
from app.services.project_graphrag_service import ProjectGraphRAGService


app = typer.Typer(add_completion=False)


@app.command("graphrag-status")
def graphrag_status() -> None:
    """Inspect corpus sizes, provenance labels, project graphs, and split leakage."""
    retrieval = RetrievalService()
    metadata = retrieval.collection.get(include=["metadatas"]).get("metadatas", [])
    by_authority: dict[str, int] = {}
    for row in metadata:
        authority = str((row or {}).get("authority_level") or "unknown")
        by_authority[authority] = by_authority.get(authority, 0) + 1

    project_collection = ProjectGraphRAGService(retrieval).collection
    project_metadata = project_collection.get(include=["metadatas"]).get("metadatas", [])
    project_ids = sorted({row.get("project_id") for row in project_metadata if row.get("project_id")})
    split_path = Path("data/processed/audit_dataset_split.json")
    leaks: list[dict[str, str]] = []
    if split_path.exists():
        split = json.loads(split_path.read_text(encoding="utf-8"))
        indexed = {(row.get("dataset"), row.get("audit_unit")) for row in metadata}
        for dataset, spec in split.get("datasets", {}).items():
            for unit in spec.get("test_units", []):
                if (dataset, unit) in indexed:
                    leaks.append({"dataset": dataset, "unit": unit})

    graph_path = retrieval.settings.graph_store_path
    graph = json.loads(graph_path.read_text(encoding="utf-8")) if graph_path.exists() else {}
    typer.echo(
        json.dumps(
            {
                "knowledge_chunks": len(metadata),
                "chunks_by_authority": by_authority,
                "knowledge_graph_nodes": len(graph.get("nodes", [])),
                "knowledge_graph_edges": len(graph.get("edges", [])),
                "project_evidence_chunks": len(project_metadata),
                "indexed_projects": project_ids,
                "held_out_test_leaks": leaks,
                "healthy": bool(metadata) and not leaks,
            },
            indent=2,
        )
    )


@app.command("evaluate-retrieval")
def evaluate_retrieval() -> None:
    """Run a repeatable authority/coverage check without calling the report LLM."""
    retrieval = RetrievalService()
    queries = [
        "blocked emergency exit fire safety requirement and corrective action evidence",
        "electrical panel exposed wiring inspection requirement",
        "structural building load crack engineering assessment",
        "overtime payroll attendance wage compliance records",
        "chemical inventory safety data sheet storage PPE training",
        "worker grievance mechanism freedom of association evidence",
    ]
    results = []
    for query in queries:
        docs = retrieval.balanced_search(query, query_variant="original", top_k=12)
        authorities = [doc.authority_level for doc in docs]
        results.append(
            {
                "query": query,
                "retrieved": len(docs),
                "authoritative_in_top_5": "authoritative" in authorities[:5],
                "authoritative_count": authorities.count("authoritative"),
                "historical_example_count": authorities.count("example_not_standard"),
                "top_sources": [doc.title for doc in docs[:3]],
            }
        )
    passed = sum(1 for row in results if row["authoritative_in_top_5"])
    typer.echo(
        json.dumps(
            {
                "queries": results,
                "authority_coverage": f"{passed}/{len(results)}",
                "passed": passed == len(results),
                "note": "Historical examples may retrieve highly, but every report also needs an authoritative criterion.",
            },
            indent=2,
        )
    )


@app.command()
def run(
    query: str = typer.Option(..., help="User query to run through the graph"),
    session_id: str = typer.Option("cli-session", help="Conversation session id"),
    user_id: str = typer.Option("cli-user", help="Synthetic user id for harness"),
) -> None:
    async def _emit(event: dict[str, Any]) -> None:
        print(json.dumps(event))

    async def _main() -> None:
        create_db_and_seed()
        with SessionLocal() as db:
            user = db.get(User, user_id)
            if not user:
                db.add(
                    User(
                        id=user_id,
                        # Use a syntactically valid reserved example domain so
                        # CLI-created users can also authenticate through the
                        # production EmailStr-validated API during E2E checks.
                        email=f"{user_id}@auditready.example.com",
                        full_name="CLI Harness User",
                        password_hash=hash_password("cli-harness-password"),
                        role="factory_user",
                        mfa_enabled=False,
                        must_enroll_mfa=False,
                        is_active=True,
                    )
                )
                db.commit()
        runtime = GraphRuntime(
            session_factory=SessionLocal,
            emitter=PipelineEmitter(emit=_emit),
            user_id=user_id,
            session_id=session_id,
        )
        graph = build_graph()
        result = await graph.ainvoke(
            {
                "original_query": query,
                "session_id": session_id,
                "user_id": user_id,
                "attachment_contexts": [],
                "retry_count": 0,
            },
            config={"configurable": {"runtime": runtime}},
        )
        print("\nFINAL RESPONSE\n")
        print(result["final_response"])

    asyncio.run(_main())


if __name__ == "__main__":
    app()
