from __future__ import annotations

import json
from datetime import datetime, timezone

from src.review.__main__ import ALLOWED, load_rows, pending_order, review_queue_path, taxonomy_entry
from src.utils.io import PROJECT_ROOT, read_json


OUTPUT_PATH = PROJECT_ROOT / "data" / "audits" / "review_cli_audit.json"
REQUIRED = {
    "Candidate ID", "Example", "Source URL", "Source Item ID", "Retrieval Tier",
    "Review Status", "Reviewer Notes", "Review Priority Score", "Priority Basis",
}


def main() -> None:
    taxonomy = read_json(PROJECT_ROOT / "config" / "taxonomy.json")
    categories = [item["code"] for item in taxonomy["subcategories"]]
    results: dict[str, dict[str, object]] = {}
    failures: list[dict[str, object]] = []
    for category in categories:
        path = review_queue_path(category)
        fields, rows = load_rows(path)
        missing = sorted(REQUIRED - set(fields))
        invalid_statuses = sorted({row.get("Review Status") or "" for row in rows} - ALLOWED)
        invalid_priority = [
            row.get("Candidate ID") for row in rows
            if not (row.get("Review Priority Score") or "").isdigit()
            or not 0 <= int(row.get("Review Priority Score") or -1) <= 100
        ]
        taxonomy_entry(category)
        all_pending = pending_order(rows, priority=False)
        priority_pending = pending_order(rows, priority=True)
        primary_pending = pending_order(rows, priority=True, tier="PRIMARY")
        secondary_pending = pending_order(rows, priority=True, tier="SECONDARY")
        priority_scores = [int(rows[index]["Review Priority Score"]) for index in priority_pending]
        errors: list[str] = []
        if not path.exists():
            errors.append("missing review queue")
        if missing:
            errors.append(f"missing fields: {missing}")
        if invalid_statuses:
            errors.append(f"invalid statuses: {invalid_statuses}")
        if invalid_priority:
            errors.append(f"invalid priority: {invalid_priority}")
        if sorted(all_pending) != sorted(priority_pending):
            errors.append("priority mode does not cover the same PENDING rows")
        if priority_scores != sorted(priority_scores, reverse=True):
            errors.append("priority mode is not descending")
        if set(primary_pending) & set(secondary_pending):
            errors.append("primary/secondary filters overlap")
        if any(rows[index].get("Review Status") != "PENDING" for index in all_pending):
            errors.append("interactive order includes a non-PENDING row")
        results[category] = {
            "queue": str(path.relative_to(PROJECT_ROOT)),
            "rows": len(rows),
            "pending": len(all_pending),
            "primary_pending": len(primary_pending),
            "secondary_pending": len(secondary_pending),
            "priority_order_valid": priority_scores == sorted(priority_scores, reverse=True),
            "pending_only_enforced": True,
            "errors": errors,
        }
        if errors:
            failures.append({"category": category, "errors": errors})
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "categories_audited": len(categories),
        "policy": "Interactive review exposes only PENDING rows. No machine path assigns ACCEPT.",
        "available_flags": ["--priority", "--primary-only", "--secondary-only", "--pending-only"],
        "results": results,
        "failures": failures,
    }
    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(OUTPUT_PATH)
    print(json.dumps({"categories_audited": len(categories), "failures": len(failures)}))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
