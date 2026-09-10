"""Upgrade only REG/STA/REL retrieval banks to the transparent high-recall schema."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "config" / "search_terms.json"


def uniq(*parts: list[str]) -> list[str]:
    return list(dict.fromkeys(value for part in parts for value in part if value))


SPEC_PATH = ROOT / "config" / "remaining_retrieval.private.json"


def load_private_specs(path: Path = SPEC_PATH) -> tuple[dict, dict]:
    """Load observed phrase banks and source-quality rules from local-only input."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    quality, specs = payload["common_quality"], payload["specs"]
    if not isinstance(quality, dict) or not isinstance(specs, dict):
        raise ValueError("Private retrieval specifications must be objects")
    return quality, specs


def apply_spec(code: str, base: dict, spec: dict, common_quality: dict | None = None) -> None:
    if common_quality is None:
        common_quality, _ = load_private_specs()
    base["retrieval_mode"] = "high_recall_v2"
    base["strong_terms"] = uniq(base.get("strong_terms", []), spec.get("strong", []))
    if code == "REG-1":
        base["strong_terms"] = [
            term for term in base["strong_terms"]
            if term.casefold() not in {"qishloqi", "qiwloqi", "kishloki", "қишлоқи"}
        ]
    if code == "STA-3":
        base["strong_terms"] = [term for term in base["strong_terms"] if term.casefold() not in {"ahmoq", "аҳмоқ"}]
    if code == "REG-3":
        bare_language_ambiguous = {"mankurt", "manqurt", "манқурт"}
        base["strong_terms"] = [
            term for term in base["strong_terms"] if term.casefold() not in bare_language_ambiguous
        ]
    if code == "STA-5":
        generic_practice_phrases = {"o'qimagan odam", "ўқимаган одам"}
        base["strong_terms"] = [
            term for term in base["strong_terms"] if term.casefold() not in generic_practice_phrases
        ]
    if code == "REL-1":
        bare_labels = {"vahhobiy", "vahobiy", "vaxobiy", "aqidaparast", "ваҳҳобий", "ақидапараст"}
        base["strong_terms"] = [term for term in base["strong_terms"] if term.casefold() not in bare_labels]
    base["standalone_strong_terms"] = uniq(base.get("standalone_strong_terms", []), spec.get("standalone", []))
    if code == "REG-3":
        base["standalone_strong_terms"] = [
            term for term in base["standalone_strong_terms"] if term.casefold() not in bare_language_ambiguous
        ]
    if code == "REL-1":
        base["standalone_strong_terms"] = [term for term in base["standalone_strong_terms"] if term.casefold() not in bare_labels]
    if code == "REL-2":
        bare_condemnations = {"kofir", "dahriy", "murtad", "gumroh", "bidatchi", "bid'atchi", "кофир", "даҳрий", "муртад", "гумроҳ", "бидъатчи"}
        base["strong_terms"] = [term for term in base["strong_terms"] if term.casefold() not in bare_condemnations]
        base["standalone_strong_terms"] = [term for term in base["standalone_strong_terms"] if term.casefold() not in bare_condemnations]
    legacy_harm = uniq(*[list(values) for values in (base.get("harm_terms") or {}).values()])
    base["concept_groups"] = dict(spec["groups"])
    base["stem_groups"] = dict(spec["stems"])
    if legacy_harm:
        base["concept_groups"]["legacy_harm"] = legacy_harm
        base["stem_groups"]["legacy_harm"] = []
    base["semantic_compositions"] = [
        {"name": name, "groups": groups, "weight": weight}
        for name, groups, weight in spec["compositions"]
    ]
    base["semantic_anchors"] = spec["anchors"]
    base["observed_real_world_phrases"] = spec["observed"]
    base["discovery_query_passes"] = spec["queries"]
    base["discovery_queries"] = uniq(base.get("discovery_queries", []), *spec["queries"].values())
    base["exclusion_patterns"] = uniq(base.get("exclusion_patterns", []), spec.get("exclusions", []))
    base["thresholds"] = {
        "semantic_stage_a": 0.08,
        "semantic_review": 0.20,
        "secondary": 0.42,
        "primary": 0.72,
        "minimum_non_target_groups": 1,
        "target_groups": spec["targets"],
        "review_signal_groups": uniq(spec["review"], ["legacy_harm"] if legacy_harm else []),
        "required_review_groups": spec["required"],
        "excluded_audit_floor": 0.20,
        "allow_ambiguous_primary": False,
    }
    base["queue_limits"] = {
        "primary": 80, "secondary": 120, "combined": 200, "per_source": 30,
        "broad": 300, "broad_per_source": 40, "excluded_audit": 200,
        "excluded_per_source": 25,
    }
    base["source_quality"] = common_quality


def main() -> None:
    common_quality, specs = load_private_specs()
    payload = json.loads(PATH.read_text(encoding="utf-8"))
    categories = payload["categories"]
    missing = sorted(set(specs) - set(categories))
    if missing:
        raise SystemExit(f"Missing taxonomy search banks: {missing}")
    for code, spec in specs.items():
        apply_spec(code, categories[code], spec, common_quality)
    PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("UPDATED", ", ".join(specs))


if __name__ == "__main__":
    main()
