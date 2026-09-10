"""Capture the immutable before-state for targeted gap-fill batch A."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.audit.consolidation_baseline import CATEGORIES, HUMAN, canonical_hash
from src.audit.remaining_baseline import workbook_semantics
from src.utils.io import PROJECT_ROOT, read_json, read_jsonl


SCOPE = ("GEN-1", "REG-1", "REG-3", "REG-4")
OUT_OF_SCOPE = tuple(category for category in CATEGORIES if category not in SCOPE)


def csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def category_artifacts(category: str) -> dict[str, str]:
    roots = (
        PROJECT_ROOT / "data" / "raw",
        PROJECT_ROOT / "data" / "candidates",
        PROJECT_ROOT / "data" / "reviewed",
        PROJECT_ROOT / "data" / "rejected",
    )
    result: dict[str, str] = {}
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob(f"{category}*")):
            if path.is_file():
                result[str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")] = file_sha256(path)
    return result


def queue_snapshot(category: str) -> dict[str, Any]:
    path = PROJECT_ROOT / "data" / "reviewed" / f"{category}.review_queue.csv"
    rows = csv_rows(path)
    return {
        "candidate_ids": [row.get("Candidate ID") or "" for row in rows],
        "candidate_semantics": {
            row.get("Candidate ID") or "": {
                key: row.get(key) or ""
                for key in (
                    "Example", "Context", "Source Platform", "Source Name", "Source URL",
                    "Content URL", "Source Item ID", "Retrieval Tier", "Review Status",
                    "Reviewer Notes",
                )
            }
            for row in rows if row.get("Candidate ID")
        },
    }


def main() -> None:
    raw_records: dict[str, dict[str, Any]] = {}
    raw_physical = 0
    raw_counts: dict[str, int] = {}
    for path in sorted((PROJECT_ROOT / "data" / "raw").rglob("*.jsonl")):
        if path.name.endswith(".provenance.jsonl"):
            continue
        rows = read_jsonl(path)
        relative = str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
        raw_counts[relative] = len(rows)
        raw_physical += len(rows)
        for row in rows:
            raw_id = str(row.get("raw_record_id") or "")
            if raw_id:
                raw_records.setdefault(raw_id, row)

    queues = {category: queue_snapshot(category) for category in CATEGORIES}
    human_decisions: dict[str, Any] = {}
    for category, queue in queues.items():
        for candidate_id, row in queue["candidate_semantics"].items():
            if row["Review Status"] in HUMAN:
                human_decisions[f"{category}:{candidate_id}"] = row

    source_registry = read_json(PROJECT_ROOT / "config" / "sources.json")
    existing_sources = {
        str(source.get("url") or ""): {
            "platform": source.get("platform"),
            "source_name": source.get("source_name"),
            "url": source.get("url"),
            "platform_source_id": source.get("platform_source_id"),
            "reachability": source.get("reachability"),
            "identity_verification": source.get("identity_verification"),
        }
        for source in source_registry.get("sources", []) if source.get("url")
    }
    final_ids_path = PROJECT_ROOT / "data" / "reviewed" / "final_ids.json"
    output = {
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scope": list(SCOPE),
        "out_of_scope": list(OUT_OF_SCOPE),
        "raw_physical_lines": raw_physical,
        "raw_unique_records": len(raw_records),
        "raw_counts_by_path": raw_counts,
        "preexisting_raw_ids": sorted(raw_records),
        "preexisting_raw_record_hashes": {
            raw_id: canonical_hash(record) for raw_id, record in sorted(raw_records.items())
        },
        "queues": queues,
        "human_decisions": human_decisions,
        "out_of_scope_artifact_hashes": {
            category: category_artifacts(category) for category in OUT_OF_SCOPE
        },
        "preexisting_source_identity": existing_sources,
        "final_ids": read_json(final_ids_path) if final_ids_path.exists() else {},
        "accepted_export_semantics": workbook_semantics(
            PROJECT_ROOT / "data" / "exports" / "data_collection.xlsx"
        ),
        "taxonomy_sha256": file_sha256(PROJECT_ROOT / "config" / "taxonomy.json"),
    }
    path = PROJECT_ROOT / "data" / "audits" / "gap_fill_a_baseline.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(path)
    print(json.dumps({
        "raw_physical_lines": raw_physical,
        "raw_unique_records": len(raw_records),
        "scope_review_rows": sum(len(queues[category]["candidate_ids"]) for category in SCOPE),
        "human_decisions": len(human_decisions),
        "out_of_scope_files_locked": sum(len(paths) for paths in output["out_of_scope_artifact_hashes"].values()),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
