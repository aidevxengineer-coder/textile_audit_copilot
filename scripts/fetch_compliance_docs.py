from __future__ import annotations

import json
import mimetypes
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx
import typer


app = typer.Typer(add_completion=False)

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/pdf,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# The fetcher downloads only explicitly reviewed manifest entries from these
# organisations.  It is not a crawler and never follows links discovered in a
# downloaded page.
APPROVED_SOURCE_DOMAINS = {
    "amfori.org",
    "assets.ctfassets.net",
    "cbp.gov",
    "clr.org.pk",
    "dglabour.gos.pk",
    "dhs.gov",
    "ethicaltrade.org",
    "ifc.org",
    "ilo.org",
    "labour.punjab.gov.pk",
    "oecd.org",
    "oeko-tex.com",
    "punjabcode.punjab.gov.pk",
    "wrapcompliance.org",
    "zdhc.org",
}


def slugify(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")


def detect_extension(item_type: str, response: httpx.Response) -> str:
    if item_type == "pdf":
        return ".pdf"
    if item_type == "html":
        return ".html"
    if item_type == "docx":
        return ".docx"
    guessed = mimetypes.guess_extension(response.headers.get("content-type", "").split(";")[0].strip())
    return guessed or ".bin"


def source_domain(url: str) -> str:
    hostname = (urlparse(url).hostname or "").lower().removeprefix("www.")
    return hostname


def validate_manifest_url(url: str) -> None:
    parsed = urlparse(url)
    hostname = source_domain(url)
    if parsed.scheme != "https" or not any(
        hostname == domain or hostname.endswith(f".{domain}") for domain in APPROVED_SOURCE_DOMAINS
    ):
        raise ValueError(f"Source URL is outside the reviewed HTTPS domain allowlist: {url}")


def validate_payload(item_type: str, response: httpx.Response) -> None:
    payload = response.content
    if item_type == "pdf" and not payload.startswith(b"%PDF"):
        raise ValueError("The response was not a valid PDF payload.")
    if item_type == "docx" and not payload.startswith(b"PK"):
        raise ValueError("The response was not a valid DOCX payload.")
    if item_type == "html":
        sample = payload[:200_000].lower()
        if len(payload) < 200 or b"<html" not in sample and b"<!doctype html" not in sample:
            raise ValueError("The response was not a usable HTML page.")
        if b"just a moment" in sample and b"cloudflare" in sample:
            raise ValueError("The source returned an anti-bot challenge instead of the requested page.")


def resolved_entry(item: dict, target_path: Path, *, response: httpx.Response | None, skipped: bool) -> dict:
    payload = target_path.read_bytes()
    entry = {
        **item,
        "local_path": str(target_path),
        "skipped": skipped,
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    if response is not None:
        entry.update(
            {
                "resolved_url": str(response.url),
                "status_code": response.status_code,
                "content_type": response.headers.get("content-type", ""),
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    return entry


@app.command()
def fetch(force: bool = typer.Option(False, "--force", help="Re-download even if files already exist.")) -> None:
    manifest_path = Path("data/source_manifest.json")
    target_dir = Path("data/raw/downloads")
    target_dir.mkdir(parents=True, exist_ok=True)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    downloaded = []
    failed = []

    transport = httpx.HTTPTransport(retries=2)
    with httpx.Client(
        follow_redirects=True,
        timeout=60.0,
        headers=REQUEST_HEADERS,
        transport=transport,
    ) as client:
        for item in manifest:
            declared_extension = (
                ".pdf"
                if item["type"] == "pdf"
                else ".html"
                if item["type"] == "html"
                else ".docx"
                if item["type"] == "docx"
                else ".bin"
            )
            target_path = target_dir / f"{slugify(item['id'])}{declared_extension}"
            if target_path.exists() and not force:
                downloaded.append(resolved_entry(item, target_path, response=None, skipped=True))
                continue

            errors = []
            for candidate_url in [item["url"], *item.get("fallback_urls", [])]:
                try:
                    validate_manifest_url(candidate_url)
                    response = client.get(candidate_url)
                    response.raise_for_status()
                    validate_payload(item["type"], response)
                    extension = detect_extension(item["type"], response)
                    target_path = target_dir / f"{slugify(item['id'])}{extension}"
                    target_path.write_bytes(response.content)
                    downloaded.append(resolved_entry(item, target_path, response=response, skipped=False))
                    typer.echo(f"Saved {item['title']} -> {target_path}")
                    break
                except (httpx.HTTPError, ValueError) as exc:
                    errors.append(f"{candidate_url}: {exc}")
            else:
                detail = " | ".join(errors)
                failed.append({**item, "error": detail})
                typer.echo(f"Skipped {item['title']} -> {detail}", err=True)

    (target_dir / "resolved_manifest.json").write_text(json.dumps(downloaded, indent=2), encoding="utf-8")
    (target_dir / "failed_manifest.json").write_text(json.dumps(failed, indent=2), encoding="utf-8")
    typer.echo(f"Fetched {len(downloaded)} source documents/pages. Failed: {len(failed)}")


if __name__ == "__main__":
    app()
