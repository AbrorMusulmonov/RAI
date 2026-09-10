"""Restore baseline source records referenced by protected GEN review queues."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "data" / "audits" / "remaining_baseline.json"
REGISTRY = ROOT / "config" / "sources.json"


def main() -> None:
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    protected = baseline.get("protected_gen_sources") or {}
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    restored = 0
    for index, source in enumerate(registry.get("sources", [])):
        url = str(source.get("url") or "")
        original = protected.get(url)
        if original is not None and source != original:
            registry["sources"][index] = original
            restored += 1
    REGISTRY.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("RESTORED_PROTECTED_GEN_SOURCES", restored)


if __name__ == "__main__":
    main()
