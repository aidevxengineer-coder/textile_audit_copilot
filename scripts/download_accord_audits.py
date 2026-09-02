"""Download public International Accord factory reports for RAG evaluation.

The downloader uses the Accord's public WordPress API to discover the report
links shown on its factory page. Downloads are resumable: existing valid files
are skipped, and a JSON/CSV manifest records provenance and checksums.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import time
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup


PAGE_CONFIG = {
    "bangladesh": {
        "api": "https://internationalaccord.org/wp-json/wp/v2/pages/92?context=view",
        "source": "https://internationalaccord.org/bangladesh-factories/",
    },
    "pakistan": {
        "api": "https://internationalaccord.org/wp-json/wp/v2/pages/22796?context=view",
        "source": "https://internationalaccord.org/pakistan-factories/",
    },
}
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138 Safari/537.36"
)


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "_", value).strip(" ._")
    return re.sub(r"\s+", "_", cleaned)[:120] or "unknown_factory"


def get_with_retries(
    session: requests.Session,
    url: str,
    *,
    stream: bool = False,
    attempts: int = 12,
) -> requests.Response:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = session.get(url, timeout=60, stream=stream)
            if response.status_code == 200:
                return response
            last_error = RuntimeError(f"HTTP {response.status_code} for {url}")
        except requests.RequestException as exc:
            last_error = exc
        if attempt < attempts:
            time.sleep(min(3 * attempt, 20))
    raise RuntimeError(f"Could not retrieve {url}: {last_error}")


def discover_factories(session: requests.Session, country: str) -> list[dict[str, Any]]:
    config = PAGE_CONFIG[country]
    response = get_with_retries(session, config["api"])
    payload = response.json()
    rendered = html.unescape(payload["content"]["rendered"])
    soup = BeautifulSoup(rendered, "html.parser")
    factories: list[dict[str, Any]] = []

    for card in soup.select(".fwpl-result"):
        title = card.select_one(".factory-title")
        if title is None:
            continue
        factory: dict[str, Any] = {
            "factory": title.get_text(" ", strip=True),
            "source_page": config["source"],
            "reports": [],
        }

        factory_link = card.find("a", href=re.compile(r"/factory/"))
        if factory_link:
            factory["factory_page"] = factory_link.get("href")

        for node in card.select(".factory-resource-link"):
            url = node.get_text(" ", strip=True)
            if not url.startswith("https://"):
                continue
            classes = set(node.get("class", []))
            report_type = next(
                (kind for kind in ("fire", "electrical", "structural", "boiler") if kind in classes),
                "inspection",
            )
            factory["reports"].append({"type": report_type, "url": url})

        cap = card.select_one(".cap-item")
        if cap:
            cap_url = cap.get_text(" ", strip=True)
            if cap_url.startswith("https://"):
                factory["reports"].append({"type": "cap", "url": cap_url})

        factories.append(factory)

    if not factories:
        raise RuntimeError("The Accord page returned no factory cards; its layout may have changed.")
    return factories


def detect_extension(first_bytes: bytes, content_type: str) -> str:
    if first_bytes.startswith(b"%PDF") or "application/pdf" in content_type:
        return ".pdf"
    if first_bytes.startswith(b"PK\x03\x04") or "spreadsheet" in content_type:
        return ".xlsx"
    return ".bin"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download_report(
    session: requests.Session,
    url: str,
    base_path: Path,
    *,
    force: bool,
) -> tuple[Path, str, str]:
    for extension in (".pdf", ".xlsx", ".bin"):
        existing = base_path.with_suffix(extension)
        if existing.exists() and existing.stat().st_size > 100 and not force:
            return existing, sha256_file(existing), "existing"

    response = get_with_retries(session, url, stream=True)
    iterator = response.iter_content(chunk_size=1024 * 1024)
    first = next(iterator, b"")
    extension = detect_extension(first, response.headers.get("content-type", "").lower())
    if extension == ".bin" and first.lstrip().lower().startswith((b"<!doctype html", b"<html")):
        raise RuntimeError("download endpoint returned an HTML page instead of a report")

    destination = base_path.with_suffix(extension)
    partial = destination.with_suffix(destination.suffix + ".part")
    with partial.open("wb") as handle:
        handle.write(first)
        for block in iterator:
            if block:
                handle.write(block)
    partial.replace(destination)
    return destination, sha256_file(destination), "downloaded"


def existing_report(base_path: Path, *, force: bool) -> tuple[Path, str, str] | None:
    for extension in (".pdf", ".xlsx", ".bin"):
        existing = base_path.with_suffix(extension)
        if existing.exists() and existing.stat().st_size > 100 and not force:
            return existing, sha256_file(existing), "existing"
    return None


def find_chromium() -> Path:
    candidates = [
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise RuntimeError("Chrome or Microsoft Edge is required to download Pakistan Salesforce reports.")


def download_pakistan_report(
    page: Any,
    url: str,
    base_path: Path,
    report_type: str,
    *,
    force: bool,
) -> tuple[Path, str, str]:
    existing = existing_report(base_path, force=force)
    if existing:
        return existing

    page.goto(url, wait_until="domcontentloaded", timeout=90_000)
    if report_type == "cap":
        button = page.locator('input[value="Export All"]')
    else:
        button = page.get_by_role("button", name="Download", exact=True)
    button.wait_for(timeout=90_000)
    with page.expect_download(timeout=90_000) as download_info:
        button.click()
    download = download_info.value
    failure = download.failure()
    if failure:
        raise RuntimeError(f"Browser download failed: {failure}")

    suggested = download.suggested_filename.lower()
    extension = ".xlsx" if suggested.endswith(".xlsx") else ".pdf" if suggested.endswith(".pdf") else ".bin"
    destination = base_path.with_suffix(extension)
    download.save_as(destination)
    first = destination.read_bytes()[:16]
    if extension == ".pdf" and not first.startswith(b"%PDF"):
        raise RuntimeError("Salesforce returned a non-PDF response for an inspection report")
    if extension == ".xlsx" and not first.startswith(b"PK\x03\x04"):
        raise RuntimeError("Salesforce returned an invalid CAP workbook")
    return destination, sha256_file(destination), "downloaded"


def write_manifests(output: Path, rows: list[dict[str, Any]]) -> None:
    (output / "manifest.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    fields = [
        "factory",
        "factory_page",
        "report_type",
        "source_url",
        "local_path",
        "bytes",
        "sha256",
        "status",
        "error",
    ]
    with (output / "manifest.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows({key: row.get(key, "") for key in fields} for row in rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--country", choices=sorted(PAGE_CONFIG), default="bangladesh")
    parser.add_argument("--limit", type=int, default=20, help="Maximum factory cards to download")
    parser.add_argument(
        "--output", type=Path, default=None
    )
    parser.add_argument("--delay", type=float, default=0.4, help="Seconds between files")
    parser.add_argument("--force", action="store_true", help="Replace existing files")
    args = parser.parse_args()

    if args.output is None:
        args.output = Path(f"data/audit_test_data/{args.country}_accord")
    args.output.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "*/*"})
    factories = discover_factories(session, args.country)[: max(args.limit, 0)]
    rows: list[dict[str, Any]] = []

    print(f"Discovered {len(factories)} {args.country.title()} factory records.")

    browser_context = None
    playwright_manager = None
    if args.country == "pakistan":
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("Install development requirements to download Pakistan reports.") from exc
        playwright_manager = sync_playwright().start()
        browser = playwright_manager.chromium.launch(headless=True, executable_path=str(find_chromium()))
        browser_context = browser.new_context(accept_downloads=True)

    try:
        for index, factory in enumerate(factories, start=1):
            folder = args.output / safe_name(factory["factory"])
            folder.mkdir(parents=True, exist_ok=True)
            print(f"[{index}/{len(factories)}] {factory['factory']}")
            type_counts: dict[str, int] = {}
            for report in factory["reports"]:
                kind = report["type"]
                type_counts[kind] = type_counts.get(kind, 0) + 1
                suffix = "" if type_counts[kind] == 1 else f"_{type_counts[kind]}"
                base_path = folder / f"{kind}{suffix}"
                row = {
                    "factory": factory["factory"],
                    "factory_page": factory.get("factory_page", ""),
                    "report_type": kind,
                    "source_url": report["url"],
                    "error": "",
                }
                try:
                    if browser_context is not None:
                        page = browser_context.new_page()
                        try:
                            path, checksum, status = download_pakistan_report(
                                page, report["url"], base_path, kind, force=args.force
                            )
                        finally:
                            page.close()
                    else:
                        path, checksum, status = download_report(
                            session, report["url"], base_path, force=args.force
                        )
                    row.update(
                        {
                            "local_path": path.as_posix(),
                            "bytes": path.stat().st_size,
                            "sha256": checksum,
                            "status": status,
                        }
                    )
                    print(f"  {kind}: {status} ({path.stat().st_size:,} bytes)")
                except Exception as exc:  # Keep the batch resumable when one public link fails.
                    row.update({"local_path": "", "bytes": 0, "sha256": "", "status": "failed"})
                    row["error"] = str(exc)
                    print(f"  {kind}: FAILED - {exc}")
                rows.append(row)
                write_manifests(args.output, rows)
                time.sleep(max(args.delay, 0))
    finally:
        if browser_context is not None:
            browser_context.browser.close()
        if playwright_manager is not None:
            playwright_manager.stop()

    successful = sum(row["status"] != "failed" for row in rows)
    print(f"Finished: {successful}/{len(rows)} files available in {args.output}")


if __name__ == "__main__":
    main()
