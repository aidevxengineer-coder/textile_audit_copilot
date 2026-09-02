from app.graph.graph import route_after_orchestrator, route_after_relevance_evaluator
from app.graph.nodes.main_llm_call import normalize_markdown_tables
from app.graph.nodes.orchestrator import REPORT_REQUEST_PATTERN, is_document_operation


def test_relevant_project_evidence_routes_to_guarded_synthesis() -> None:
    state = {
        "relevance_verdict": {"relevant": True, "sufficient": False},
        "reranked_docs": [{"source_type": "project_upload"}],
        "retry_count": 1,
    }
    assert route_after_relevance_evaluator(state) == "main"


def test_insufficient_library_only_retrieval_still_retries() -> None:
    state = {
        "relevance_verdict": {"relevant": True, "sufficient": False},
        "reranked_docs": [{"source_type": "historical_audit_example"}],
        "retry_count": 0,
    }
    assert route_after_relevance_evaluator(state) == "retry"


def test_normal_document_question_does_not_request_report() -> None:
    assert REPORT_REQUEST_PATTERN.search("What does this document say about wages?") is None
    assert REPORT_REQUEST_PATTERN.search("What audit issues are mentioned on page 2?") is None


def test_explicit_report_request_selects_report_mode() -> None:
    assert REPORT_REQUEST_PATTERN.search("Generate a full pre-audit report from my files")
    assert REPORT_REQUEST_PATTERN.search("Please export the audit report")


def test_uploaded_document_operations_use_document_workspace() -> None:
    examples = [
        "Summarize the uploaded policy",
        "Explain this document in simple language",
        "Make a table of responsibilities",
        "Create a flowchart and identify its shortcomings",
        "Suggest improvements to this technical report",
    ]
    assert all(is_document_operation(query, has_documents=True) for query in examples)
    assert route_after_orchestrator({"orchestrator_decision": {"route": "document"}}) == "document"


def test_compliance_judgment_remains_grounded() -> None:
    assert not is_document_operation(
        "Review this document for legal compliance and violations", has_documents=True
    )
    assert not is_document_operation("Summarize this document", has_documents=False)
    assert not is_document_operation(
        "Create a full audit report from this document", has_documents=True, response_mode="report"
    )


def test_document_table_cleanup_replaces_empty_cells() -> None:
    value = "| Fact | Limitation |\n| --- | --- |\n| Exit E-3 was not inspected |  |"
    cleaned = normalize_markdown_tables(value)
    assert "| Exit E-3 was not inspected | — |" in cleaned
