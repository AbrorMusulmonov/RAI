from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.utils.io import PROJECT_ROOT


CONFIG_PATH = PROJECT_ROOT / "config" / "consolidation_cleanup.json"
REVIEW_DIR = PROJECT_ROOT / "data" / "reviewed"
EXCLUDED_DIR = PROJECT_ROOT / "data" / "candidates"
AUDIT_PATH = PROJECT_ROOT / "data" / "audits" / "consolidation_cleanup.json"
EXTRA_FIELDS = ["Quality Exclusion Reason", "Quality Excluded At", "Original Queue"]


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def main() -> None:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    excluded_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    audit: dict[str, Any] = {
        "generated_at": excluded_at,
        "policy": config["policy"],
        "categories": {},
        "errors": [],
    }

    for category, configured in config["categories"].items():
        queue_path = REVIEW_DIR / f"{category}.review_queue.csv"
        fields, rows = read_csv(queue_path)
        excluded_path = EXCLUDED_DIR / f"{category}.quality_excluded.csv"
        existing_fields: list[str] = []
        existing: list[dict[str, str]] = []
        if excluded_path.exists():
            existing_fields, existing = read_csv(excluded_path)
        existing_excluded_ids = {
            row.get("Candidate ID", "") for row in existing if row.get("Candidate ID")
        }
        configured_ids = set(configured)
        found_ids = {row.get("Candidate ID", "") for row in rows}
        missing = sorted(configured_ids - found_ids - existing_excluded_ids)
        if missing:
            audit["errors"].append({"category": category, "missing_candidate_ids": missing})

        kept: list[dict[str, str]] = []
        removed: list[dict[str, Any]] = []
        for row in rows:
            candidate_id = row.get("Candidate ID", "")
            if candidate_id not in configured_ids:
                kept.append(row)
                continue
            if (row.get("Review Status") or "PENDING").strip() != "PENDING":
                audit["errors"].append({
                    "category": category,
                    "candidate_id": candidate_id,
                    "error": "Refused to exclude a human-reviewed row",
                })
                kept.append(row)
                continue
            excluded = dict(row)
            excluded.update({
                "Quality Exclusion Reason": configured[candidate_id],
                "Quality Excluded At": excluded_at,
                "Original Queue": str(queue_path.relative_to(PROJECT_ROOT)),
            })
            removed.append(excluded)

        merged = {row.get("Candidate ID", ""): row for row in existing if row.get("Candidate ID")}
        for row in removed:
            merged[row["Candidate ID"]] = row
        excluded_fields = list(dict.fromkeys(fields + existing_fields + EXTRA_FIELDS))

        write_csv(queue_path, fields, kept)
        write_csv(excluded_path, excluded_fields, list(merged.values()))
        audit["categories"][category] = {
            "queue_before": len(rows),
            "removed_pending": len(removed),
            "queue_after": len(kept),
            "quality_excluded_total": len(merged),
            "excluded_file": str(excluded_path.relative_to(PROJECT_ROOT)),
            "candidate_ids": [row["Candidate ID"] for row in removed],
        }

    if audit["errors"]:
        raise RuntimeError(json.dumps(audit["errors"], ensure_ascii=False, indent=2))
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    AUDIT_PATH.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
