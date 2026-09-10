from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from src.utils.io import PROJECT_ROOT, read_json


PRIMARY_PATH = PROJECT_ROOT / "data" / "candidates" / "GEN-1.csv"
BROAD_PATH = PROJECT_ROOT / "data" / "candidates" / "GEN-1.broad_discovery.csv"
SECONDARY_PATH = PROJECT_ROOT / "data" / "candidates" / "GEN-1.secondary_review.csv"
REVIEW_QUEUE_PATH = PROJECT_ROOT / "data" / "reviewed" / "GEN-1.review_queue.csv"
METRICS_PATH = PROJECT_ROOT / "data" / "candidates" / "GEN-1.secondary_review.metrics.json"

REVIEW_FIELDS = [
    "Candidate ID", "Example", "Context", "Source Platform", "Source Name",
    "Source URL", "Content URL", "Source Item ID", "Retrieval Tier",
    "Retrieval Signal", "Stance Hint", "Stance Evidence", "Suggested Category",
    "Review Status", "Reviewer Notes",
]
SECONDARY_FIELDS = REVIEW_FIELDS + [
    "Secondary Rank", "Secondary Score", "Similarity Score", "Raw Matched Signals",
    "Provenance", "Verified Source Title", "Verified Source Publisher", "Retrieved At",
]
FOCUS_STANCES = {"AMBIGUOUS", "POSSIBLE_COUNTER_SPEECH", "QUOTED_OR_REPORTED_ABUSE"}
DECISION_STATUSES = {"ACCEPT", "REJECT", "UNSURE", "MOVE_TO_OTHER_CATEGORY"}
HARM_GROUPS = {
    "inferiority", "role_enforcement", "public_or_political_exclusion",
    "victim_blaming", "class_blame", "rights_money_family_harm",
    "hostile_anti_feminism",
}
HOSTILE_SUPPLEMENT_TERMS = {"fitna", "sajda qilish", "buzuq", "фитна", "сажда қилиш", "бузуқ"}


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def split_signals(row: dict[str, str]) -> list[str]:
    return [value.strip() for value in (row.get("Matched Signals") or "").split("||") if value.strip()]


def signal_pairs(row: dict[str, str]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for signal in split_signals(row):
        name, separator, value = signal.partition(":")
        if separator:
            pairs.append((name, value))
    return pairs


def values_for(row: dict[str, str], groups: set[str] | str) -> list[str]:
    group_set = {groups} if isinstance(groups, str) else groups
    return [value for name, value in signal_pairs(row) if name in group_set]


def has_target(row: dict[str, str]) -> bool:
    return bool(values_for(row, "target"))


def harm_values(row: dict[str, str]) -> list[str]:
    return values_for(row, HARM_GROUPS)


def hostile_supplement_values(row: dict[str, str]) -> list[str]:
    return [value for value in values_for(row, "contempt") if value in HOSTILE_SUPPLEMENT_TERMS]


def similarity_score(row: dict[str, str]) -> float:
    try:
        return float(row.get("Similarity Score") or 0)
    except ValueError:
        return 0.0


def secondary_score(row: dict[str, str], supplemental: bool = False) -> float:
    harms = harm_values(row) or hostile_supplement_values(row)
    harm_groups = {name for name, _ in signal_pairs(row) if name in HARM_GROUPS}
    try:
        retrieval_score = float(row.get("Retrieval Score") or 0)
    except ValueError:
        retrieval_score = 0.0
    stance_bonus = {
        "AMBIGUOUS": 2.0,
        "QUOTED_OR_REPORTED_ABUSE": 1.5,
        "POSSIBLE_COUNTER_SPEECH": 1.0,
    }.get(row.get("Stance Hint") or "", 0.0)
    score = 10.0 + retrieval_score + 3.0 * len(harm_groups) + stance_bonus
    score += min(2.5, similarity_score(row) * 5.0)
    score += min(2.0, max(0, len(harms) - 1) * 0.5)
    if supplemental:
        score -= 3.0
    return round(score, 4)


def stance_evidence(row: dict[str, str]) -> str:
    stance = row.get("Stance Hint") or "AMBIGUOUS"
    pairs = signal_pairs(row)
    if stance == "POSSIBLE_COUNTER_SPEECH":
        markers = [value for name, value in pairs if name == "stance_counter"]
        opening = (
            f"Contains possible counter-speech marker '{markers[0]}'"
            if markers else "Contains language that may oppose or condemn the harmful position"
        )
    elif stance == "QUOTED_OR_REPORTED_ABUSE":
        markers = [value for name, value in pairs if name == "stance_reported"]
        opening = (
            f"Contains reporting/quotation marker '{markers[0]}'"
            if markers else "Appears to quote or report a potentially harmful position"
        )
    else:
        markers = [value for name, value in pairs if name == "stance_ambiguous"]
        if markers:
            opening = f"Contains contrast/ambiguity marker '{markers[0]}'"
        elif "?" in (row.get("Example") or ""):
            opening = "Contains a question mark, so endorsement is uncertain"
        else:
            opening = "The speaker's stance is not resolved by the configured markers"
    harms = harm_values(row) or hostile_supplement_values(row)
    if harms:
        return (
            f"Machine hint: {opening}; the same text also contains possible GEN-1 harm wording "
            f"'{harms[0]}'. Review whether the speaker endorses, reports, or challenges it."
        )
    return "Machine hint: " + opening + ". Review the original text; this is not ground truth."


def retrieval_reason(row: dict[str, str]) -> str:
    targets = values_for(row, "target")
    harms = harm_values(row)
    if harms:
        reason = f"Explicit female target '{targets[0]}' plus harm-bearing wording '{harms[0]}'."
    else:
        hostile = hostile_supplement_values(row)
        reason = f"Explicit female target '{targets[0]}' plus hostile anti-feminist wording '{hostile[0]}'."
    similarity = similarity_score(row)
    if similarity:
        reason += f" Taxonomy similarity {similarity:.4f} is used only for ranking."
    return reason


def existing_decisions() -> dict[str, tuple[str, str]]:
    decisions: dict[str, tuple[str, str]] = {}
    paths = [
        REVIEW_QUEUE_PATH,
        PROJECT_ROOT / "data" / "reviewed" / "GEN-1.csv",
        PROJECT_ROOT / "data" / "rejected" / "GEN-1.csv",
        PRIMARY_PATH,
        SECONDARY_PATH,
        BROAD_PATH,
    ]
    for path in paths:
        for row in read_csv(path):
            candidate_id = row.get("Candidate ID")
            if not candidate_id:
                continue
            status = (row.get("Review Status") or "PENDING").strip()
            notes = row.get("Reviewer Notes") or ""
            previous = decisions.get(candidate_id)
            if previous is None:
                decisions[candidate_id] = (status, notes)
            elif status in DECISION_STATUSES and previous[0] not in DECISION_STATUSES:
                decisions[candidate_id] = (status, notes)
    return decisions


def secondary_candidates(broad: list[dict[str, str]]) -> list[dict[str, Any]]:
    core = [
        row for row in broad
        if row.get("Stance Hint") in FOCUS_STANCES and has_target(row) and harm_values(row)
    ]
    core_ids = {row["Candidate ID"] for row in core}
    supplemental = [
        row for row in broad
        if row.get("Candidate ID") not in core_ids
        and row.get("Stance Hint") in FOCUS_STANCES
        and has_target(row)
        and hostile_supplement_values(row)
    ]
    ranked_core = sorted(
        ((secondary_score(row), row) for row in core),
        key=lambda item: (-item[0], item[1]["Candidate ID"]),
    )[:50]
    target_count = min(50, max(20, len(ranked_core)))
    ranked_supplemental = sorted(
        ((secondary_score(row, supplemental=True), row) for row in supplemental),
        key=lambda item: (-item[0], item[1]["Candidate ID"]),
    )
    ranked = ranked_core + ranked_supplemental[:max(0, target_count - len(ranked_core))]
    return [
        {"row": row, "secondary_score": score, "secondary_rank": rank}
        for rank, (score, row) in enumerate(ranked, 1)
    ]


def review_row(
    source: dict[str, str], tier: str, signal: str, evidence: str,
    suggested: str, decision: tuple[str, str],
) -> dict[str, Any]:
    return {
        "Candidate ID": source.get("Candidate ID") or "",
        "Example": source.get("Example") or "",
        "Context": source.get("Context") or "",
        "Source Platform": source.get("Source Platform") or "",
        "Source Name": source.get("Source Name") or "",
        "Source URL": source.get("Source URL") or "",
        "Content URL": source.get("Content URL") or "",
        "Source Item ID": source.get("Source Item ID") or "",
        "Retrieval Tier": tier,
        "Retrieval Signal": signal,
        "Stance Hint": source.get("Stance Hint") or "AMBIGUOUS",
        "Stance Evidence": evidence,
        "Suggested Category": suggested,
        "Review Status": decision[0],
        "Reviewer Notes": decision[1],
    }


def source_is_verified(row: dict[str, Any], sources: dict[str, dict[str, Any]]) -> bool:
    source = sources.get(str(row.get("Source URL") or ""))
    return bool(
        source
        and source.get("reachability", {}).get("reachable")
        and source.get("identity_verification", {}).get("verified")
        and row.get("Source Item ID")
        and row.get("Example")
    )


def main() -> None:
    primary = read_csv(PRIMARY_PATH)
    broad = read_csv(BROAD_PATH)
    prior_review_queue = read_csv(REVIEW_QUEUE_PATH)
    decisions = existing_decisions()
    selected = secondary_candidates(broad)

    secondary_rows: list[dict[str, Any]] = []
    for item in selected:
        source = item["row"]
        decision = decisions.get(source["Candidate ID"], ("PENDING", ""))
        row = review_row(
            source, "SECONDARY", retrieval_reason(source), stance_evidence(source),
            "UNSURE", decision,
        )
        row.update({
            "Secondary Rank": item["secondary_rank"],
            "Secondary Score": item["secondary_score"],
            "Similarity Score": source.get("Similarity Score") or "0",
            "Raw Matched Signals": source.get("Matched Signals") or "",
            "Provenance": source.get("Provenance") or "",
            "Verified Source Title": source.get("Verified Source Title") or "",
            "Verified Source Publisher": source.get("Verified Source Publisher") or "",
            "Retrieved At": source.get("Retrieved At") or "",
        })
        secondary_rows.append(row)

    combined_rows: list[dict[str, Any]] = []
    for source in primary:
        decision = decisions.get(source["Candidate ID"], ("PENDING", ""))
        harms = harm_values(source)
        strong = values_for(source, "strong")
        matched = strong or harms
        signal = (
            f"Primary rule match: '{matched[0]}'. Similarity is secondary/ranking-only."
            if matched else "Primary rule match recorded in the source candidate queue."
        )
        evidence = (
            f"Direct target-and-harm wording '{matched[0]}' with no configured counter/report marker. "
            "This is a machine-generated review hint, not a decision."
            if matched else "Primary retrieval rule matched; stance hint is not ground truth."
        )
        combined_rows.append(review_row(source, "PRIMARY", signal, evidence, "GEN-1", decision))
    combined_rows.extend({field: row.get(field, "") for field in REVIEW_FIELDS} for row in secondary_rows)

    # A retrieval rerun may rank a previously reviewed row outside the current
    # top tiers. Human decisions remain canonical and must never disappear.
    combined_ids = {row.get("Candidate ID") for row in combined_rows}
    for prior in prior_review_queue:
        candidate_id = prior.get("Candidate ID") or ""
        if candidate_id in combined_ids:
            continue
        if (prior.get("Review Status") or "") not in DECISION_STATUSES:
            continue
        combined_rows.append({field: prior.get(field, "") for field in REVIEW_FIELDS})
        combined_ids.add(candidate_id)

    write_csv(SECONDARY_PATH, secondary_rows, SECONDARY_FIELDS)
    write_csv(REVIEW_QUEUE_PATH, combined_rows, REVIEW_FIELDS)

    registry = read_json(PROJECT_ROOT / "config" / "sources.json")
    sources = {source["url"]: source for source in registry["sources"]}
    stance_counts = Counter(row["Stance Hint"] for row in secondary_rows)
    status_counts = Counter(row["Review Status"] for row in combined_rows)
    metrics = {
        "primary_candidates": len(primary),
        "secondary_review_candidates": len(secondary_rows),
        "combined_human_review_candidates": len(combined_rows),
        "secondary_by_original_stance": {
            stance: stance_counts[stance]
            for stance in ("AMBIGUOUS", "POSSIBLE_COUNTER_SPEECH", "QUOTED_OR_REPORTED_ABUSE")
        },
        "distinct_sources_represented": len({row["Source URL"] for row in combined_rows}),
        "candidates_with_factual_context": sum(bool(row["Context"]) for row in combined_rows),
        "candidates_with_verified_source_provenance": sum(source_is_verified(row, sources) for row in combined_rows),
        "candidates_lacking_exact_direct_permalink": sum(not bool(row["Content URL"]) for row in combined_rows),
        "review_status_counts": {
            status: status_counts[status]
            for status in ("ACCEPT", "REJECT", "UNSURE", "MOVE_TO_OTHER_CATEGORY", "PENDING")
        },
        "selection_method": {
            "core": "Focused stance + explicit female target + configured GEN-1 harm-bearing signal",
            "supplement": "Highest-ranked focused-stance row with explicit female target + hostile anti-feminist/contempt wording",
            "taxonomy_similarity": "ranking-only",
            "maximum_secondary_rows": 50,
            "minimum_target_rows": 20,
        },
    }
    METRICS_PATH.write_text(json.dumps(metrics, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"PRIMARY\t{metrics['primary_candidates']}")
    print(f"SECONDARY\t{metrics['secondary_review_candidates']}")
    print(f"COMBINED\t{metrics['combined_human_review_candidates']}")
    for stance, count in metrics["secondary_by_original_stance"].items():
        print(f"SECONDARY_{stance}\t{count}")
    print(f"DISTINCT_SOURCES\t{metrics['distinct_sources_represented']}")
    print(f"VERIFIED_PROVENANCE\t{metrics['candidates_with_verified_source_provenance']}")


if __name__ == "__main__":
    main()
