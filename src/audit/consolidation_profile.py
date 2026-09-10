"""Profile and sample all taxonomy queues for final consolidation QA."""

from __future__ import annotations

import csv
import hashlib
import json
import random
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.processing.category import source_verified
from src.utils.io import PROJECT_ROOT, read_json, read_jsonl
from src.utils.text import normalized_for_comparison


CATEGORIES = (
    "GEN-1", "GEN-2", "GEN-3", "GEN-4", "GEN-5",
    "REG-1", "REG-2", "REG-3", "REG-4",
    "STA-1", "STA-2", "STA-3", "STA-4", "STA-5",
    "REL-1", "REL-2",
)
STATUSES = ("ACCEPT", "REJECT", "UNSURE", "MOVE_TO_OTHER_CATEGORY", "PENDING")


def csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def compact(row: dict[str, str]) -> dict[str, str]:
    return {
        key: row.get(key) or ""
        for key in (
            "Candidate ID", "Example", "Source URL", "Source Item ID", "Retrieval Tier",
            "Retrieval Score", "Matched Signals", "Retrieval Signal", "Stance Hint",
            "Possible Compound Category", "Review Status",
        )
    }


def deterministic_sample(rows: list[dict[str, str]], count: int, seed: str) -> list[dict[str, str]]:
    if len(rows) <= count:
        return list(rows)
    generator = random.Random(int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16], 16))
    return [rows[index] for index in sorted(generator.sample(range(len(rows)), count))]


def score(row: dict[str, str]) -> float:
    try:
        return float(row.get("Retrieval Score") or 0.0)
    except ValueError:
        return 0.0


def all_raw() -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    by_id: dict[str, dict[str, Any]] = {}
    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for path in sorted((PROJECT_ROOT / "data" / "raw").rglob("*.jsonl")):
        if path.name.endswith(".provenance.jsonl"):
            continue
        for row in read_jsonl(path):
            raw_id = str(row.get("raw_record_id") or "")
            if raw_id:
                by_id.setdefault(raw_id, row)
            if path.stem in CATEGORIES:
                by_category[path.stem].append(row)
    return by_id, by_category


def discovery_passes() -> dict[str, set[str]]:
    result = {category: set() for category in CATEGORIES}
    path = PROJECT_ROOT / "data" / "logs" / "source_discovery.jsonl"
    if not path.exists():
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        pass_name = str(record.get("pass_name") or "default")
        for category in record.get("categories") or []:
            if category in result:
                result[category].add(pass_name)
    return result


def main() -> None:
    registry_doc = read_json(PROJECT_ROOT / "config" / "sources.json")
    registry = {str(row.get("url") or ""): row for row in registry_doc.get("sources", [])}
    raw_by_id, raw_by_category = all_raw()
    passes = discovery_passes()
    profile: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scope": list(CATEGORIES),
        "categories": {},
        "cross_category_duplicates": [],
    }
    samples: dict[str, Any] = {}
    text_locations: dict[str, list[dict[str, str]]] = defaultdict(list)

    for category in CATEGORIES:
        queue_path = PROJECT_ROOT / "data" / "reviewed" / f"{category}.review_queue.csv"
        primary = csv_rows(PROJECT_ROOT / "data" / "candidates" / f"{category}.csv")
        secondary = csv_rows(PROJECT_ROOT / "data" / "candidates" / f"{category}.secondary_review.csv")
        queue = csv_rows(queue_path)
        excluded = csv_rows(PROJECT_ROOT / "data" / "candidates" / f"{category}.excluded_high_score.csv")
        broad = csv_rows(PROJECT_ROOT / "data" / "candidates" / f"{category}.broad_discovery.csv")
        if len(excluded) < 10:
            known = {row.get("Candidate ID") for row in excluded}
            excluded.extend(row for row in broad if row.get("Candidate ID") not in known)
        occurrences: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for occurrence in read_jsonl(PROJECT_ROOT / "data" / "candidates" / f"{category}.occurrences.jsonl"):
            occurrences[str(occurrence.get("candidate_id") or "")].append(occurrence)

        status_counts = Counter(row.get("Review Status") or "" for row in queue)
        sources = Counter(row.get("Source URL") or "" for row in queue)
        sources.pop("", None)
        names = Counter(row.get("Source Name") or "" for row in queue)
        names.pop("", None)
        platforms = Counter(row.get("Source Platform") or "" for row in queue)
        platforms.pop("", None)
        candidate_id_duplicates = sum(count - 1 for count in Counter(row.get("Candidate ID") for row in queue).values() if count > 1)
        normalized = Counter(normalized_for_comparison(row.get("Example") or "") for row in queue)
        text_duplicates = sum(count - 1 for text, count in normalized.items() if text and count > 1)

        failures: list[dict[str, str]] = []
        context_failures: list[str] = []
        for row in queue:
            candidate_id = row.get("Candidate ID") or ""
            source_url = row.get("Source URL") or ""
            item_id = row.get("Source Item ID") or ""
            source = registry.get(source_url)
            evidence = []
            for occurrence in occurrences.get(candidate_id, []):
                raw = raw_by_id.get(str(occurrence.get("raw_record_id") or ""))
                if raw:
                    evidence.append(raw)
            if not source or not source_verified(source):
                failures.append({"candidate_id": candidate_id, "reason": "SOURCE_UNVERIFIED"})
            elif not item_id:
                failures.append({"candidate_id": candidate_id, "reason": "SOURCE_ITEM_ID_MISSING"})
            elif not any(
                raw.get("source_url") == source_url
                and str(raw.get("source_item_id") or "") == item_id
                and raw.get("original_text") == row.get("Example")
                and raw.get("example_is_real_world") is True
                for raw in evidence
            ):
                failures.append({"candidate_id": candidate_id, "reason": "EXACT_RAW_EVIDENCE_MISSING"})
            context = row.get("Context") or ""
            factual_prefix = context.startswith("Public YouTube comment under video:")
            actual_parent = any(str(raw.get("platform_parent_context") or "").strip() for raw in evidence)
            if context and not factual_prefix and not actual_parent:
                context_failures.append(candidate_id)

            norm = normalized_for_comparison(row.get("Example") or "")
            if norm:
                text_locations[norm].append({
                    "category": category,
                    "candidate_id": candidate_id,
                    "example": row.get("Example") or "",
                    "compound_hint": row.get("Possible Compound Category") or "",
                })

        audit_files = []
        for path in (PROJECT_ROOT / "data" / "audits").glob("*"):
            if category in path.name or category.split("-")[0] + "_batch_audit" in path.name:
                audit_files.append(str(path.relative_to(PROJECT_ROOT)))
        raw_rows = raw_by_category.get(category, [])
        top_sources = [
            {"source_url": url, "candidate_count": count}
            for url, count in sources.most_common(5)
        ]
        profile["categories"][category] = {
            "raw_records": len(raw_rows),
            "unique_raw": len({str(row.get("raw_record_id") or "") for row in raw_rows if row.get("raw_record_id")}),
            "primary": len(primary),
            "secondary": len(secondary),
            "total_review": len(queue),
            "status_counts": {status: status_counts.get(status, 0) for status in STATUSES},
            "distinct_source_urls": len(sources),
            "distinct_source_names": len(names),
            "platform_distribution": dict(platforms),
            "top_5_sources": top_sources,
            "largest_source_contribution": max(sources.values(), default=0),
            "largest_source_share": round(max(sources.values(), default=0) / len(queue), 4) if queue else 0.0,
            "verified_provenance": len(queue) - len(failures),
            "unverified_provenance": len(failures),
            "provenance_failures": failures,
            "candidate_id_duplicate_count": candidate_id_duplicates,
            "normalized_text_duplicate_count": text_duplicates,
            "review_queue_exists": queue_path.exists(),
            "quality_audit_files": sorted(audit_files),
            "quality_audit_performed": bool(audit_files),
            "previous_collection_target_reached": len(queue) >= 100,
            "targeted_collection_passes": sorted(passes[category]),
            "context_failures": context_failures,
            "direct_permalink_count": sum(bool(row.get("Content URL")) for row in queue),
            "source_url_plus_item_id_only": sum(
                bool(row.get("Source URL")) and bool(row.get("Source Item ID")) and not bool(row.get("Content URL"))
                for row in queue
            ),
        }
        samples[category] = {
            "primary": [compact(row) for row in deterministic_sample(primary, 20, category + ":primary")],
            "secondary": [compact(row) for row in deterministic_sample(secondary, 20, category + ":secondary")],
            "excluded": [compact(row) for row in sorted(excluded, key=score, reverse=True)[:10]],
        }

    for norm, locations in sorted(text_locations.items()):
        categories = sorted({row["category"] for row in locations})
        if len(categories) > 1:
            profile["cross_category_duplicates"].append({
                "normalized_text_sha256": hashlib.sha256(norm.encode("utf-8")).hexdigest().upper(),
                "categories": categories,
                "occurrences": locations,
                "possible_compound_relevance": any(row["compound_hint"] for row in locations),
            })

    audit_dir = PROJECT_ROOT / "data" / "audits"
    (audit_dir / "consolidation_profile.json").write_text(
        json.dumps(profile, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (audit_dir / "consolidation_samples.json").write_text(
        json.dumps(samples, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(audit_dir / "consolidation_profile.json")
    print(json.dumps({
        "categories": len(profile["categories"]),
        "review_rows": sum(value["total_review"] for value in profile["categories"].values()),
        "provenance_failures": sum(value["unverified_provenance"] for value in profile["categories"].values()),
        "cross_category_duplicate_texts": len(profile["cross_category_duplicates"]),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
