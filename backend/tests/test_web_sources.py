import asyncio
from time import perf_counter

import pytest

from app.mcp.service import MCPIntegrationError, MCPService
from app.mcp.web_sources import (
    build_compliance_web_query,
    is_authoritative_url,
    normalize_authoritative_results,
)


def test_authoritative_domain_policy_rejects_search_blogs_and_fake_suffixes() -> None:
    assert is_authoritative_url("https://www.ilo.org/resource/example") is True
    assert is_authoritative_url("https://help.cbp.gov/s/article/Article1842") is True
    assert is_authoritative_url("https://ilo.org.example.test/fake") is False
    assert is_authoritative_url("https://random-compliance-blog.example/post") is False


def test_web_results_are_deduplicated_and_keep_exact_official_urls() -> None:
    rows = normalize_authoritative_results(
        {
            "results": [
                {
                    "title": "ILO textile safety code",
                    "url": "https://www.ilo.org/resource/other/textile-safety#download",
                    "snippet": "Official sector-specific safety guidance for textile and leather factories.",
                },
                {
                    "title": "Duplicate",
                    "url": "https://www.ilo.org/resource/other/textile-safety#other",
                    "snippet": "Duplicate result.",
                },
                {
                    "title": "Unverified blog",
                    "url": "https://example.com/audit-tips",
                    "snippet": "This must not be used as grounded compliance evidence.",
                },
            ]
        }
    )
    assert len(rows) == 1
    assert rows[0]["source_url"] == "https://www.ilo.org/resource/other/textile-safety"
    assert rows[0]["source_domain"] == "ilo.org"
    assert rows[0]["authoritative"] is True


def test_fallback_query_includes_evaluator_gap_and_sector_context() -> None:
    query = build_compliance_web_query(
        "What should I upload?",
        evaluator_feedback="Local clauses do not cover chemical records.",
    )
    assert "What should I upload?" in query
    assert "chemical records" in query
    assert "textile or leather" in query


def test_authoritative_search_has_one_fail_fast_end_to_end_deadline(monkeypatch) -> None:
    service = MCPService()
    service.settings.web_search_timeout_seconds = 0.05

    async def stalled_mcp_call(server: str, preferred_names: list[str], arguments: dict) -> dict:
        await asyncio.sleep(0.5)
        return {
            "results": [
                {
                    "title": "Should not escape the deadline",
                    "url": "https://www.ilo.org/should-not-be-returned",
                    "snippet": "This result arrived after the interactive deadline.",
                }
            ]
        }

    monkeypatch.setattr(service, "_call_tool", stalled_mcp_call)
    started = perf_counter()
    with pytest.raises(MCPIntegrationError, match="interactive deadline"):
        asyncio.run(service.search_authoritative_sources("textile fire safety"))
    elapsed = perf_counter() - started

    assert elapsed < 0.2
