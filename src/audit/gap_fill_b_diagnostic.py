"""Measured before-state diagnostic for gap-fill batch B."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from src.utils.io import PROJECT_ROOT, read_json


CATEGORIES = ("STA-1", "STA-2", "STA-4", "REL-1")
FAILURES = {
    "STA-1": ("semantic recall too narrow", ["poor source relevance", "source-title keyword contamination"]),
    "STA-2": ("poor source relevance", ["category boundary confusion", "semantic recall too narrow"]),
    "STA-4": ("semantic recall too narrow", ["lexical recall too narrow", "category boundary confusion"]),
    "REL-1": ("poor source relevance", ["source concentration", "category boundary confusion"]),
}


def main() -> None:
    profile = read_json(PROJECT_ROOT / "data" / "audits" / "consolidation_profile.json")
    manual = read_json(PROJECT_ROOT / "data" / "audits" / "consolidation_manual_assessments.json")
    categories = {}
    for category in CATEGORIES:
        row = profile["categories"][category]
        assessment = manual["categories"][category]
        primary_failure, additional = FAILURES[category]
        categories[category] = {
            "Current raw": row["raw_records"],
            "Current unique raw": row["unique_raw"],
            "Current PRIMARY": row["primary"],
            "Current SECONDARY": row["secondary"],
            "Current total review queue": row["total_review"],
            "Current ACCEPT": row["status_counts"].get("ACCEPT", 0),
            "Current REJECT": row["status_counts"].get("REJECT", 0),
            "Current UNSURE": row["status_counts"].get("UNSURE", 0),
            "Current MOVE": row["status_counts"].get("MOVE_TO_OTHER_CATEGORY", 0),
            "Current PENDING": row["status_counts"].get("PENDING", 0),
            "Distinct source URLs": row["distinct_source_urls"],
            "Largest source share": row["largest_source_share"],
            "Platform distribution": row["platform_distribution"],
            "Verified provenance": row["verified_provenance"],
            "Estimated review precision": {
                "estimate": assessment["estimated_precision"],
                "basis": assessment["main_issue"],
            },
            "Primary failure mode": primary_failure,
            "Additional failure modes": additional,
        }
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scope": list(CATEGORIES),
        "method_note": "Counts are measured. Precision is the prior manual retrieval-quality estimate, not human annotation truth.",
        "categories": categories,
    }
    path = PROJECT_ROOT / "data" / "audits" / "gap_fill_b_before.json"
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(path)
    print(json.dumps(categories, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
