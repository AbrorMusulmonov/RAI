from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import shutil
from collections import Counter
from pathlib import Path
from typing import Any

from src.utils.io import PROJECT_ROOT, read_json, read_jsonl
from src.utils.text import looks_uzbek, normalized_for_comparison, similarity


RAW_PATH = PROJECT_ROOT / "data" / "raw" / "youtube" / "GEN-1.jsonl"
REVIEW_QUEUE_PATH = PROJECT_ROOT / "data" / "reviewed" / "GEN-1.review_queue.csv"
CANDIDATE_PATH = PROJECT_ROOT / "data" / "candidates" / "GEN-1.csv"
PRE_PRECISION_PATH = PROJECT_ROOT / "data" / "candidates" / "GEN-1.pre_precision.csv"
PRE_STANCE_FIX_PATH = PROJECT_ROOT / "data" / "candidates" / "GEN-1.pre_stance_fix.csv"
BROAD_PATH = PROJECT_ROOT / "data" / "candidates" / "GEN-1.broad_discovery.csv"
OCCURRENCES_PATH = PROJECT_ROOT / "data" / "candidates" / "GEN-1.occurrences.jsonl"
PROVENANCE_PATH = PROJECT_ROOT / "data" / "raw" / "youtube" / "GEN-1.provenance.jsonl"
METRICS_PATH = PROJECT_ROOT / "data" / "candidates" / "GEN-1.metrics.json"
FIELDS = [
    "Candidate ID", "Example", "Context", "Platform Thread Context", "Stance Hint",
    "Source Platform", "Source Name", "Verified Source Title", "Verified Source Publisher",
    "Source URL", "Content URL", "Source Item ID", "Provenance", "Retrieved At",
    "Source Identity Method", "Search Term", "Retrieval Tier", "Retrieval Score",
    "Similarity Score", "Matched Signals", "Suspected Category", "Review Status",
    "Reviewer Notes",
]
DECISION_STATUSES = {"ACCEPT", "REJECT", "UNSURE", "MOVE_TO_OTHER_CATEGORY"}
HARM_GROUPS = {
    "inferiority", "role_enforcement", "public_or_political_exclusion",
    "victim_blaming", "class_blame", "rights_money_family_harm", "hostile_anti_feminism",
}
SUPPORT_GROUPS = {"collective_or_inherent", "prescription_or_denial"}
PRIMARY_STANCES = {"POSSIBLE_ABUSE"}
INITIAL_RAW_UNIQUE_COUNT = 2023
INITIAL_SOURCE_COUNT = 25


def stable_candidate_id(normalized_text: str) -> str:
    return "GEN1-C-" + hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()[:12].upper()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def decision_map() -> dict[str, tuple[str, str]]:
    """Preserve explicit human decisions and never synthesize one."""
    paths = [
        REVIEW_QUEUE_PATH, CANDIDATE_PATH, BROAD_PATH,
        PROJECT_ROOT / "data" / "reviewed" / "GEN-1.csv",
        PROJECT_ROOT / "data" / "rejected" / "GEN-1.csv",
    ]
    decisions: dict[str, tuple[str, str]] = {}
    for path in paths:
        for row in read_csv(path):
            candidate_id = row.get("Candidate ID")
            status = (row.get("Review Status") or "PENDING").strip()
            notes = row.get("Reviewer Notes") or ""
            if not candidate_id:
                continue
            previous = decisions.get(candidate_id)
            if previous is None or status in DECISION_STATUSES:
                decisions[candidate_id] = (status, notes)
    return decisions


def corpus_raw_records(include_cross_category: bool) -> list[dict[str, Any]]:
    """Return real raw evidence, deduplicated by platform raw-record ID.

    Cross-category mode changes only the search space. It does not relabel raw data
    or write to another category's files.
    """
    if not include_cross_category:
        return read_jsonl(RAW_PATH)
    unique: dict[str, dict[str, Any]] = {}
    for path in sorted((PROJECT_ROOT / "data" / "raw").rglob("*.jsonl")):
        if path.name.endswith(".provenance.jsonl"):
            continue
        for record in read_jsonl(path):
            raw_id = str(record.get("raw_record_id") or "")
            if raw_id:
                unique.setdefault(raw_id, record)
    return list(unique.values())


def normalized_phrases(values: list[str]) -> list[tuple[str, str]]:
    return [(value, normalized_for_comparison(value)) for value in values]


def matched_phrases(text_norm: str, phrases: list[tuple[str, str]]) -> list[str]:
    return [original for original, normalized in phrases if normalized and normalized in text_norm]


def lexical_normalize(text: str) -> str:
    """Normalize separators for retrieval only; original text remains untouched."""
    value = normalized_for_comparison(text)
    return re.sub(r"[^\w']+", " ", value, flags=re.UNICODE).strip()


def matched_target_phrases(text_norm: str, phrases: list[tuple[str, str]]) -> list[str]:
    """Match configured target words with Uzbek case/possessive endings, not arbitrary substrings."""
    suffixes = (
        "", "lar", "lari", "larni", "larga", "lardan", "ning", "ni", "ga", "da", "dan",
        "ini", "iga", "ida", "idan", "ining", "isi", "isini", "isiga", "isida",
        "imni", "imga", "imizni", "ingizni",
        "i", "im", "imiz", "ingiz", "лар", "лари", "ларни", "ларга", "лардан", "нинг",
        "ни", "га", "да", "дан", "и", "им", "имиз", "ингиз",
    )
    hits: list[str] = []
    for original, normalized in phrases:
        if not normalized:
            continue
        endings = "|".join(re.escape(value) for value in sorted(suffixes, key=len, reverse=True))
        pattern = rf"(?<!\w){re.escape(normalized)}(?:{endings})(?!\w)"
        if re.search(pattern, text_norm):
            hits.append(original)
    return hits


def target_harm_proximity(
    text_norm: str, target_hits: list[str], group_hits: dict[str, list[str]], max_distance: int = 180,
) -> set[str]:
    """Require target and harm wording to occur locally, reducing cross-sentence false matches."""
    target_positions: list[int] = []
    for target in target_hits:
        needle = normalized_for_comparison(target)
        start = 0
        while needle and (position := text_norm.find(needle, start)) >= 0:
            target_positions.append(position)
            start = position + max(1, len(needle))
    close_groups: set[str] = set()
    for group_name, hits in group_hits.items():
        for hit in hits:
            needle = lexical_normalize(hit)
            start = 0
            while needle and (position := text_norm.find(needle, start)) >= 0:
                if any(abs(position - target_position) <= max_distance for target_position in target_positions):
                    close_groups.add(group_name)
                    break
                start = position + max(1, len(needle))
            if group_name in close_groups:
                break
    return close_groups


def stance_hint(text: str, config: dict[str, Any], has_harm: bool) -> tuple[str, list[str]]:
    """Return a transparent reviewer hint, never a review decision."""
    norm = lexical_normalize(text)
    markers = config.get("stance_markers", {})
    counter = matched_phrases(norm, normalized_phrases(markers.get("counter_speech", [])))
    reported = matched_phrases(norm, normalized_phrases(markers.get("reported_or_quoted", [])))
    ambiguous = matched_phrases(norm, normalized_phrases(markers.get("ambiguous", [])))
    signals: list[str] = []
    signals.extend(f"stance_counter:{value}" for value in counter)
    signals.extend(f"stance_reported:{value}" for value in reported)
    signals.extend(f"stance_ambiguous:{value}" for value in ambiguous)
    if counter:
        return "POSSIBLE_COUNTER_SPEECH", signals
    if reported:
        return "QUOTED_OR_REPORTED_ABUSE", signals
    if has_harm and (ambiguous or "?" in text):
        return "AMBIGUOUS", signals
    if has_harm:
        return "POSSIBLE_ABUSE", signals
    return "AMBIGUOUS", signals


def score_text(text: str, config: dict[str, Any]) -> dict[str, Any]:
    norm = lexical_normalize(text)
    strong = matched_phrases(norm, normalized_phrases(config["strong_abuse_signals"]))
    discovery = matched_phrases(norm, normalized_phrases(config["contextual_discovery_terms"]))
    weak = matched_target_phrases(norm, normalized_phrases(config["weak_terms"]))
    group_hits: dict[str, list[str]] = {}
    for name, phrases in config["semantic_signal_groups"].items():
        hits = matched_phrases(norm, normalized_phrases(phrases))
        if hits:
            group_hits[name] = hits

    close_groups = target_harm_proximity(norm, weak, group_hits)
    harm_hit_names = [name for name in group_hits if name in HARM_GROUPS and name in close_groups]
    support_hit_names = [name for name in group_hits if name in SUPPORT_GROUPS]
    stance, stance_signals = stance_hint(text, config, bool(strong or harm_hit_names))
    signals = [f"target:{value}" for value in weak]
    signals.extend(f"discovery:{value}" for value in discovery)
    signals.extend(f"strong:{value}" for value in strong)
    for group_name, hits in group_hits.items():
        signals.extend(f"{group_name}:{value}" for value in hits)
    signals.extend(stance_signals)
    signals.extend(f"target_harm_proximity:{name}" for name in harm_hit_names)

    if strong:
        return {
            "tier": "STRONG_LEXICAL", "score": 10 + min(5, len(strong) - 1),
            "search_term": strong[0], "signals": signals, "stance_hint": stance,
            "explicit_target": bool(weak), "meaningful_harm": True, "similarity_score": 0.0,
        }

    score = 0
    if weak:
        score += 1
    if harm_hit_names:
        score += 2 + max(0, len(harm_hit_names) - 1)
    if discovery and harm_hit_names:
        score += 1
    score += len(support_hit_names)
    if weak and harm_hit_names:
        tier = "CONTEXTUAL_SEMANTIC"
        search_term = discovery[0] if discovery else group_hits[harm_hit_names[0]][0]
    else:
        tier = "BROAD_DISCOVERY"
        search_term = discovery[0] if discovery else (weak[0] if weak else "")
    return {
        "tier": tier, "score": score, "search_term": search_term, "signals": signals,
        "stance_hint": stance, "explicit_target": bool(weak),
        "meaningful_harm": bool(harm_hit_names), "similarity_score": 0.0,
    }


def char_ngrams(text: str) -> Counter[str]:
    value = " " + normalized_for_comparison(text) + " "
    grams: Counter[str] = Counter()
    for width in (3, 4, 5):
        grams.update(value[index:index + width] for index in range(max(0, len(value) - width + 1)))
    return grams


def add_taxonomy_reference_similarity(
    candidates: list[dict[str, Any]], search_config: dict[str, Any], taxonomy_category: dict[str, Any],
) -> None:
    """Add a ranking-only score. This function never changes a retrieval tier."""
    eligible = [candidate for candidate in candidates if candidate["retrieval"]["explicit_target"]]
    if not eligible:
        return
    anchors = list(taxonomy_category["reference_examples"]) + list(search_config["strong_abuse_signals"])
    documents = [char_ngrams(candidate["record"]["original_text"]) for candidate in eligible]
    anchor_documents = [char_ngrams(anchor) for anchor in anchors]
    all_documents = documents + anchor_documents
    document_frequency: Counter[str] = Counter()
    for document in all_documents:
        document_frequency.update(document.keys())
    document_count = len(all_documents)
    inverse_document_frequency = {
        gram: math.log((document_count + 1) / (frequency + 1)) + 1
        for gram, frequency in document_frequency.items()
    }

    def vector(document: Counter[str]) -> tuple[dict[str, float], float]:
        values = {gram: (1 + math.log(count)) * inverse_document_frequency[gram] for gram, count in document.items()}
        return values, math.sqrt(sum(value * value for value in values.values()))

    def cosine(left: tuple[dict[str, float], float], right: tuple[dict[str, float], float]) -> float:
        left_values, left_magnitude = left
        right_values, right_magnitude = right
        if not left_magnitude or not right_magnitude:
            return 0.0
        if len(left_values) > len(right_values):
            left_values, right_values = right_values, left_values
        dot_product = sum(value * right_values.get(gram, 0.0) for gram, value in left_values.items())
        return dot_product / (left_magnitude * right_magnitude)

    candidate_vectors = [vector(document) for document in documents]
    anchor_vectors = [vector(document) for document in anchor_documents]
    threshold = float(search_config["taxonomy_reference_similarity"]["minimum_similarity"])
    for candidate, candidate_vector in zip(eligible, candidate_vectors):
        similarity_score = max(cosine(candidate_vector, anchor_vector) for anchor_vector in anchor_vectors)
        candidate["retrieval"]["similarity_score"] = round(similarity_score, 4)
        if similarity_score >= threshold:
            candidate["retrieval"]["signals"].append(
                f"taxonomy_reference_char_tfidf_ranking_only:{similarity_score:.4f}"
            )


def current_source_state(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {source["url"]: source for source in registry["sources"]}


def verified_provenance(record: dict[str, Any], sources: dict[str, dict[str, Any]]) -> tuple[bool, str]:
    source = sources.get(str(record.get("source_url") or ""))
    if not source:
        return False, "SOURCE_NOT_IN_REGISTRY"
    if not source.get("reachability", {}).get("reachable"):
        return False, "URL_NOT_REACHABLE"
    if not source.get("identity_verification", {}).get("verified"):
        return False, "IDENTITY_NOT_VERIFIED"
    if not record.get("source_item_id"):
        return False, "SOURCE_ITEM_ID_MISSING"
    if not record.get("original_text"):
        return False, "ORIGINAL_TEXT_MISSING"
    return True, "VERIFIED"


def provenance_label(record: dict[str, Any]) -> str:
    return (
        f"{record.get('source_name') or 'Unknown source'} | "
        f"{record.get('source_url') or 'SOURCE URL MISSING'} | "
        f"Source Item ID: {record.get('source_item_id') or 'MISSING'}"
    )


def source_identity(record: dict[str, Any], sources: dict[str, dict[str, Any]]) -> dict[str, Any]:
    source = sources.get(str(record.get("source_url") or ""), {})
    identity = source.get("identity_verification", {})
    return {
        "title": identity.get("observed_title") or record.get("source_identity_title") or "",
        "publisher": identity.get("observed_publisher") or record.get("source_identity_publisher") or "",
        "method": identity.get("method") or record.get("source_identity_method") or "",
    }


def factual_context(record: dict[str, Any], sources: dict[str, dict[str, Any]]) -> tuple[str, str]:
    identity = source_identity(record, sources)
    platform = record.get("source_platform") or "Public platform"
    title = str(identity["title"]).replace("'", "’")
    thread_context = record.get("platform_parent_context") or record.get("surrounding_context") or ""
    if platform == "YouTube":
        base = f"Public YouTube comment under video: '{title}'."
    else:
        base = f"Public {platform} item under verified source: '{title}'."
    if thread_context:
        return base + " Exact platform-returned thread context is stored separately.", str(thread_context)
    return base + " Surrounding thread context unavailable.", ""


def candidate_row(
    candidate: dict[str, Any], decision: tuple[str, str], sources: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    record = candidate["record"]
    retrieval = candidate["retrieval"]
    identity = source_identity(record, sources)
    context, thread_context = factual_context(record, sources)
    direct_url = record.get("content_url") if record.get("direct_permalink_available") else None
    return {
        "Candidate ID": candidate["candidate_id"], "Example": record["original_text"],
        "Context": context, "Platform Thread Context": thread_context,
        "Stance Hint": retrieval["stance_hint"], "Source Platform": record.get("source_platform") or "",
        "Source Name": record.get("source_name") or "", "Verified Source Title": identity["title"],
        "Verified Source Publisher": identity["publisher"], "Source URL": record.get("source_url") or "",
        "Content URL": direct_url or "", "Source Item ID": record.get("source_item_id") or "",
        "Provenance": provenance_label(record), "Retrieved At": record.get("retrieved_at") or "",
        "Source Identity Method": identity["method"], "Search Term": retrieval["search_term"],
        "Retrieval Tier": retrieval["tier"], "Retrieval Score": retrieval["score"],
        "Similarity Score": retrieval["similarity_score"],
        "Matched Signals": " || ".join(retrieval["signals"]), "Suspected Category": "GEN-1",
        "Review Status": decision[0], "Reviewer Notes": decision[1],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build precision and broad-discovery GEN-1 queues without annotating them.")
    parser.add_argument("--max-primary-per-source", type=int, default=30)
    parser.add_argument("--max-primary-total", type=int, default=200)
    parser.add_argument(
        "--include-cross-category", action="store_true",
        help="Search all existing real raw records while writing only GEN-1 artifacts.",
    )
    args = parser.parse_args()
    if args.max_primary_per_source < 1 or args.max_primary_total < 1:
        raise SystemExit("Primary queue caps must be positive")

    if CANDIDATE_PATH.exists() and not PRE_PRECISION_PATH.exists():
        shutil.copy2(CANDIDATE_PATH, PRE_PRECISION_PATH)
    if CANDIDATE_PATH.exists() and not PRE_STANCE_FIX_PATH.exists():
        shutil.copy2(CANDIDATE_PATH, PRE_STANCE_FIX_PATH)
    before_rows = read_csv(PRE_STANCE_FIX_PATH)
    before_ids = {row.get("Candidate ID", "") for row in before_rows}
    before_similarity_ids = {
        row.get("Candidate ID", "") for row in before_rows
        if row.get("Retrieval Tier") == "TAXONOMY_REFERENCE_SIMILARITY"
    }
    decisions = decision_map()
    targeted_raw_records = read_jsonl(RAW_PATH)
    raw_records = corpus_raw_records(args.include_cross_category)
    search_config = read_json(PROJECT_ROOT / "config" / "search_terms.json")["categories"]["GEN-1"]
    taxonomy = read_json(PROJECT_ROOT / "config" / "taxonomy.json")
    taxonomy_category = next(item for item in taxonomy["subcategories"] if item["code"] == "GEN-1")
    registry = read_json(PROJECT_ROOT / "config" / "sources.json")
    sources = current_source_state(registry)

    provenance_rows: list[dict[str, Any]] = []
    occurrence_rows: list[dict[str, Any]] = []
    unique: dict[str, dict[str, Any]] = {}
    filtered_counts: Counter[str] = Counter()
    provenance_failure_ids: set[str] = set()

    for record in raw_records:
        provenance_ok, provenance_state = verified_provenance(record, sources)
        identity = source_identity(record, sources)
        provenance_rows.append({
            "raw_record_id": record.get("raw_record_id"), "original_text": record.get("original_text"),
            "source_url": record.get("source_url"), "source_item_id": record.get("source_item_id"),
            "retrieved_at": record.get("retrieved_at"), "verified_source_title": identity["title"],
            "verified_source_publisher": identity["publisher"], "source_identity_method": identity["method"],
            "human_readable_provenance": provenance_label(record),
            "direct_permalink_available": bool(record.get("direct_permalink_available")),
            "content_url": record.get("content_url") if record.get("direct_permalink_available") else None,
            "current_provenance_state": provenance_state,
        })
        if not provenance_ok:
            filtered_counts[provenance_state] += 1
            provenance_failure_ids.add(str(record.get("raw_record_id")))
            occurrence_rows.append({"raw_record_id": record.get("raw_record_id"), "candidate_id": None,
                                    "disposition": f"PROVENANCE_FAILURE:{provenance_state}"})
            continue
        original = str(record.get("original_text") or "")
        norm = normalized_for_comparison(original)
        if len(norm) < 5:
            filtered_counts["TOO_SHORT"] += 1
            occurrence_rows.append({"raw_record_id": record.get("raw_record_id"), "candidate_id": None,
                                    "disposition": "FILTERED_TOO_SHORT"})
            continue
        if not looks_uzbek(original):
            filtered_counts["LANGUAGE_HEURISTIC"] += 1
            occurrence_rows.append({"raw_record_id": record.get("raw_record_id"), "candidate_id": None,
                                    "disposition": "FILTERED_LANGUAGE_HEURISTIC"})
            continue
        candidate_id = stable_candidate_id(norm)
        retrieval = score_text(original, search_config)
        existing = unique.get(norm)
        if existing is None or retrieval["score"] > existing["retrieval"]["score"]:
            unique[norm] = {"candidate_id": candidate_id, "norm": norm, "record": record,
                            "retrieval": retrieval, "occurrences": [record]}
        else:
            existing["occurrences"].append(record)

    candidates = list(unique.values())
    add_taxonomy_reference_similarity(candidates, search_config, taxonomy_category)
    candidates = sorted(candidates, key=lambda item: (
        -int(item["retrieval"]["score"]), -float(item["retrieval"]["similarity_score"]), item["candidate_id"],
    ))
    deduplicated: list[dict[str, Any]] = []
    near_duplicate_blocks: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        existing_decision = decisions.get(candidate["candidate_id"], ("PENDING", ""))[0]
        near_of = None
        if existing_decision not in DECISION_STATUSES and len(candidate["norm"]) >= 20:
            block_key = re.sub(r"\W+", "", candidate["norm"], flags=re.UNICODE)[:10]
            for prior in near_duplicate_blocks.get(block_key, []):
                if abs(len(candidate["norm"]) - len(prior["norm"])) > max(
                    20, int(max(len(candidate["norm"]), len(prior["norm"])) * 0.2)
                ):
                    continue
                if similarity(candidate["norm"], prior["norm"]) >= 0.94:
                    near_of = prior["candidate_id"]
                    break
        if near_of:
            filtered_counts["NEAR_DUPLICATE"] += 1
            for occurrence in candidate["occurrences"]:
                occurrence_rows.append({
                    "raw_record_id": occurrence.get("raw_record_id"), "candidate_id": near_of,
                    "disposition": "NEAR_DUPLICATE_OCCURRENCE", "source_url": occurrence.get("source_url"),
                    "source_item_id": occurrence.get("source_item_id"),
                })
            continue
        deduplicated.append(candidate)
        block_key = re.sub(r"\W+", "", candidate["norm"], flags=re.UNICODE)[:10]
        near_duplicate_blocks.setdefault(block_key, []).append(candidate)

    primary: list[dict[str, Any]] = []
    broad: list[dict[str, Any]] = []
    source_caps: Counter[str] = Counter()
    for candidate in deduplicated:
        candidate_id = candidate["candidate_id"]
        decision = decisions.get(candidate_id, ("PENDING", ""))
        retrieval = candidate["retrieval"]
        source_url = str(candidate["record"].get("source_url") or "")
        qualifies = (
            retrieval["tier"] in {"STRONG_LEXICAL", "CONTEXTUAL_SEMANTIC"}
            and retrieval["explicit_target"] and retrieval["meaningful_harm"]
            and retrieval["stance_hint"] in PRIMARY_STANCES
        )
        within_caps = source_caps[source_url] < args.max_primary_per_source and len(primary) < args.max_primary_total
        if qualifies and within_caps:
            primary.append(candidate_row(candidate, decision, sources))
            source_caps[source_url] += 1
            disposition = "PRIMARY_REVIEW_QUEUE"
        else:
            if qualifies:
                candidate["retrieval"] = dict(candidate["retrieval"])
                candidate["retrieval"]["tier"] = "HIGH_RELEVANCE_OVERFLOW"
            broad.append(candidate_row(candidate, decision, sources))
            disposition = candidate["retrieval"]["tier"]
        for occurrence in candidate["occurrences"]:
            occurrence_rows.append({
                "raw_record_id": occurrence.get("raw_record_id"), "candidate_id": candidate_id,
                "disposition": disposition, "source_url": occurrence.get("source_url"),
                "source_item_id": occurrence.get("source_item_id"),
            })

    write_csv(CANDIDATE_PATH, primary)
    write_csv(BROAD_PATH, broad)
    with OCCURRENCES_PATH.open("w", encoding="utf-8", newline="\n") as handle:
        for occurrence in occurrence_rows:
            handle.write(json.dumps(occurrence, ensure_ascii=False, sort_keys=True) + "\n")
    with PROVENANCE_PATH.open("w", encoding="utf-8", newline="\n") as handle:
        for provenance in provenance_rows:
            handle.write(json.dumps(provenance, ensure_ascii=False, sort_keys=True) + "\n")

    tier_counts = Counter(row["Retrieval Tier"] for row in primary)
    stance_all = Counter(
        candidate["retrieval"]["stance_hint"] for candidate in deduplicated
        if candidate["retrieval"]["meaningful_harm"]
    )
    stance_primary = Counter(row["Stance Hint"] for row in primary)
    per_source = Counter(row["Source URL"] for row in primary)
    per_source_named = {
        f"{next(row['Source Name'] for row in primary if row['Source URL'] == url)} | {url}": count
        for url, count in sorted(per_source.items())
    }
    exact_direct = sum(bool(row["Content URL"]) for row in primary)
    primary_ids = {row["Candidate ID"] for row in primary}
    broad_ids = {row["Candidate ID"] for row in broad}
    raw_id_counts = Counter(str(record.get("raw_record_id") or "") for record in targeted_raw_records)
    unique_raw_records = len([raw_id for raw_id in raw_id_counts if raw_id])
    metrics = {
        "raw_records": len(targeted_raw_records),
        "unique_raw_records": unique_raw_records,
        "duplicate_raw_record_lines": len(targeted_raw_records) - unique_raw_records,
        "corpus_records_screened": len(raw_records),
        "cross_category_search_enabled": args.include_cross_category,
        "legacy_primary_candidates_before_precision_fix": len(read_csv(PRE_PRECISION_PATH)),
        "primary_candidates_before_stance_fix": len(before_rows),
        "primary_candidates_preserved_from_before_fix": len(before_ids & primary_ids),
        "candidates_before_precision_filtering": len(deduplicated),
        "candidates_after_precision_filtering": len(primary),
        "strong_lexical_candidates": tier_counts["STRONG_LEXICAL"],
        "contextual_semantic_candidates": tier_counts["CONTEXTUAL_SEMANTIC"],
        "taxonomy_reference_similarity_primary_candidates": 0,
        "similarity_only_candidates_moved_to_broad_discovery": len(before_similarity_ids & broad_ids),
        "possible_counter_speech_candidates_all_queues": stance_all["POSSIBLE_COUNTER_SPEECH"],
        "possible_counter_speech_candidates_primary": stance_primary["POSSIBLE_COUNTER_SPEECH"],
        "quoted_or_reported_abuse_candidates_all_queues": stance_all["QUOTED_OR_REPORTED_ABUSE"],
        "ambiguous_candidates_all_queues": stance_all["AMBIGUOUS"],
        "ambiguous_candidates_primary": stance_primary["AMBIGUOUS"],
        "broad_discovery_candidates": len(broad),
        "high_relevance_overflow_candidates": sum(row["Retrieval Tier"] == "HIGH_RELEVANCE_OVERFLOW" for row in broad),
        "distinct_primary_sources": len(per_source),
        "primary_candidates_per_source_url": dict(sorted(per_source.items())),
        "primary_candidates_per_source": per_source_named,
        "candidates_with_populated_factual_context": sum(bool(row["Context"]) for row in primary),
        "candidates_with_exact_direct_permalink": exact_direct,
        "candidates_with_source_url_and_item_id_only": sum(
            bool(row["Source URL"]) and bool(row["Source Item ID"]) and not bool(row["Content URL"])
            for row in primary
        ),
        "provenance_failures": len(provenance_failure_ids),
        "new_sources_discovered_this_run": max(0, len(registry["sources"]) - INITIAL_SOURCE_COUNT),
        "new_raw_records_collected_this_run": max(0, unique_raw_records - INITIAL_RAW_UNIQUE_COUNT),
        "filtered_counts": dict(filtered_counts),
        "review_status_counts": dict(Counter(row["Review Status"] for row in primary)),
        "caps": {"max_primary_per_source": args.max_primary_per_source, "max_primary_total": args.max_primary_total},
    }
    METRICS_PATH.write_text(json.dumps(metrics, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"RAW\t{metrics['raw_records']}")
    print(f"PRIMARY_BEFORE_FIX\t{metrics['primary_candidates_before_stance_fix']}")
    print(f"PRIMARY_AFTER_FIX\t{metrics['candidates_after_precision_filtering']}")
    print(f"STRONG\t{metrics['strong_lexical_candidates']}")
    print(f"CONTEXTUAL\t{metrics['contextual_semantic_candidates']}")
    print(f"SIMILARITY_ONLY_MOVED\t{metrics['similarity_only_candidates_moved_to_broad_discovery']}")
    print(f"BROAD\t{len(broad)}")
    print(f"DISTINCT_PRIMARY_SOURCES\t{metrics['distinct_primary_sources']}")
    print(f"PROVENANCE_FAILURES\t{metrics['provenance_failures']}")


if __name__ == "__main__":
    main()
