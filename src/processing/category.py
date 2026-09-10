from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from sklearn.feature_extraction.text import TfidfVectorizer

from src.utils.io import PROJECT_ROOT, read_json, read_jsonl
from src.utils.text import normalized_for_comparison


REVIEW_FIELDS = [
    "Candidate ID",
    "Example",
    "Context",
    "Source Platform",
    "Source Name",
    "Source URL",
    "Content URL",
    "Source Item ID",
    "Retrieval Tier",
    "Retrieval Signal",
    "Stance Hint",
    "Stance Evidence",
    "Model Retrieval Relevance",
    "Model Suggested Category",
    "Model Evidence Span",
    "Model Stance Hint",
    "Model Confidence",
    "Suggested Category",
    "Possible Compound Category",
    "Review Status",
    "Reviewer Notes",
]
CANDIDATE_FIELDS = REVIEW_FIELDS + [
    "Retrieval Score",
    "Matched Signals",
    "Provenance",
    "Verified Source Title",
    "Verified Source Publisher",
    "Retrieved At",
]
DECISION_STATUSES = {"ACCEPT", "REJECT", "UNSURE", "MOVE_TO_OTHER_CATEGORY"}
STANCE_VALUES = {
    "POSSIBLE_ABUSE",
    "POSSIBLE_COUNTER_SPEECH",
    "QUOTED_OR_REPORTED_ABUSE",
    "AMBIGUOUS",
}
DEFAULT_STANCE_MARKERS = {
    "counter_speech": [
        "bu kamsitish", "kamsitish kerak emas", "haqorat qilmang", "haqorat qilish noto'g'ri",
        "qo'shilmayman", "qarshiman", "noto'g'ri fikr", "bunday demang", "ayblamang",
        "urmaslik kerak", "urish kerak emas", "ayblamanglar", "aybi yo'q", "aybi yoq",
        "hamma narsa o'z vaqtida", "har kimni o'z vaqti", "baxtli bo'lishga haqqi bor",
        "nomusli degani", "assimilyatsiya", "камситиш", "ҳақорат қилманг", "қаршиман",
        "нотўғри фикр", "айбламанг", "урмаслик керак", "уриш керак эмас", "айби йўқ",
        "номусли дегани", "ассимиляция", "savodsiz emas", "саводсиз эмас",
    ],
    "reported_or_quoted": [
        "deb aytdi", "deb yozdi", "deyishadi", "degan gap", "deganini eshitdim", "degan", "deb",
        "dgani", "deyapti", "deganda", "deganlarga", "degandi", "deyish", "deyishga", "deyishiga", "deyiwadi", "desa", "deydi",
        "диган", "деяпти", "дейишга", "деганди", "деганда", "деганларга", "деса", "дейди", "дейиш",
        "деб айтди", "деб ёзди", "дейишади", "деган гап", "деганини эшитдим", "деган", "деб",
    ],
    "ambiguous": [
        "lekin", "ammo", "biroq", "aslida", "albatta", "iltimos", "maslahat bering",
        "mumkinmi", "bo'ladimi", "qanday", "bilmoqchiman", "men", "mening", "menda", "man",
        "лекин", "аммо", "бироқ",
        "албатта", "илтимос", "мумкинми", "қандай", "билмоқчиман", "мен", "менинг", "менда",
    ],
}


def csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def atomic_csv(path: Path, fields: list[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def atomic_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


@lru_cache(maxsize=100_000)
def lexical(text: str) -> str:
    value = normalized_for_comparison(text)
    return re.sub(r"[^\w']+", " ", value, flags=re.UNICODE).strip()


def phrase_match(text: str, phrases: Iterable[str]) -> list[str]:
    hits: list[str] = []
    for phrase in phrases:
        needle = lexical(str(phrase))
        if not needle:
            continue
        if phrase_pattern(needle).search(text):
            hits.append(str(phrase))
    return hits


@lru_cache(maxsize=20_000)
def phrase_pattern(needle: str) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w){re.escape(needle)}(?!\w)")


@lru_cache(maxsize=20_000)
def stem_pattern(needle: str) -> re.Pattern[str]:
    if " " in needle:
        return re.compile(rf"(?<!\w){re.escape(needle)}")
    return re.compile(rf"(?<!\w){re.escape(needle)}\w*")


def target_match(text: str, phrases: Iterable[str]) -> list[str]:
    """Match target stems with common Uzbek inflectional/possessive endings."""
    latin_suffixes = (
        "lar", "lari", "larni", "larga", "lardan", "ning", "ni", "ga", "da", "dan",
        "i", "im", "imiz", "ingiz", "si", "sini", "cha",
    )
    cyrillic_suffixes = (
        "лар", "лари", "ларни", "ларга", "лардан", "нинг", "ни", "га", "да", "дан",
        "и", "им", "имиз", "ингиз", "си", "сини", "ча",
    )
    hits: list[str] = []
    for phrase in phrases:
        needle = lexical(str(phrase))
        if not needle:
            continue
        if " " in needle:
            if re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", text):
                hits.append(str(phrase))
            continue
        suffixes = cyrillic_suffixes if re.search(r"[\u0400-\u04ff]", needle) else latin_suffixes
        endings = "|".join(re.escape(value) for value in sorted(suffixes, key=len, reverse=True))
        if re.search(rf"(?<!\w){re.escape(needle)}(?:{endings})?(?!\w)", text):
            hits.append(str(phrase))
    return hits


def stem_match(text: str, stems: Iterable[str]) -> list[str]:
    """Match configured word stems without rewriting the source text."""
    hits: list[str] = []
    for stem in stems:
        needle = lexical(str(stem))
        if not needle:
            continue
        if stem_pattern(needle).search(text):
            hits.append(str(stem))
    return hits


def flatten_variants(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, dict):
        return [str(item) for variants in value.values() for item in variants]
    return []


def normalized_config(raw: dict[str, Any]) -> dict[str, Any]:
    """Read the generalized schema while keeping the legacy GEN-1 bank usable."""
    strong = raw.get("strong_terms") or raw.get("strong_abuse_signals") or []
    contextual = raw.get("contextual_terms") or raw.get("contextual_discovery_terms") or raw.get("contextual") or []
    discovery = raw.get("discovery_queries") or contextual
    weak = raw.get("weak_terms") or []
    targets = raw.get("target_terms") or weak
    harms = raw.get("harm_terms") or raw.get("semantic_signal_groups") or {}
    variants = flatten_variants(raw.get("spelling_variants") or [])
    variants.extend(flatten_variants(raw.get("latin_variants") or raw.get("latin") or []))
    variants.extend(flatten_variants(raw.get("cyrillic_variants") or raw.get("cyrillic") or []))
    variants.extend(flatten_variants(raw.get("informal_variants") or []))
    standalone = raw.get("standalone_strong_terms") or []
    compounds = raw.get("compound_patterns") or {}
    return {
        "strong_terms": list(strong),
        "contextual_terms": list(contextual),
        "discovery_queries": list(discovery),
        "weak_terms": list(weak),
        "target_terms": list(targets),
        "harm_terms": dict(harms),
        "spelling_variants": variants,
        "standalone_strong_terms": list(standalone),
        "compound_patterns": dict(compounds),
        "requires_contextual_for_target_harm": bool(raw.get("requires_contextual_for_target_harm")),
        "exclusion_patterns": list(raw.get("exclusion_patterns") or []),
        "stance_markers": raw.get("stance_markers") or DEFAULT_STANCE_MARKERS,
        "retrieval_mode": str(raw.get("retrieval_mode") or "strict_v1"),
        "concept_groups": {
            str(group): list(values) for group, values in (raw.get("concept_groups") or {}).items()
        },
        "stem_groups": {
            str(group): list(values) for group, values in (raw.get("stem_groups") or {}).items()
        },
        "semantic_compositions": list(raw.get("semantic_compositions") or []),
        "semantic_anchors": list(raw.get("semantic_anchors") or []),
        "thresholds": dict(raw.get("thresholds") or {}),
        "queue_limits": dict(raw.get("queue_limits") or {}),
        "source_quality": dict(raw.get("source_quality") or {}),
        "discovery_query_passes": {
            str(name): list(values) for name, values in (raw.get("discovery_query_passes") or {}).items()
        },
    }


def stable_candidate_id(category: str, normalized_text: str) -> str:
    prefix = category.replace("-", "")
    digest = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()[:12].upper()
    return f"{prefix}-C-{digest}"


def source_verified(source: dict[str, Any] | None) -> bool:
    if not source or not source.get("public_access"):
        return False
    reachable = source.get("reachability_verified")
    if reachable is None:
        reachable = source.get("reachability", {}).get("reachable")
    identity = source.get("identity_verified")
    if identity is None:
        identity = source.get("identity_verification", {}).get("verified")
    return bool(reachable and identity)


def verified_title(source: dict[str, Any]) -> str:
    return str(
        source.get("verified_title")
        or source.get("identity_verification", {}).get("observed_title")
        or source.get("name")
        or ""
    )


def verified_publisher(source: dict[str, Any]) -> str:
    return str(
        source.get("verified_publisher")
        or source.get("identity_verification", {}).get("observed_publisher")
        or ""
    )


def stance_hint(text: str, config: dict[str, Any], has_evidence: bool) -> tuple[str, str, list[str]]:
    norm = lexical(text)
    markers = config["stance_markers"]
    counter = phrase_match(norm, markers.get("counter_speech", []))
    reported = phrase_match(norm, markers.get("reported_or_quoted", []))
    ambiguous = phrase_match(norm, markers.get("ambiguous", []))
    signals = [*(f"stance_counter:{x}" for x in counter), *(f"stance_reported:{x}" for x in reported)]
    signals.extend(f"stance_ambiguous:{x}" for x in ambiguous)
    if counter:
        hint = "POSSIBLE_COUNTER_SPEECH"
        evidence = f"Machine hint: possible counter-speech marker '{counter[0]}' occurs in the candidate text."
    elif reported or ('"' in text and has_evidence):
        hint = "QUOTED_OR_REPORTED_ABUSE"
        marker = reported[0] if reported else "quotation marks"
        evidence = f"Machine hint: possible quoted/reported marker '{marker}' occurs in the candidate text."
    elif ambiguous or ("?" in text and has_evidence):
        hint = "AMBIGUOUS"
        marker = ambiguous[0] if ambiguous else "question mark"
        evidence = f"Machine hint: ambiguity marker '{marker}' occurs in the candidate text."
    elif has_evidence:
        hint = "POSSIBLE_ABUSE"
        evidence = "Machine hint: configured target-and-harm or strong lexical evidence occurs without a configured counter/report marker."
    else:
        hint = "AMBIGUOUS"
        evidence = "Machine hint: no sufficient category-specific abuse signal was found."
    return hint, evidence, signals


def score_record(text: str, config: dict[str, Any]) -> dict[str, Any]:
    norm = lexical(text)
    strong = phrase_match(norm, config["strong_terms"])
    standalone = phrase_match(norm, config["standalone_strong_terms"])
    targets = target_match(norm, config["target_terms"])
    contextual = phrase_match(norm, config["contextual_terms"])
    weak = target_match(norm, config["weak_terms"])
    variants = phrase_match(norm, config["spelling_variants"])
    exclusions = phrase_match(norm, config["exclusion_patterns"])
    harm_hits = {
        group: phrase_match(norm, phrases)
        for group, phrases in config["harm_terms"].items()
    }
    harm_hits = {group: hits for group, hits in harm_hits.items() if hits}
    target_plus_harm = bool(targets and harm_hits)
    if config["requires_contextual_for_target_harm"]:
        target_plus_harm = bool(target_plus_harm and contextual)
    meaningful = bool(strong or standalone or target_plus_harm) and not exclusions
    hint, stance_evidence, stance_signals = stance_hint(text, config, meaningful)
    compound: list[str] = []
    for other_category, phrases in config["compound_patterns"].items():
        if phrase_match(norm, phrases):
            compound.append(other_category)
    signals = [*(f"strong:{x}" for x in strong), *(f"standalone:{x}" for x in standalone)]
    signals.extend(f"target:{x}" for x in targets)
    signals.extend(f"contextual:{x}" for x in contextual)
    signals.extend(f"weak:{x}" for x in weak)
    signals.extend(f"variant:{x}" for x in variants)
    signals.extend(f"exclusion:{x}" for x in exclusions)
    for group, hits in harm_hits.items():
        signals.extend(f"harm_{group}:{x}" for x in hits)
    signals.extend(stance_signals)
    score = 10 * len(strong) + 9 * len(standalone) + (7 if target_plus_harm else 0)
    score += min(4, len(harm_hits)) + min(2, len(contextual)) + min(1, len(variants))
    if hint == "POSSIBLE_ABUSE":
        score += 2
    if meaningful and hint == "POSSIBLE_ABUSE":
        tier = "PRIMARY"
    elif meaningful:
        tier = "SECONDARY"
    else:
        tier = "BROAD_DISCOVERY"
    if strong:
        reason = f"Strong lexical signal '{strong[0]}'"
    elif standalone:
        reason = f"Standalone category-specific abuse signal '{standalone[0]}'"
    elif target_plus_harm:
        first_group = next(iter(harm_hits))
        reason = f"Target '{targets[0]}' plus {first_group} harm signal '{harm_hits[first_group][0]}'"
    else:
        reason = "Topic/discovery relevance only; excluded from the human-review queue"
    if contextual:
        reason += f"; contextual term '{contextual[0]}'"
    return {
        "tier": tier,
        "score": score,
        "signals": signals,
        "reason": reason,
        "stance_hint": hint,
        "stance_evidence": stance_evidence,
        "compound": "; ".join(sorted(set(compound))),
        "model_relevance": min(0.99, score / 20.0),
        "model_evidence_span": evidence_span(text, [*strong, *standalone, *targets]),
        "stage_a": meaningful,
    }


def evidence_span(text: str, signals: Iterable[str], maximum: int = 220) -> str:
    """Return only a short, verbatim span from the retrieved comment."""
    if not text:
        return ""
    folded = text.casefold()
    located: list[int] = []
    for signal in signals:
        tokens = [token for token in lexical(str(signal)).split() if len(token) >= 3]
        for token in tokens:
            index = folded.find(token.casefold())
            if index >= 0:
                located.append(index)
                break
    center = min(located) if located else 0
    start = max(0, center - maximum // 4)
    end = min(len(text), start + maximum)
    span = text[start:end].strip()
    if start > 0:
        span = "…" + span
    if end < len(text):
        span += "…"
    return span


def semantic_similarity_map(
    normalized_texts: list[str], anchors: list[str],
) -> dict[str, float]:
    """Character n-gram semantic support for ranking; texts remain unchanged."""
    clean_anchors = [lexical(value) for value in anchors if lexical(value)]
    if not normalized_texts or not clean_anchors:
        return {text: 0.0 for text in normalized_texts}
    documents = normalized_texts + clean_anchors
    vectorizer = TfidfVectorizer(
        analyzer="char_wb", ngram_range=(3, 5), min_df=1, sublinear_tf=True,
        max_features=250_000,
    )
    matrix = vectorizer.fit_transform(documents)
    text_matrix = matrix[:len(normalized_texts)]
    anchor_matrix = matrix[len(normalized_texts):]
    similarities = text_matrix @ anchor_matrix.T
    result: dict[str, float] = {}
    for index, text in enumerate(normalized_texts):
        row = similarities.getrow(index)
        result[text] = round(float(row.max()) if row.nnz else 0.0, 4)
    return result


def high_recall_score_record(
    text: str,
    config: dict[str, Any],
    similarity: float,
    source_topic_relevant: bool,
) -> dict[str, Any]:
    """Two-stage retrieval: broad semantic recall followed by transparent ranking."""
    norm = lexical(text)
    strong = phrase_match(norm, config["strong_terms"])
    standalone = phrase_match(norm, config["standalone_strong_terms"])
    exclusions = phrase_match(norm, config["exclusion_patterns"])
    group_hits: dict[str, list[str]] = {}
    for group, phrases in config["concept_groups"].items():
        hits = phrase_match(norm, phrases)
        hits.extend(stem_match(norm, config["stem_groups"].get(group, [])))
        if hits:
            group_hits[group] = list(dict.fromkeys(hits))

    matched_compositions: list[dict[str, Any]] = []
    for composition in config["semantic_compositions"]:
        groups = [str(group) for group in composition.get("groups") or []]
        any_groups = [str(group) for group in composition.get("any_groups") or []]
        if groups and not all(group in group_hits for group in groups):
            continue
        if any_groups and not any(group in group_hits for group in any_groups):
            continue
        matched_compositions.append(composition)

    thresholds = config["thresholds"]
    semantic_stage_a = float(thresholds.get("semantic_stage_a", 0.12))
    secondary_threshold = float(thresholds.get("secondary", 0.40))
    primary_threshold = float(thresholds.get("primary", 0.70))
    semantic_review_threshold = float(thresholds.get("semantic_review", 0.22))
    target_groups = set(thresholds.get("target_groups") or ["target"])
    has_target = any(group in group_hits for group in target_groups)
    non_target_groups = [group for group in group_hits if group not in target_groups]

    base = 0.0
    if strong:
        base = max(base, 0.92)
    if standalone:
        base = max(base, 0.94)
    if matched_compositions:
        base = max(base, max(float(item.get("weight") or 0.0) for item in matched_compositions))
    if has_target and non_target_groups:
        base = max(base, 0.36 + min(0.16, 0.04 * len(non_target_groups)))
    if has_target and similarity >= semantic_stage_a:
        normalized_similarity = min(1.0, similarity / max(semantic_stage_a * 3.0, 0.01))
        base = max(base, 0.30 + 0.34 * normalized_similarity)

    supporting_groups = max(0, len(group_hits) - 2)
    relevance = base + min(0.09, 0.025 * supporting_groups)
    relevance += min(0.06, 0.18 * similarity)
    if source_topic_relevant:
        relevance += 0.025
    if exclusions:
        relevance = 0.0
    relevance = round(min(0.99, relevance), 4)

    stage_a = bool(
        not exclusions
        and (
            strong
            or standalone
            or matched_compositions
            or (has_target and len(non_target_groups) >= int(thresholds.get("minimum_non_target_groups", 1)))
            or (has_target and similarity >= semantic_stage_a)
        )
    )
    maximum_composition_weight = max(
        (float(item.get("weight") or 0.0) for item in matched_compositions),
        default=0.0,
    )
    review_signal_groups = set(thresholds.get("review_signal_groups") or [])
    required_review_groups = set(thresholds.get("required_review_groups") or [])
    has_review_group = bool(review_signal_groups.intersection(group_hits))
    has_required_review_context = bool(
        not required_review_groups or required_review_groups.intersection(group_hits)
    )
    composition_review = maximum_composition_weight >= secondary_threshold
    semantic_review = bool(
        has_target
        and non_target_groups
        and similarity >= semantic_review_threshold
        and (not review_signal_groups or has_review_group)
    )
    review_eligible = bool(
        strong
        or standalone
        or (
            has_required_review_context
            and (
                composition_review
                or (has_target and has_review_group)
                or semantic_review
            )
        )
    )
    hint, stance_evidence, stance_signals = stance_hint(text, config, stage_a)
    primary_evidence = bool(
        strong
        or standalone
        or maximum_composition_weight >= primary_threshold
        or (has_target and len(review_signal_groups.intersection(group_hits)) >= 2)
    )
    strong_ambiguous_primary = bool(
        bool(thresholds.get("allow_ambiguous_primary", True))
        and
        hint in {"AMBIGUOUS", "QUOTED_OR_REPORTED_ABUSE"}
        and (
            strong
            or standalone
            or maximum_composition_weight >= min(0.95, primary_threshold + 0.06)
        )
    )
    primary_stance = hint == "POSSIBLE_ABUSE" or strong_ambiguous_primary
    if stage_a and review_eligible and primary_evidence and relevance >= primary_threshold and primary_stance:
        tier = "PRIMARY"
    elif stage_a and review_eligible and relevance >= secondary_threshold:
        tier = "SECONDARY"
    elif stage_a:
        tier = "BROAD_DISCOVERY"
    else:
        tier = "EXCLUDED_HIGH_SCORE"
    if hint == "POSSIBLE_COUNTER_SPEECH" and thresholds.get("exclude_counter_speech_from_review"):
        tier = "BROAD_DISCOVERY" if stage_a else "EXCLUDED_HIGH_SCORE"

    signal_terms: list[str] = [*strong, *standalone]
    for hits in group_hits.values():
        signal_terms.extend(hits)
    composition_names = [str(item.get("name") or "composition") for item in matched_compositions]
    signals = [*(f"strong:{item}" for item in strong), *(f"standalone:{item}" for item in standalone)]
    for group, hits in group_hits.items():
        signals.extend(f"concept_{group}:{item}" for item in hits)
    signals.extend(f"composition:{name}" for name in composition_names)
    signals.extend(stance_signals)
    if strong:
        reason = f"Strong lexical signal '{strong[0]}'"
    elif standalone:
        reason = f"Standalone category signal '{standalone[0]}'"
    elif composition_names:
        reason = "Semantic composition " + ", ".join(composition_names[:3])
    elif group_hits:
        reason = "Concept groups " + ", ".join(sorted(group_hits))
    else:
        reason = "Semantic similarity support"
    reason += f"; local semantic similarity {similarity:.4f}; relevance {relevance:.4f}"
    if source_topic_relevant:
        reason += "; verified source topic used as ranking support only"

    compound: list[str] = []
    for other_category, phrases in config["compound_patterns"].items():
        if phrase_match(norm, phrases) or stem_match(norm, phrases):
            compound.append(other_category)
    return {
        "tier": tier,
        "score": round(relevance * 100, 2),
        "signals": signals,
        "reason": reason,
        "stance_hint": hint,
        "stance_evidence": stance_evidence,
        "compound": "; ".join(sorted(set(compound))),
        "model_relevance": relevance,
        "model_evidence_span": evidence_span(text, signal_terms),
        "stage_a": stage_a,
        "group_hits": group_hits,
        "similarity": similarity,
        "semantic_recall": True,
    }


def taxonomy_similarity(text: str, anchors: list[str]) -> float:
    """Transparent ranking support only; never changes queue eligibility."""
    def grams(value: str) -> Counter[str]:
        value = f" {lexical(value)} "
        result: Counter[str] = Counter()
        for width in (3, 4, 5):
            result.update(value[i:i + width] for i in range(max(0, len(value) - width + 1)))
        return result

    left = grams(text)
    if not left:
        return 0.0
    best = 0.0
    for anchor in anchors:
        right = grams(anchor)
        shared = set(left) & set(right)
        numerator = sum(left[g] * right[g] for g in shared)
        denominator = math.sqrt(sum(v * v for v in left.values()) * sum(v * v for v in right.values()))
        if denominator:
            best = max(best, numerator / denominator)
    return round(best, 4)


def decision_map(category: str) -> dict[str, tuple[str, str]]:
    paths = [
        PROJECT_ROOT / "data" / "reviewed" / f"{category}.review_queue.csv",
        PROJECT_ROOT / "data" / "reviewed" / f"{category}.csv",
        PROJECT_ROOT / "data" / "rejected" / f"{category}.csv",
    ]
    decisions: dict[str, tuple[str, str]] = {}
    for path in paths:
        for row in csv_rows(path):
            candidate_id = row.get("Candidate ID") or ""
            status = (row.get("Review Status") or "PENDING").strip()
            if candidate_id and status in DECISION_STATUSES:
                decisions[candidate_id] = (status, row.get("Reviewer Notes") or "")
    return decisions


@lru_cache(maxsize=64)
def baseline_candidate_ids(category: str) -> frozenset[str]:
    """Keep pre-resume PENDING IDs traceable even when precision rules change."""
    path = PROJECT_ROOT / "data" / "audits" / "remaining_baseline.json"
    if not path.exists():
        return frozenset()
    baseline = read_json(path)
    values = baseline.get("queues", {}).get(category, {}).get("candidate_ids") or []
    return frozenset(str(value) for value in values if value)


def raw_records(category: str, include_cross_category: bool = True) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    targeted: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    paths = (
        (PROJECT_ROOT / "data" / "raw").rglob("*.jsonl")
        if include_cross_category
        else (PROJECT_ROOT / "data" / "raw").rglob(f"{category}.jsonl")
    )
    for path in paths:
        if path.name.endswith(".provenance.jsonl"):
            continue
        path_records = read_jsonl(path)
        if path.name == f"{category}.jsonl":
            targeted.extend(path_records)
        records.extend(path_records)
    # Shared sources can be stored in several category raw files. Screen each
    # exact platform record once while retaining category-targeted volume above.
    unique: dict[str, dict[str, Any]] = {}
    for record in records:
        key = str(record.get("raw_record_id") or "")
        if not key:
            key = "MISSING-" + hashlib.sha256(
                (str(record.get("source_url")) + "\u241f" + str(record.get("source_item_id")) + "\u241f" + str(record.get("original_text"))).encode("utf-8")
            ).hexdigest()
        unique.setdefault(key, record)
    return targeted, list(unique.values())


def factual_context(record: dict[str, Any], source: dict[str, Any]) -> str:
    parent = record.get("platform_parent_context") or record.get("surrounding_context")
    if parent:
        return f"Retrieved parent/thread context: {parent}"
    title = verified_title(source)
    platform = record.get("source_platform") or source.get("platform") or "Public source"
    if platform == "YouTube":
        return f"Public YouTube comment under video: {title}. Surrounding thread context unavailable."
    return f"Public {platform} item under source: {title}. Surrounding thread context unavailable."


def build_row(
    category: str,
    record: dict[str, Any],
    source: dict[str, Any],
    retrieval: dict[str, Any],
    candidate_id: str,
    status: str,
    notes: str,
    similarity_score: float,
) -> dict[str, Any]:
    provenance = record.get("human_readable_provenance") or (
        f"{source.get('name', '')} | {source.get('url', '')} | Source Item ID: {record.get('source_item_id', '')}"
    )
    signal = retrieval["reason"]
    if not retrieval.get("semantic_recall"):
        signal += f"; taxonomy-reference similarity {similarity_score:.4f} is ranking-only."
    return {
        "Candidate ID": candidate_id,
        "Example": record.get("original_text") or "",
        "Context": factual_context(record, source),
        "Source Platform": record.get("source_platform") or source.get("platform") or "",
        "Source Name": source.get("name") or record.get("source_name") or "",
        "Source URL": source.get("url") or record.get("source_url") or "",
        "Content URL": record.get("content_url") or "",
        "Source Item ID": str(record.get("source_item_id") or ""),
        "Retrieval Tier": retrieval["tier"],
        "Retrieval Signal": signal,
        "Stance Hint": retrieval["stance_hint"],
        "Stance Evidence": retrieval["stance_evidence"],
        "Model Retrieval Relevance": f"{float(retrieval.get('model_relevance') or 0.0):.4f}",
        "Model Suggested Category": category,
        "Model Evidence Span": retrieval.get("model_evidence_span") or "",
        "Model Stance Hint": retrieval["stance_hint"],
        "Model Confidence": f"{float(retrieval.get('model_relevance') or 0.0):.4f}",
        "Suggested Category": category,
        "Possible Compound Category": retrieval["compound"],
        "Review Status": status,
        "Reviewer Notes": notes,
        "Retrieval Score": retrieval["score"],
        "Matched Signals": " || ".join(retrieval["signals"]),
        "Provenance": provenance,
        "Verified Source Title": verified_title(source),
        "Verified Source Publisher": verified_publisher(source),
        "Retrieved At": record.get("retrieved_at") or "",
    }


def select_with_source_cap(rows: list[dict[str, Any]], limit: int, per_source: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for row in sorted(rows, key=lambda r: (-float(r["Retrieval Score"]), r["Candidate ID"])):
        source = str(row["Source URL"])
        if counts[source] >= per_source:
            continue
        selected.append(row)
        counts[source] += 1
        if len(selected) >= limit:
            break
    return selected


def near_deduplicate(
    rows: list[dict[str, Any]], threshold: float = 0.96,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Collapse conservative near-copies while never discarding human decisions."""
    ordered = sorted(
        rows,
        key=lambda row: (
            row.get("Review Status") == "PENDING",
            -float(row.get("Retrieval Score") or 0),
            str(row.get("Candidate ID") or ""),
        ),
    )
    kept: list[dict[str, Any]] = []
    # SequenceMatcher is quadratic in both the number and length of strings.
    # Block comparisons by first token and a coarse length band so an expanded
    # high-recall queue does not turn this conservative cleanup into an O(n^2)
    # corpus-wide operation. Exact copies were already grouped above.
    blocks: dict[tuple[str, int], list[tuple[dict[str, Any], str]]] = defaultdict(list)
    remap: dict[str, str] = {}
    for row in ordered:
        normalized_text = lexical(str(row.get("Example") or ""))
        # Very short insults are semantically sensitive to one-token changes.
        # Exact copies have already been grouped, so retain short variants.
        if row.get("Review Status") != "PENDING" or len(normalized_text) < 24:
            kept.append(row)
            continue
        first_token = normalized_text.split(" ", 1)[0]
        length_band = len(normalized_text) // 12
        duplicate_of = None
        comparison_pool: list[tuple[dict[str, Any], str]] = []
        for adjacent_band in (length_band - 1, length_band, length_band + 1):
            comparison_pool.extend(blocks.get((first_token, adjacent_band), []))
        for existing, other in comparison_pool:
            length_ratio = min(len(normalized_text), len(other)) / max(len(normalized_text), len(other))
            if length_ratio < threshold:
                continue
            if SequenceMatcher(None, normalized_text, other, autojunk=False).ratio() >= threshold:
                duplicate_of = str(existing.get("Candidate ID") or "")
                break
        if duplicate_of:
            remap[str(row.get("Candidate ID") or "")] = duplicate_of
        else:
            kept.append(row)
            blocks[(first_token, length_band)].append((row, normalized_text))
    return kept, remap


def process_category(
    category: str,
    primary_limit: int = 150,
    secondary_limit: int = 200,
    per_source_limit: int = 75,
    include_cross_category: bool = True,
) -> dict[str, Any]:
    if category == "GEN-1":
        raise ValueError("GEN-1 is protected; use its existing dedicated processor only when explicitly required.")
    taxonomy = read_json(PROJECT_ROOT / "config" / "taxonomy.json")
    taxonomy_entry = next((item for item in taxonomy["subcategories"] if item["code"] == category), None)
    if not taxonomy_entry:
        raise ValueError(f"Unknown taxonomy category: {category}")
    search_banks = read_json(PROJECT_ROOT / "config" / "search_terms.json")["categories"]
    if category not in search_banks:
        raise ValueError(f"No search-term bank for {category}")
    config = normalized_config(search_banks[category])
    registry = read_json(PROJECT_ROOT / "config" / "sources.json")
    sources = {str(source.get("url")): source for source in registry["sources"]}
    decisions = decision_map(category)
    protected_pending_ids = baseline_candidate_ids(category)
    targeted_records, records = raw_records(category, include_cross_category=include_cross_category)
    by_text: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        text = str(record.get("original_text") or "").strip()
        if text:
            by_text[lexical(text)].append(record)

    all_rows: list[dict[str, Any]] = []
    broad_rows: list[dict[str, Any]] = []
    excluded_rows: list[dict[str, Any]] = []
    occurrences: list[dict[str, Any]] = []
    provenance_failures: Counter[str] = Counter()
    high_recall = config["retrieval_mode"] == "high_recall_v2"
    anchors = (
        list(taxonomy_entry.get("reference_examples") or [])
        + config["strong_terms"]
        + config["semantic_anchors"]
    )
    similarity_by_text = (
        semantic_similarity_map(list(sorted(by_text)), anchors)
        if high_recall
        else {}
    )
    stage_a_count = 0
    for norm, grouped_records in sorted(by_text.items()):
        record = grouped_records[0]
        source = sources.get(str(record.get("source_url") or ""))
        source_topic_relevant = bool(
            source and category in (source.get("likely_taxonomy_categories") or [])
        )
        retrieval = (
            high_recall_score_record(
                str(record.get("original_text") or ""),
                config,
                similarity_by_text.get(norm, 0.0),
                source_topic_relevant,
            )
            if high_recall
            else score_record(str(record.get("original_text") or ""), config)
        )
        if retrieval.get("stage_a"):
            stage_a_count += 1
        candidate_id = stable_candidate_id(category, norm)
        retained_baseline_pending = candidate_id in protected_pending_ids
        verified = source_verified(source)
        candidate_considered = bool(
            retained_baseline_pending
            or retrieval.get("stage_a")
            or float(retrieval.get("model_relevance") or 0.0)
            >= float(config["thresholds"].get("excluded_audit_floor", 0.20))
        )
        if candidate_considered:
            if not source:
                provenance_failures["SOURCE_NOT_IN_REGISTRY"] += 1
            elif not verified:
                provenance_failures["SOURCE_UNVERIFIED"] += 1
            elif not record.get("source_item_id"):
                provenance_failures["SOURCE_ITEM_ID_MISSING"] += 1
            elif not record.get("original_text"):
                provenance_failures["TEXT_MISSING"] += 1
        valid_provenance = bool(source and verified and record.get("source_item_id") and record.get("original_text"))
        similarity_score = (
            similarity_by_text.get(norm, 0.0)
            if high_recall
            else (
                taxonomy_similarity(str(record.get("original_text") or ""), anchors)
                if retrieval["tier"] in {"PRIMARY", "SECONDARY"}
                else 0.0
            )
        )
        status, notes = decisions.get(candidate_id, ("PENDING", ""))
        if source:
            row = build_row(category, record, source, retrieval, candidate_id, status, notes, similarity_score)
            if status in DECISION_STATUSES and valid_provenance and retrieval["tier"] not in {"PRIMARY", "SECONDARY"}:
                row["Retrieval Tier"] = "SECONDARY"
                row["Retrieval Signal"] += "; retained because a human decision already exists"
                all_rows.append(row)
            elif retained_baseline_pending and valid_provenance and retrieval["tier"] not in {"PRIMARY", "SECONDARY"}:
                row["Retrieval Tier"] = "BROAD_DISCOVERY"
                row["Retrieval Signal"] += "; retained from the pre-resume PENDING queue for Candidate-ID traceability"
                broad_rows.append(row)
            elif retrieval["tier"] in {"PRIMARY", "SECONDARY"} and valid_provenance:
                all_rows.append(row)
            elif retrieval.get("stage_a") and valid_provenance:
                row["Retrieval Tier"] = "BROAD_DISCOVERY"
                broad_rows.append(row)
            elif candidate_considered and valid_provenance:
                row["Retrieval Tier"] = "EXCLUDED_HIGH_SCORE"
                excluded_rows.append(row)
        for occurrence in grouped_records:
            occurrences.append({
                "candidate_id": candidate_id if candidate_considered and valid_provenance else None,
                "raw_record_id": occurrence.get("raw_record_id"),
                "source_url": occurrence.get("source_url"),
                "source_item_id": occurrence.get("source_item_id"),
                "disposition": retrieval["tier"] if valid_provenance else "SOURCE_UNVERIFIED",
            })

    all_rows, near_duplicate_remap = near_deduplicate(all_rows)
    if near_duplicate_remap:
        for occurrence in occurrences:
            candidate_id = occurrence.get("candidate_id")
            if candidate_id in near_duplicate_remap:
                occurrence["candidate_id"] = near_duplicate_remap[candidate_id]
                occurrence["disposition"] = "NEAR_DUPLICATE_OCCURRENCE"
    primary_pool = [row for row in all_rows if row["Retrieval Tier"] == "PRIMARY"]
    secondary_pool = [row for row in all_rows if row["Retrieval Tier"] == "SECONDARY"]
    queue_limits = config["queue_limits"] if high_recall else {}
    effective_primary_limit = min(primary_limit, int(queue_limits.get("primary") or primary_limit))
    effective_secondary_limit = min(secondary_limit, int(queue_limits.get("secondary") or secondary_limit))
    effective_source_limit = min(per_source_limit, int(queue_limits.get("per_source") or per_source_limit))
    combined_limit = int(queue_limits.get("combined") or (effective_primary_limit + effective_secondary_limit))
    primary = select_with_source_cap(primary_pool, effective_primary_limit, effective_source_limit)
    secondary_room = max(0, combined_limit - len(primary))
    secondary = select_with_source_cap(
        secondary_pool, min(effective_secondary_limit, secondary_room), effective_source_limit,
    )
    selected_ids = {row["Candidate ID"] for row in primary + secondary}
    overflow = [row for row in all_rows if row["Candidate ID"] not in selected_ids]
    for row in overflow:
        row["Retrieval Tier"] = "BROAD_DISCOVERY"
    broad_rows.extend(overflow)
    broad_limit = int(queue_limits.get("broad") or len(broad_rows))
    excluded_limit = int(queue_limits.get("excluded_audit") or 200)
    # A capped broad artifact must still retain IDs that existed in the
    # pre-resume queue. They are traceability records, not review promotion.
    protected_broad = [row for row in broad_rows if row.get("Candidate ID") in protected_pending_ids]
    protected_broad_ids = {row.get("Candidate ID") for row in protected_broad}
    ordinary_broad = [row for row in broad_rows if row.get("Candidate ID") not in protected_broad_ids]
    selected_broad = select_with_source_cap(
        ordinary_broad,
        max(0, broad_limit - len(protected_broad)),
        max(effective_source_limit, int(queue_limits.get("broad_per_source") or 40)),
    )
    broad_rows = sorted(
        protected_broad + selected_broad,
        key=lambda row: (-float(row.get("Retrieval Score") or 0), str(row.get("Candidate ID") or "")),
    )
    excluded_rows = select_with_source_cap(
        excluded_rows, excluded_limit, int(queue_limits.get("excluded_per_source") or 25),
    )
    review = primary + secondary

    candidate_dir = PROJECT_ROOT / "data" / "candidates"
    review_dir = PROJECT_ROOT / "data" / "reviewed"
    atomic_csv(candidate_dir / f"{category}.csv", CANDIDATE_FIELDS, primary)
    atomic_csv(candidate_dir / f"{category}.secondary_review.csv", CANDIDATE_FIELDS, secondary)
    atomic_csv(candidate_dir / f"{category}.broad_discovery.csv", CANDIDATE_FIELDS, broad_rows)
    atomic_csv(candidate_dir / f"{category}.excluded_high_score.csv", CANDIDATE_FIELDS, excluded_rows)
    atomic_csv(review_dir / f"{category}.review_queue.csv", REVIEW_FIELDS, review)
    atomic_jsonl(candidate_dir / f"{category}.occurrences.jsonl", occurrences)

    per_source = Counter(row["Source URL"] for row in review)
    metrics = {
        "category": category,
        "raw_records": len(targeted_records),
        "unique_raw_records": len({str(record.get('raw_record_id') or '') for record in targeted_records if record.get('raw_record_id')}),
        "screened_corpus_records": len(records),
        "screened_unique_texts": len(by_text),
        "unique_corpus_matches_considered": stage_a_count,
        "near_duplicate_candidates_collapsed": len(near_duplicate_remap),
        "primary_candidates": len(primary),
        "secondary_candidates": len(secondary),
        "combined_review_candidates": len(review),
        "broad_discovery_records": len(broad_rows),
        "excluded_high_score_records": len(excluded_rows),
        "distinct_sources": len(per_source),
        "candidates_per_source": dict(sorted(per_source.items())),
        "verified_provenance": len(review),
        "unverified_provenance": sum(provenance_failures.values()),
        "provenance_failures": dict(provenance_failures),
        "direct_permalink_count": sum(bool(row["Content URL"]) for row in review),
        "source_url_plus_item_id_count": sum(
            bool(row["Source URL"]) and bool(row["Source Item ID"]) and not bool(row["Content URL"])
            for row in review
        ),
        "review_status_counts": dict(Counter(row["Review Status"] for row in review)),
        "stance_counts": dict(Counter(row["Stance Hint"] for row in review)),
        "compound_hint_counts": dict(Counter(row["Possible Compound Category"] for row in review if row["Possible Compound Category"])),
        "largest_source_share": round(max(per_source.values(), default=0) / len(review), 4) if review else 0.0,
        "platform_distribution": dict(Counter(row["Source Platform"] for row in review)),
        "retrieval_mode": config["retrieval_mode"],
        "thresholds": config["thresholds"],
        "limits": {
            "primary": effective_primary_limit,
            "secondary": effective_secondary_limit,
            "combined": combined_limit,
            "per_source": effective_source_limit,
        },
    }
    metrics_path = candidate_dir / f"{category}.metrics.json"
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate category-aware primary, secondary, broad, and human-review queues.")
    parser.add_argument("categories", nargs="+", help="Taxonomy codes, excluding protected GEN-1")
    parser.add_argument("--primary-limit", type=int, default=150)
    parser.add_argument("--secondary-limit", type=int, default=200)
    parser.add_argument("--per-source-limit", type=int, default=75)
    parser.add_argument("--no-cross-category", action="store_true", help="Screen only raw files collected for each category")
    args = parser.parse_args()
    for category in (value.upper() for value in args.categories):
        metrics = process_category(
            category,
            args.primary_limit,
            args.secondary_limit,
            args.per_source_limit,
            include_cross_category=not args.no_cross_category,
        )
        print(
            f"{category}\tRAW={metrics['raw_records']}\tUNIQUE={metrics['unique_raw_records']}"
            f"\tPRIMARY={metrics['primary_candidates']}\tSECONDARY={metrics['secondary_candidates']}"
            f"\tREVIEW={metrics['combined_review_candidates']}\tSOURCES={metrics['distinct_sources']}"
        )


if __name__ == "__main__":
    main()
