"""Write the factual starting diagnostic for targeted gap-fill batch A."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from src.utils.io import PROJECT_ROOT, read_json


SCOPE = ("GEN-1", "REG-1", "REG-3", "REG-4")
FAILURES = {
    "GEN-1": [
        "poor source relevance", "semantic recall too narrow", "counter-speech contamination",
    ],
    "REG-1": [
        "insufficient raw data", "source-title keyword contamination", "source concentration",
    ],
    "REG-3": [
        "insufficient raw data", "lexical recall too narrow", "semantic recall too narrow",
        "source concentration",
    ],
    "REG-4": [
        "poor source relevance", "semantic recall too narrow", "counter-speech/noise",
    ],
}
PRECISION = {
    "GEN-1": {
        "estimate": 0.086,
        "basis": "3 ACCEPT among 35 already human-reviewed GEN-1 rows; this is observed yield, not model truth.",
    },
    "REG-1": {
        "estimate": 1.0,
        "basis": "Prior manual consolidation audit judged all 3 active rows plausible; n=3 is too small for stability.",
    },
    "REG-3": {
        "estimate": 1.0,
        "basis": "Prior manual consolidation audit judged the sole active row plausible; n=1 is not a stable estimate.",
    },
    "REG-4": {
        "estimate": 0.0,
        "basis": "Prior false-positive audit removed all 7 unreviewed topic-only/support rows from the active queue.",
    },
}


def main() -> None:
    profile = read_json(PROJECT_ROOT / "data" / "audits" / "consolidation_profile.json")
    categories = {}
    for category in SCOPE:
        row = profile["categories"][category]
        categories[category] = {
            "Current raw": row["raw_records"],
            "Current unique raw": row["unique_raw"],
            "Current PRIMARY": row["primary"],
            "Current SECONDARY": row["secondary"],
            "Current total review queue": row["total_review"],
            "Current ACCEPT": row["status_counts"]["ACCEPT"],
            "Current REJECT": row["status_counts"]["REJECT"],
            "Current UNSURE": row["status_counts"]["UNSURE"],
            "Current MOVE": row["status_counts"]["MOVE_TO_OTHER_CATEGORY"],
            "Current PENDING": row["status_counts"]["PENDING"],
            "Distinct source URLs": row["distinct_source_urls"],
            "Largest source share": row["largest_source_share"],
            "Platform distribution": row["platform_distribution"],
            "Estimated review precision": PRECISION[category],
            "Primary failure mode": FAILURES[category][0],
            "Additional failure modes": FAILURES[category][1:],
            "Provenance failures": row["unverified_provenance"],
        }
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scope": list(SCOPE),
        "categories": categories,
        "method_note": "Counts are measured; precision entries are explicitly labeled estimates with their evidence basis.",
    }
    path = PROJECT_ROOT / "data" / "audits" / "gap_fill_a_before.json"
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(path)


if __name__ == "__main__":
    main()
