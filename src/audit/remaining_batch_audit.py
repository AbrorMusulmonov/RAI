"""Deterministic retrieval QA for REG/STA/REL batches without review decisions."""

from __future__ import annotations

import argparse
import csv
import json
import random
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from src.processing.category import lexical, source_verified
from src.utils.io import PROJECT_ROOT, read_json, read_jsonl


BATCHES = {
    "REG": [f"REG-{number}" for number in range(1, 5)],
    "STA": [f"STA-{number}" for number in range(1, 6)],
    "REL": [f"REL-{number}" for number in range(1, 3)],
}


def rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def raw_index() -> set[tuple[str, str, str]]:
    result: set[tuple[str, str, str]] = set()
    for path in (PROJECT_ROOT / "data" / "raw").rglob("*.jsonl"):
        if path.name.endswith(".provenance.jsonl"):
            continue
        for row in read_jsonl(path):
            result.add((
                str(row.get("source_url") or ""),
                str(row.get("source_item_id") or ""),
                str(row.get("original_text") or ""),
            ))
    return result


def retrieval_assessment(row: dict[str, str], in_queue: bool) -> tuple[str, str]:
    signal = (row.get("Retrieval Signal") or "").casefold()
    matched = (row.get("Matched Signals") or "").casefold()
    stance = row.get("Stance Hint") or ""
    evidence = f"{signal} || {matched}"
    has_target = "concept_" in evidence and any(token in evidence for token in ("target", "religiosity", "belief", "education", "age_", "occupation", "class_", "migrant", "language", "speaker", "rural", "regional", "disability"))
    has_harm = any(token in evidence for token in (
        "composition:", "semantic composition", "strong:", "strong lexical signal", "standalone:", "standalone category",
        "contempt", "exclusion", "stereotype", "denunciation", "mockery",
        "loyalty", "inferiority", "shame", "failure", "harm", "defect",
        "worth", "incompetence", "obsolete", "rights", "condemnation", "danger",
    ))
    if in_queue:
        if stance == "POSSIBLE_COUNTER_SPEECH":
            return "AMBIGUOUS_RELEVANCE", "Counter-speech marker; retained for human judgment only when configured category evidence is present."
        if stance == "QUOTED_OR_REPORTED_ABUSE":
            return "AMBIGUOUS_RELEVANCE", "Reported/quoted abuse is retrievable evidence but may not be an abusive author stance."
        if has_harm:
            return "LIKELY_RELEVANT", "Configured category target/harm composition or strong lexical evidence is present."
        return "POSSIBLE_FALSE_POSITIVE", "Queued without an inspectable target-and-harm signal in the exported audit fields."
    if has_target and has_harm:
        return "POSSIBLE_FALSE_NEGATIVE", "Excluded row still exposes both target and harm evidence and needs threshold review."
    return "LIKELY_CORRECT_EXCLUSION", "Topic/target-only evidence does not establish category harm."


def audit_category(category: str, registry: dict[str, dict[str, Any]], raw: set[tuple[str, str, str]]) -> dict[str, Any]:
    queue = rows(PROJECT_ROOT / "data" / "reviewed" / f"{category}.review_queue.csv")
    broad = rows(PROJECT_ROOT / "data" / "candidates" / f"{category}.broad_discovery.csv")
    excluded = rows(PROJECT_ROOT / "data" / "candidates" / f"{category}.excluded_high_score.csv")
    rng = random.Random(f"remaining-audit-v1:{category}")
    review_sample = rng.sample(queue, min(20, len(queue)))
    nonqueue = sorted(
        broad + excluded,
        key=lambda row: (-float(row.get("Retrieval Score") or 0), row.get("Candidate ID") or ""),
    )[:10]

    def sampled(row: dict[str, str], in_queue: bool) -> dict[str, str]:
        assessment, reason = retrieval_assessment(row, in_queue)
        return {
            "candidate_id": row.get("Candidate ID") or "",
            "example": row.get("Example") or "",
            "source_url": row.get("Source URL") or "",
            "source_item_id": row.get("Source Item ID") or "",
            "retrieval_tier": row.get("Retrieval Tier") or "",
            "retrieval_signal": row.get("Retrieval Signal") or "",
            "stance_hint": row.get("Stance Hint") or "",
            "audit_assessment": assessment,
            "audit_reason": reason,
            "review_status_unchanged": row.get("Review Status") or "",
        }

    review_audit = [sampled(row, True) for row in review_sample]
    exclusion_audit = [sampled(row, False) for row in nonqueue]
    provenance_failures: list[dict[str, str]] = []
    for row in queue:
        url = row.get("Source URL") or ""
        item_id = row.get("Source Item ID") or ""
        text = row.get("Example") or ""
        source = registry.get(url)
        reason = ""
        if not source:
            reason = "SOURCE_NOT_IN_REGISTRY"
        elif not source_verified(source):
            reason = "SOURCE_IDENTITY_OR_REACHABILITY_UNVERIFIED"
        elif not item_id:
            reason = "SOURCE_ITEM_ID_MISSING"
        elif (url, item_id, text) not in raw:
            reason = "EXACT_RAW_OCCURRENCE_MISSING"
        content_url = row.get("Content URL") or ""
        if not reason and content_url and urlparse(content_url).netloc.casefold() not in {"youtube.com", "www.youtube.com", "youtu.be"}:
            reason = "DIRECT_PERMALINK_HOST_INVALID"
        if reason:
            provenance_failures.append({"candidate_id": row.get("Candidate ID") or "", "reason": reason})

    normalized = [lexical(row.get("Example") or "") for row in queue]
    exact_duplicates = len(normalized) - len(set(normalized))
    near_pairs: list[list[str]] = []
    for left in range(len(queue)):
        for right in range(left + 1, len(queue)):
            if normalized[left] == normalized[right] or not normalized[left] or not normalized[right]:
                continue
            if min(len(normalized[left]), len(normalized[right])) < 24:
                continue
            ratio = SequenceMatcher(None, normalized[left], normalized[right], autojunk=False).ratio()
            if ratio >= .96:
                near_pairs.append([queue[left].get("Candidate ID") or "", queue[right].get("Candidate ID") or ""])

    assessment_counts = Counter(row["audit_assessment"] for row in review_audit + exclusion_audit)
    source_counts = Counter(row.get("Source URL") or "" for row in queue)
    return {
        "category": category,
        "review_candidate_count": len(queue),
        "review_sample_requested": 20,
        "review_sample_size": len(review_audit),
        "review_sample_shortfall_reason": None if len(queue) >= 20 else "Fewer than 20 defensible review candidates exist.",
        "high_scoring_exclusion_sample_requested": 10,
        "high_scoring_exclusion_sample_size": len(exclusion_audit),
        "review_sample": review_audit,
        "high_scoring_exclusion_sample": exclusion_audit,
        "assessment_counts": dict(sorted(assessment_counts.items())),
        "likely_false_positive_count_in_sample": sum(row["audit_assessment"] in {"LIKELY_FALSE_POSITIVE", "POSSIBLE_FALSE_POSITIVE"} for row in review_audit),
        "possible_false_negative_count_in_sample": sum(row["audit_assessment"] == "POSSIBLE_FALSE_NEGATIVE" for row in exclusion_audit),
        "exact_duplicate_count": exact_duplicates,
        "near_duplicate_pairs": near_pairs,
        "distinct_sources": len(source_counts),
        "candidates_per_source": dict(sorted(source_counts.items())),
        "largest_source_share": round(max(source_counts.values(), default=0) / len(queue), 4) if queue else 0.0,
        "provenance_failure_count": len(provenance_failures),
        "provenance_failures": provenance_failures,
        "all_review_statuses_pending": all((row.get("Review Status") or "") == "PENDING" for row in queue),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("batch", choices=sorted(BATCHES))
    args = parser.parse_args()
    registry_doc = read_json(PROJECT_ROOT / "config" / "sources.json")
    registry = {str(row.get("url") or ""): row for row in registry_doc.get("sources", [])}
    raw = raw_index()
    audits = [audit_category(category, registry, raw) for category in BATCHES[args.batch]]
    output = {
        "batch": args.batch,
        "audit_method": "Deterministic 20-row random review sample plus top-10 non-queue score sample; retrieval QA only, never a human ACCEPT decision.",
        "categories": audits,
        "totals": {
            "review_candidates": sum(row["review_candidate_count"] for row in audits),
            "sampled_review_candidates": sum(row["review_sample_size"] for row in audits),
            "sampled_nonqueue_candidates": sum(row["high_scoring_exclusion_sample_size"] for row in audits),
            "likely_false_positives": sum(row["likely_false_positive_count_in_sample"] for row in audits),
            "possible_false_negatives": sum(row["possible_false_negative_count_in_sample"] for row in audits),
            "provenance_failures": sum(row["provenance_failure_count"] for row in audits),
        },
    }
    path = PROJECT_ROOT / "data" / "audits" / f"{args.batch}_batch_audit.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(path)
    print(json.dumps(output["totals"], ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
