from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.utils.io import PROJECT_ROOT


CONFIG = PROJECT_ROOT / "config" / "gap_fill_a_cleanup.json"
REVIEW = PROJECT_ROOT / "data" / "reviewed"
CANDIDATES = PROJECT_ROOT / "data" / "candidates"
AUDIT = PROJECT_ROOT / "data" / "audits" / "gap_fill_a_cleanup.json"
EXTRA = ["Quality Exclusion Reason", "Audit Classification", "Quality Excluded At", "Original Queue"]


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


def filter_derived(path: Path, configured_ids: set[str]) -> int:
    if not path.exists():
        return 0
    fields, rows = read_csv(path)
    kept = [row for row in rows if row.get("Candidate ID", "") not in configured_ids]
    write_csv(path, fields, kept)
    return len(rows) - len(kept)


def main() -> None:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    excluded_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    report: dict[str, Any] = {
        "generated_at": excluded_at,
        "policy": config["policy"],
        "categories": {},
        "errors": [],
    }
    for category, configured in config["categories"].items():
        queue_path = REVIEW / f"{category}.review_queue.csv"
        fields, rows = read_csv(queue_path)
        configured_ids = set(configured)
        found = {row.get("Candidate ID", "") for row in rows}
        excluded_path = CANDIDATES / f"{category}.gap_fill_quality_excluded.csv"
        old_fields, old_rows = read_csv(excluded_path) if excluded_path.exists() else ([], [])
        old = {row.get("Candidate ID", ""): row for row in old_rows if row.get("Candidate ID")}
        missing = sorted(configured_ids - found - set(old))
        if missing:
            report["errors"].append({"category": category, "missing_candidate_ids": missing})

        kept: list[dict[str, str]] = []
        removed: list[dict[str, Any]] = []
        for row in rows:
            candidate_id = row.get("Candidate ID", "")
            if candidate_id not in configured_ids:
                kept.append(row)
                continue
            if (row.get("Review Status") or "PENDING").strip() != "PENDING":
                report["errors"].append({
                    "category": category,
                    "candidate_id": candidate_id,
                    "error": "Refused to exclude a human-reviewed row",
                })
                kept.append(row)
                continue
            excluded = dict(row)
            excluded.update({
                "Quality Exclusion Reason": configured[candidate_id],
                "Audit Classification": "FALSE_POSITIVE",
                "Quality Excluded At": excluded_at,
                "Original Queue": str(queue_path.relative_to(PROJECT_ROOT)),
            })
            removed.append(excluded)

        if report["errors"]:
            continue
        for row in removed:
            old[row["Candidate ID"]] = row
        excluded_fields = list(dict.fromkeys(fields + old_fields + EXTRA))
        write_csv(queue_path, fields, kept)
        write_csv(excluded_path, excluded_fields, list(old.values()))
        removed_primary = filter_derived(CANDIDATES / f"{category}.csv", configured_ids)
        removed_secondary = filter_derived(CANDIDATES / f"{category}.secondary_review.csv", configured_ids)
        report["categories"][category] = {
            "queue_seen_this_run": len(rows),
            "candidates_before_precision_filtering": len(kept) + len(old),
            "removed_pending": len(removed),
            "queue_after": len(kept),
            "quality_excluded_total": len(old),
            "removed_from_primary": removed_primary,
            "removed_from_secondary": removed_secondary,
            "excluded_file": str(excluded_path.relative_to(PROJECT_ROOT)),
            "candidate_ids": [row["Candidate ID"] for row in removed],
        }

    if report["errors"]:
        raise RuntimeError(json.dumps(report["errors"], ensure_ascii=False, indent=2))
    AUDIT.parent.mkdir(parents=True, exist_ok=True)
    AUDIT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
