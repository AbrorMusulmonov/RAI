"""Audit actual Git index/commit bytes without printing private matched values.

Portable checks reject concrete platform links and reconstructable identifiers.
The optional private-evidence comparison requires the original local research
workspace. It is a heuristic safeguard, not legal clearance or a proof that
arbitrary transformed/short text cannot reveal information.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
from collections import Counter
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse


ROOT = Path(__file__).resolve().parents[1]
# A coincidental channel name must not make ordinary method documentation
# unpublishable. This exception is vocabulary, not a source allowlist.
GENERIC_METADATA_WORDS = {"artifact"}
PLATFORM_PATTERNS = {
    "concrete_video_link": re.compile(
        r"(?:youtube\.com/(?:watch\?[^\s\"'<>]*?v=|shorts/|live/|embed/)|youtu\.be/)"
        r"[A-Za-z0-9_-]+", re.I
    ),
    "concrete_channel_link": re.compile(r"youtube\.com/(?:@|channel/|c/|user/)[A-Za-z0-9_-]+", re.I),
    "concrete_messaging_link": re.compile(r"(?:t\.me|telegram\.me)/(?:s/)?[A-Za-z0-9_+]+", re.I),
    "platform_comment_id": re.compile(r"\bUg[wxz][A-Za-z0-9_-]{15,}\b"),
    "reconstructable_video_id": re.compile(r"\bYT-[A-Za-z0-9_-]{11}(?![A-Za-z0-9_-])"),
}


def decoded_text(text: str) -> str:
    for _ in range(2):
        text = unquote(html.unescape(text)).replace("\\/", "/")
    return text


def public_findings(text: str) -> dict[str, int]:
    value = decoded_text(text)
    return {kind: len(matches) for kind, pattern in PLATFORM_PATTERNS.items()
            if (matches := list(pattern.finditer(value)))}


def git_entries(root: Path = ROOT, ref: str | None = None) -> dict[str, bytes]:
    actual = Path(subprocess.check_output(
        ["git", "rev-parse", "--show-toplevel"], cwd=root, text=True
    ).strip())
    if actual.resolve() != root.resolve():
        raise RuntimeError("Refusing a Git root outside the intended project")
    if ref:
        ref = subprocess.check_output(
            ["git", "rev-parse", "--verify", ref + "^{commit}"], cwd=root, text=True
        ).strip()
    command = ["git", "ls-tree", "-r", "--name-only", "-z", ref] if ref else ["git", "ls-files", "-z"]
    names = subprocess.check_output(command, cwd=root).decode("utf-8").split("\0")
    return {name: subprocess.check_output(
        ["git", "show", f"{ref}:{name}" if ref else f":{name}"], cwd=root
    ) for name in names if name}


def private_evidence(root: Path = ROOT) -> dict[str, str]:
    """Build local-only comparison strings; never emit these strings in reports."""
    registry = json.loads((root / "config" / "sources.json").read_text(encoding="utf-8"))
    raw_paths = list((root / "data" / "raw").rglob("*.jsonl"))
    if not registry.get("sources") or not raw_paths:
        raise RuntimeError("Private evidence check requires a populated registry and raw corpus")
    evidence: dict[str, str] = {}

    def add(value: object, kind: str, minimum: int = 8) -> None:
        if isinstance(value, str) and len(value.strip()) >= minimum:
            if kind == "known_source_metadata" and value.strip().casefold() in GENERIC_METADATA_WORDS:
                return
            evidence[value.strip()] = kind

    def add_url(value: object) -> None:
        if not isinstance(value, str) or not value.startswith(("https://", "http://")):
            return
        add(value, "known_source_url")
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower()
        if host.endswith("youtube.com"):
            for video_id in parse_qs(parsed.query).get("v", []):
                add(video_id, "known_source_identifier")
            if parsed.path.startswith(("/shorts/", "/live/", "/embed/")):
                add(parsed.path.split("/")[2], "known_source_identifier")
        elif host in {"youtu.be", "t.me", "telegram.me"}:
            add(parsed.path.lstrip("/"), "known_source_identifier")

    def visit_registry(value: object) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {"source_id", "video_id", "source_item_id"}:
                    add(child, "known_source_identifier")
                if key in {"name", "title", "source_name", "verified_title", "observed_title",
                           "publisher", "verified_publisher", "observed_publisher"}:
                    add(child, "known_source_metadata", 6)
                visit_registry(child)
        elif isinstance(value, list):
            for child in value:
                visit_registry(child)
        elif isinstance(value, str):
            add_url(value)

    visit_registry(registry)
    records = 0
    for path in raw_paths:
        with path.open(encoding="utf-8-sig") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                records += 1
                for key in ("source_url", "content_url", "parent_url"):
                    add_url(row.get(key))
                for key in ("source_item_id", "video_id", "parent_id", "parent_comment_id"):
                    add(row.get(key), "known_source_identifier")
                # Short common vocabulary cannot reliably distinguish code from a row.
                add(row.get("original_text"), "known_raw_text", 25)
    if not records:
        raise RuntimeError("Private raw corpus is empty")
    return evidence


def evidence_matcher(evidence: dict[str, str]):
    folded = {decoded_text(value).casefold(): kind for value, kind in evidence.items()}

    def matches(text: str) -> dict[str, int]:
        value = decoded_text(text).casefold()
        counts: Counter[str] = Counter()
        # Thousands of long alternatives make an unanchored regex prohibitively
        # slow. Literal substring checks also handle punctuation/newlines exactly.
        for needle, kind in folded.items():
            if needle in value:
                counts[kind] += value.count(needle)
        return dict(counts)

    return matches


def audit_entries(entries: dict[str, bytes], evidence: dict[str, str] | None = None) -> list[dict]:
    compare = evidence_matcher(evidence or {})
    findings = []
    for path, payload in entries.items():
        try:
            text = payload.decode("utf-8-sig")
        except UnicodeDecodeError:
            findings.append({"path": path, "kinds": {"uninspected_binary_file": 1}})
            continue
        kinds = public_findings(text)
        kinds.update(compare(text))
        if kinds:
            findings.append({"path": path, "kinds": kinds})
    return findings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", help="Inspect a commit instead of the current index")
    parser.add_argument("--private-evidence", action="store_true", help="Require and compare local private evidence")
    args = parser.parse_args()
    entries = git_entries(ref=args.ref)
    evidence = private_evidence() if args.private_evidence else None
    findings = audit_entries(entries, evidence)
    print(json.dumps({"scope": args.ref or "actual index bytes", "files_checked": len(entries),
                      "private_evidence_compared": evidence is not None,
                      "findings": findings, "matched_values_disclosed": False}, indent=2))
    if findings:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
