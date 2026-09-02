"""Download public FLA factory assessments and corrective-action plans.

This is deliberately separate from the International Accord downloader: the
Accord operates in Bangladesh and Pakistan, while FLA publishes independent
factory assessments connected to global apparel and footwear brands.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup


MEMBER_PAGES = {
    "adidas": "https://www.fairlabor.org/member/adidas/",
    "nike": "https://www.fairlabor.org/member/nike/",
    "puma": "https://www.fairlabor.org/member/puma-se/",
    "patagonia": "https://www.fairlabor.org/member/patagonia/",
    "under_armour": "https://www.fairlabor.org/member/under-armour/",
    "uniqlo_fast_retailing": "https://www.fairlabor.org/member/fast-retailing/",
    "gildan": "https://www.fairlabor.org/member/gildan-activewear-inc/",
}
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/138 Safari/537.36"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def get(session: requests.Session, url: str, attempts: int = 8) -> requests.Response:
    error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = session.get(url, timeout=60)
            if response.status_code == 200:
                return response
            error = RuntimeError(f"HTTP {response.status_code}")
        except requests.RequestException as exc:
            error = exc
        if attempt < attempts:
            time.sleep(min(attempt * 2, 12))
    raise RuntimeError(f"Could not retrieve {url}: {error}")


def discover(session: requests.Session, per_brand: int) -> list[dict[str, Any]]:
    assessments: dict[str, dict[str, Any]] = {}
    for source_brand, page_url in MEMBER_PAGES.items():
        soup = BeautifulSoup(get(session, page_url).text, "html.parser")
        selected = 0
        for card in soup.select("li.report-card"):
            summary = " ".join(card.get_text(" ", strip=True).split())
            if not summary.startswith("Factory Assessment"):
                continue
            links: dict[str, str] = {}
            assessment_id = ""
            for link in card.select("a.report-items__link[href]"):
                label = " ".join(link.get_text(" ", strip=True).split())
                match = re.match(r"(Report|CAP):\s*(\d+)", label, flags=re.IGNORECASE)
                if match:
                    links[match.group(1).lower()] = link["href"]
                    assessment_id = assessment_id or match.group(2)
            if not assessment_id or "report" not in links:
                continue
            item = assessments.setdefault(
                assessment_id,
                {
                    "assessment_id": assessment_id,
                    "summary": summary,
                    "source_brands": [],
                    "source_pages": [],
                    "links": links,
                },
            )
            if source_brand not in item["source_brands"]:
                item["source_brands"].append(source_brand)
            if page_url not in item["source_pages"]:
                item["source_pages"].append(page_url)
            item["links"].update(links)
            selected += 1
            if selected >= per_brand:
                break
    return list(assessments.values())


def download_document(
    session: requests.Session, url: str, base_path: Path, *, force: bool
) -> tuple[Path, str, str]:
    for extension in (".pdf", ".xlsx"):
        existing = base_path.with_suffix(extension)
        if existing.exists() and existing.stat().st_size > 100 and not force:
            return existing, sha256_file(existing), "existing"
    response = get(session, url)
    if response.content.startswith(b"%PDF"):
        destination = base_path.with_suffix(".pdf")
    elif response.content.startswith(b"PK\x03\x04"):
        destination = base_path.with_suffix(".xlsx")
    else:
        raise RuntimeError("Official endpoint returned an unsupported document response")
    partial = destination.with_suffix(destination.suffix + ".part")
    partial.write_bytes(response.content)
    partial.replace(destination)
    return destination, sha256_file(destination), "downloaded"


def write_manifests(output: Path, rows: list[dict[str, Any]]) -> None:
    (output / "manifest.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    fields = [
        "assessment_id",
        "source_brands",
        "summary",
        "document_type",
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
        for row in rows:
            serialized = dict(row)
            serialized["source_brands"] = ", ".join(row.get("source_brands", []))
            writer.writerow({field: serialized.get(field, "") for field in fields})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-brand", type=int, default=3)
    parser.add_argument(
        "--output", type=Path, default=Path("data/audit_test_data/global_fla_brands")
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--delay", type=float, default=0.25)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    assessments = discover(session, max(args.per_brand, 0))
    print(f"Discovered {len(assessments)} unique FLA assessments.")
    rows: list[dict[str, Any]] = []
    for index, assessment in enumerate(assessments, start=1):
        folder = args.output / f"assessment_{assessment['assessment_id']}"
        folder.mkdir(parents=True, exist_ok=True)
        print(f"[{index}/{len(assessments)}] {assessment['summary'][:100]}")
        for document_type in ("report", "cap"):
            url = assessment["links"].get(document_type)
            if not url:
                continue
            destination_base = folder / document_type
            row = {
                "assessment_id": assessment["assessment_id"],
                "source_brands": assessment["source_brands"],
                "source_pages": assessment["source_pages"],
                "summary": assessment["summary"],
                "document_type": document_type,
                "source_url": url,
                "error": "",
            }
            try:
                destination, checksum, status = download_document(
                    session, url, destination_base, force=args.force
                )
                row.update(
                    {
                        "local_path": destination.as_posix(),
                        "bytes": destination.stat().st_size,
                        "sha256": checksum,
                        "status": status,
                    }
                )
                print(f"  {document_type}: {status} ({destination.stat().st_size:,} bytes)")
            except Exception as exc:
                row.update(
                    {"local_path": "", "bytes": 0, "sha256": "", "status": "failed", "error": str(exc)}
                )
                print(f"  {document_type}: FAILED - {exc}")
            rows.append(row)
            write_manifests(args.output, rows)
            time.sleep(max(args.delay, 0))
    print(f"Finished: {sum(row['status'] != 'failed' for row in rows)}/{len(rows)} files available.")


if __name__ == "__main__":
    main()
