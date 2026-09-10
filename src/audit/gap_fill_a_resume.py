"""Record the exact interrupted-state checkpoint for gap-fill batch A."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from src.utils.io import PROJECT_ROOT, read_json


SCOPE = ("GEN-1", "REG-1", "REG-3", "REG-4")


def main() -> None:
    profile = read_json(PROJECT_ROOT / "data" / "audits" / "consolidation_profile.json")
    states = {
        "GEN-1": {
            "overall": "PARTIAL",
            "Pass 1 completed": True,
            "Pass 2 completed": True,
            "Pass 3 completed": True,
            "post_collection_queue_generation_completed": False,
            "false_positive_audit_completed": False,
            "false_negative_audit_completed": False,
            "source_diversity_audit_completed": False,
        },
        "REG-1": {
            "overall": "PARTIAL",
            "Pass 1 completed": True,
            "Pass 2 completed": True,
            "Pass 3 completed": True,
            "post_collection_queue_generation_completed": True,
            "false_positive_audit_completed": False,
            "false_negative_audit_completed": False,
            "source_diversity_audit_completed": False,
        },
        "REG-3": {
            "overall": "PARTIAL",
            "Pass 1 completed": True,
            "Pass 2 completed": True,
            "Pass 3 completed": True,
            "post_collection_queue_generation_completed": True,
            "false_positive_audit_completed": False,
            "false_negative_audit_completed": False,
            "source_diversity_audit_completed": False,
        },
        "REG-4": {
            "overall": "PARTIAL",
            "Pass 1 completed": True,
            "Pass 2 completed": True,
            "Pass 3 completed": True,
            "post_collection_queue_generation_completed": True,
            "false_positive_audit_completed": False,
            "false_negative_audit_completed": False,
            "source_diversity_audit_completed": False,
        },
    }
    for category in SCOPE:
        row = profile["categories"][category]
        states[category]["measured_state"] = {
            "raw": row["raw_records"],
            "unique_raw": row["unique_raw"],
            "primary": row["primary"],
            "secondary": row["secondary"],
            "active_review": row["total_review"],
            "status_counts": row["status_counts"],
            "distinct_sources": row["distinct_source_urls"],
            "largest_source_share": row["largest_source_share"],
            "verified_provenance": row["verified_provenance"],
        }
        states[category]["gap_fill_workbook_generated"] = False
        states[category]["post_change_tests_passed"] = False
    output = {
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scope": list(SCOPE),
        "categories": states,
        "precise_last_successful_checkpoint": (
            "REG-4 targeted collection completed at 2026-08-27T20:17:31+00:00 "
            "with 2,103 new real comments from 23 attempted verified sources; the "
            "three regional queues were then regenerated, but quality/false-negative "
            "audits, GEN-1 post-collection regeneration, workbook, docs, and tests remained."
        ),
        "repository_note": (
            "The working directory is inside an uncommitted Git repository rooted at the user home; "
            "there is no repository commit history for project-level change reconstruction."
        ),
    }
    path = PROJECT_ROOT / "data" / "audits" / "gap_fill_a_resume_map.json"
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(path)


if __name__ == "__main__":
    main()
