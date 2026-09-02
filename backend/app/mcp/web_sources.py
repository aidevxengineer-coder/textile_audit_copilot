from __future__ import annotations

import re
from typing import Any, Iterable
from urllib.parse import urlparse


# Public-web fallback is deliberately narrower than general browsing.  These
# hosts belong to standards bodies, inter-governmental organisations, or
# government agencies that are relevant to the product's textile/leather
# compliance use case.  Subdomains are accepted automatically.
AUTHORITATIVE_WEB_DOMAINS: tuple[str, ...] = (
    "amfori.org",
    "cbp.gov",
    "dhs.gov",
    "dol.gov",
    "ethicaltrade.org",
    "europa.eu",
    "ifc.org",
    "ilo.org",
    "oecd.org",
    "oeko-tex.com",
    "pakistancode.gov.pk",
    "punjab.gov.pk",
    "punjabcode.punjab.gov.pk",
    "sedex.com",
    "sindhlaws.gov.pk",
    "wrapcompliance.org",
    "worldbank.org",
    "zdhc.org",
)

_SPACE_RE = re.compile(r"\s+")


def normalize_hostname(value: str) -> str:
    hostname = (urlparse(value).hostname or "").lower().rstrip(".")
    return hostname[4:] if hostname.startswith("www.") else hostname


def is_authoritative_url(value: str) -> bool:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        return False
    hostname = normalize_hostname(value)
    return any(hostname == domain or hostname.endswith(f".{domain}") for domain in AUTHORITATIVE_WEB_DOMAINS)


def build_compliance_web_query(
    query: str,
    *,
    evaluator_feedback: str | None = None,
) -> str:
    """Create a useful fallback query without pretending the user used audit jargon."""

    cleaned_query = _SPACE_RE.sub(" ", query).strip()
    feedback = _SPACE_RE.sub(" ", evaluator_feedback or "").strip()
    parts = [cleaned_query]
    if feedback and feedback.lower() not in cleaned_query.lower():
        parts.append(f"Local evidence gap: {feedback[:240]}")
    parts.append(
        "official guidance for textile or leather factory compliance, supplier due diligence, and buyer audit preparation"
    )
    return ". ".join(part for part in parts if part)[:700]


def _iter_rows(result: Any) -> Iterable[dict[str, Any]]:
    if isinstance(result, dict):
        rows = result.get("results", result.get("items", []))
    else:
        rows = result
    if not isinstance(rows, list):
        rows = [rows]
    for row in rows:
        if isinstance(row, dict):
            yield row


def normalize_authoritative_results(result: Any, *, limit: int = 5) -> list[dict[str, Any]]:
    """Filter, deduplicate, and label public-search results for grounded use."""

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in _iter_rows(result):
        url = str(row.get("url") or row.get("source_url") or "").strip()
        if not is_authoritative_url(url):
            continue
        canonical = url.split("#", 1)[0]
        if canonical in seen:
            continue
        title = _SPACE_RE.sub(" ", str(row.get("title") or "Official compliance source")).strip()
        snippet = _SPACE_RE.sub(" ", str(row.get("snippet") or row.get("content") or "")).strip()
        # A URL with no usable search evidence cannot ground a response.
        if len(title) + len(snippet) < 24:
            continue
        seen.add(canonical)
        normalized.append(
            {
                "title": title[:300],
                "url": canonical,
                "source_url": canonical,
                "snippet": snippet[:1200],
                "source_domain": normalize_hostname(canonical),
                "authoritative": True,
                "content_verified": bool(row.get("content_verified", False)),
            }
        )
        if len(normalized) >= max(1, min(limit, 10)):
            break
    return normalized

