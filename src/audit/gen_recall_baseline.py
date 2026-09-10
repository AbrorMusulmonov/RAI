from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from src.utils.io import PROJECT_ROOT, read_jsonl


CATEGORIES = ["GEN-2", "GEN-3", "GEN-4", "GEN-5"]
PROTECTED_GEN1 = [
    "data/reviewed/GEN-1.review_queue.csv",
    "data/reviewed/GEN-1.csv",
    "data/rejected/GEN-1.csv",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    raw_ids: set[str] = set()
    raw_by_category: dict[str, dict[str, object]] = {}
    for path in (PROJECT_ROOT / "data" / "raw").rglob("*.jsonl"):
        if path.name.endswith(".provenance.jsonl"):
            continue
        rows = read_jsonl(path)
        ids = {str(row.get("raw_record_id") or "") for row in rows if row.get("raw_record_id")}
        raw_ids.update(ids)
        raw_by_category[path.stem] = {
            "path": str(path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "rows": len(rows),
            "unique_ids": len(ids),
            "sha256": sha256(path),
        }

    queues: dict[str, object] = {}
    for category in CATEGORIES:
        path = PROJECT_ROOT / "data" / "reviewed" / f"{category}.review_queue.csv"
        rows = csv_rows(path)
        queues[category] = {
            "path": str(path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "sha256": sha256(path),
            "rows": len(rows),
            "status_counts": dict(Counter(row.get("Review Status") or "" for row in rows)),
            "human_decisions": {
                row.get("Candidate ID") or "": {
                    "status": row.get("Review Status") or "",
                    "notes": row.get("Reviewer Notes") or "",
                }
                for row in rows
                if row.get("Review Status") not in {None, "", "PENDING"}
            },
        }

    payload = {
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scope": CATEGORIES,
        "raw_by_category": raw_by_category,
        "all_preexisting_raw_ids": sorted(raw_ids),
        "queues": queues,
        "protected_gen1_hashes": {
            relative: sha256(PROJECT_ROOT / relative) for relative in PROTECTED_GEN1
        },
    }
    output = PROJECT_ROOT / "data" / "audits" / "GEN_recall_baseline.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"BASELINE\t{output}")
    print(f"PREEXISTING_RAW_IDS\t{len(raw_ids)}")


if __name__ == "__main__":
    main()
