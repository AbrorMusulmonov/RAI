"""Keep discovered URLs but stop collection from clearly irrelevant entertainment hits."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "config" / "sources.json"
REMAINING = {f"REG-{n}" for n in range(1, 5)} | {f"STA-{n}" for n in range(1, 6)} | {"REL-1", "REL-2"}
DISPOSITIONS = ROOT / "config" / "source_dispositions.private.json"


def load_private_dispositions(path: Path = DISPOSITIONS) -> tuple[set[str], dict[str, tuple[str, str]]]:
    """Keep historical source-specific decisions local, never embedded in code."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    exact = payload["exact_source_ids"]
    reassign = payload["reassign"]
    if not isinstance(exact, list) or any(not isinstance(value, str) or not value for value in exact):
        raise ValueError("Private source dispositions require a list of nonempty identifiers")
    if not isinstance(reassign, dict) or any(
        not isinstance(key, str) or not key or not isinstance(pair, list) or len(pair) != 2
        or any(not isinstance(value, str) or not value for value in pair)
        for key, pair in reassign.items()
    ):
        raise ValueError("Private source reassignment requires two category codes per identifier")
    return set(exact), {key: tuple(pair) for key, pair in reassign.items()}


def main() -> None:
    exact_source_ids, reassign = load_private_dispositions()
    markers = json.loads(DISPOSITIONS.read_text(encoding="utf-8"))["markers"]
    if not isinstance(markers, list) or any(not isinstance(value, str) or not value for value in markers):
        raise ValueError("Private source markers must be a list of nonempty strings")
    payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    changed: list[str] = []
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for source in payload.get("sources", []):
        source_id = str(source.get("source_id") or "")
        if source_id not in reassign:
            continue
        remove, add = reassign[source_id]
        categories = [value for value in (source.get("likely_taxonomy_categories") or []) if value != remove]
        if add not in categories:
            categories.append(add)
        source["likely_taxonomy_categories"] = categories
        source["source_category_correction"] = f"Verified-title audit: {remove} -> {add}"
        source["source_category_corrected_at"] = now
    for source in payload.get("sources", []):
        title = str(source.get("verified_title") or source.get("name") or "").casefold()
        categories = set(source.get("likely_taxonomy_categories") or [])
        explicitly_irrelevant = str(source.get("source_id") or "") in exact_source_ids
        if not categories.intersection(REMAINING) or not (
            explicitly_irrelevant or any(marker in title for marker in markers)
        ):
            continue
        # Never alter a source that participates in the protected GEN work.
        if any(category.startswith("GEN-") for category in categories):
            continue
        source["collection_enabled"] = False
        source["collection_status"] = "DEPRIORITIZED_IRRELEVANT_ENTERTAINMENT_TITLE"
        source["collection_status_at"] = now
        source["collection_status_evidence"] = "Verified title contains an entertainment marker unrelated to the taxonomy discussion."
        changed.append(str(source.get("source_id") or source.get("url") or ""))
    payload["last_updated"] = now
    REGISTRY.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("DEPRIORITIZED", len(changed))


if __name__ == "__main__":
    main()
