"""Capture the immutable evidence/decision baseline for final consolidation."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.audit.remaining_baseline import workbook_semantics
from src.utils.io import PROJECT_ROOT, read_json, read_jsonl


CATEGORIES = (
    "GEN-1", "GEN-2", "GEN-3", "GEN-4", "GEN-5",
    "REG-1", "REG-2", "REG-3", "REG-4",
    "STA-1", "STA-2", "STA-3", "STA-4", "STA-5",
    "REL-1", "REL-2",
)
HUMAN = {"ACCEPT", "REJECT", "UNSURE", "MOVE_TO_OTHER_CATEGORY"}


def csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def canonical_hash(record: dict[str, Any]) -> str:
    preserved = {
        key: record.get(key)
        for key in (
            "raw_record_id", "original_text", "source_platform", "source_name",
            "source_url", "content_url", "source_item_id", "example_is_real_world",
        )
    }
    payload = json.dumps(preserved, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest().upper()


def main() -> None:
    raw_records: dict[str, dict[str, Any]] = {}
    physical_lines = 0
    raw_counts: dict[str, int] = {}
    for path in sorted((PROJECT_ROOT / "data" / "raw").rglob("*.jsonl")):
        if path.name.endswith(".provenance.jsonl"):
            continue
        rows = read_jsonl(path)
        physical_lines += len(rows)
        raw_counts[path.stem] = len(rows)
        for row in rows:
            raw_id = str(row.get("raw_record_id") or "")
            if raw_id:
                raw_records.setdefault(raw_id, row)

    queues: dict[str, Any] = {}
    human_decisions: dict[str, Any] = {}
    for category in CATEGORIES:
        path = PROJECT_ROOT / "data" / "reviewed" / f"{category}.review_queue.csv"
        rows = csv_rows(path)
        queues[category] = {
            "exists": path.exists(),
            "candidate_ids": [row.get("Candidate ID") or "" for row in rows],
            "candidate_semantics": {
                row.get("Candidate ID") or "": {
                    "Example": row.get("Example") or "",
                    "Source URL": row.get("Source URL") or "",
                    "Source Item ID": row.get("Source Item ID") or "",
                    "Review Status": row.get("Review Status") or "",
                    "Reviewer Notes": row.get("Reviewer Notes") or "",
                }
                for row in rows if row.get("Candidate ID")
            },
        }
        for row in rows:
            status = row.get("Review Status") or ""
            if status in HUMAN:
                candidate_id = row.get("Candidate ID") or ""
                human_decisions[f"{category}:{candidate_id}"] = {
                    "status": status,
                    "reviewer_notes": row.get("Reviewer Notes") or "",
                    "example": row.get("Example") or "",
                    "source_url": row.get("Source URL") or "",
                    "source_item_id": row.get("Source Item ID") or "",
                }

    final_ids_path = PROJECT_ROOT / "data" / "reviewed" / "final_ids.json"
    output = {
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scope": list(CATEGORIES),
        "raw_physical_lines": physical_lines,
        "raw_unique_records": len(raw_records),
        "raw_counts_by_file_stem": raw_counts,
        "preexisting_raw_ids": sorted(raw_records),
        "preexisting_raw_record_hashes": {
            raw_id: canonical_hash(record) for raw_id, record in sorted(raw_records.items())
        },
        "queues": queues,
        "human_decisions": human_decisions,
        "final_ids": read_json(final_ids_path) if final_ids_path.exists() else {},
        "accepted_export_semantics": workbook_semantics(
            PROJECT_ROOT / "data" / "exports" / "data_collection.xlsx"
        ),
    }
    path = PROJECT_ROOT / "data" / "audits" / "consolidation_baseline.json"
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(path)
    print(json.dumps({
        "raw_physical_lines": physical_lines,
        "raw_unique_records": len(raw_records),
        "queue_rows": sum(len(value["candidate_ids"]) for value in queues.values()),
        "human_decisions": len(human_decisions),
        "final_id_mappings": len(output["final_ids"]),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
