from __future__ import annotations

import json
from pathlib import Path

from openpyxl import Workbook

import ingest


def test_extract_text_reads_xlsx_sheet_and_rows(tmp_path: Path) -> None:
    path = tmp_path / "cap.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Corrective Action Plan"
    sheet.append(["Finding", "Target date", "Status"])
    sheet.append(["Blocked fire exit", "2026-08-15", "In progress"])
    workbook.save(path)

    text = ingest.extract_text(path)

    assert "## Sheet: Corrective Action Plan" in text
    assert "Blocked fire exit | 2026-08-15 | In progress" in text


def test_audit_split_keeps_each_factory_wholly_in_one_split(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "accord"
    rows = []
    for factory in ("factory_a", "factory_b", "factory_c", "factory_d", "factory_e"):
        unit = root / factory
        unit.mkdir(parents=True)
        for name in ("fire.pdf", "cap.xlsx"):
            path = unit / name
            path.touch()
            rows.append({"factory": factory, "local_path": str(path), "status": "downloaded"})
    (root / "manifest.json").write_text(json.dumps(rows), encoding="utf-8")

    split_path = tmp_path / "split.json"
    monkeypatch.setattr(ingest, "AUDIT_DATASETS", {"sample": root})
    monkeypatch.setattr(ingest, "AUDIT_SPLIT_PATH", split_path)

    sources, split = ingest.resolve_audit_sources(0.8)
    dataset_split = split["datasets"]["sample"]
    train_units = set(dataset_split["train_units"])
    test_units = set(dataset_split["test_units"])

    assert train_units.isdisjoint(test_units)
    assert train_units | test_units == {"factory_a", "factory_b", "factory_c", "factory_d", "factory_e"}
    assert {source["audit_unit"] for source in sources} == train_units
    assert all(source["source_type"] == "historical_audit_example" for source in sources)
    assert split_path.exists()
