from __future__ import annotations

import argparse
import hashlib
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from src.collect.__main__ import download_comments
from src.utils.io import PROJECT_ROOT, append_jsonl, read_json, read_jsonl


RAW_PATH = PROJECT_ROOT / "data" / "raw" / "youtube" / "GEN-1.jsonl"


def stable_raw_id(source_id: str, source_item_id: str, original_text: str) -> str:
    payload = "\u241f".join((source_id, source_item_id, original_text)).encode("utf-8")
    return "RAW-" + hashlib.sha256(payload).hexdigest()[:16]


def returned_direct_permalink(comment: dict[str, Any]) -> str | None:
    """Accept only a URL literally returned by platform metadata; never construct one."""
    for field in ("permalink", "comment_url", "url"):
        value = comment.get(field)
        if not isinstance(value, str) or not value.startswith(("https://", "http://")):
            continue
        host = urlparse(value).netloc.casefold()
        if host.endswith("youtube.com") or host.endswith("youtu.be"):
            return value
    return None


def returned_parent_context(comment: dict[str, Any]) -> str | None:
    """Preserve exact parent text only when the retrieval response literally supplies it."""
    for field in ("parent_text", "reply_to_text", "parent_comment_text"):
        value = comment.get(field)
        if isinstance(value, str) and value.strip():
            return value
    return None


def make_record(source: dict[str, Any], comment: dict[str, Any], retrieved_at: str) -> dict[str, Any] | None:
    original_text = comment.get("text")
    source_item_id = comment.get("cid")
    if not isinstance(original_text, str) or not original_text.strip() or not source_item_id:
        return None
    direct_permalink = returned_direct_permalink(comment)
    parent_context = returned_parent_context(comment)
    identity = source.get("identity_verification") or {}
    reachability = source.get("reachability") or {}
    return {
        "raw_record_id": stable_raw_id(source["source_id"], str(source_item_id), original_text),
        "candidate_id": None,
        "original_text": original_text,
        "normalized_text": None,
        "surrounding_context": None,
        "platform_parent_context": parent_context,
        "context_unavailable": parent_context is None,
        "source_platform": "YouTube",
        "source_name": source["name"],
        "source_url": source["url"],
        "content_url": direct_permalink,
        "direct_permalink_available": direct_permalink is not None,
        "source_item_id": str(source_item_id),
        "human_readable_provenance": (
            f"{source['name']} | {source['url']} | Source Item ID: {source_item_id}"
        ),
        "published_at": None,
        "platform_time_text": comment.get("time"),
        "search_term": None,
        "retrieval_method": "youtube-comment-downloader public endpoint",
        "retrieved_at": retrieved_at,
        "suspected_category": "GEN-1",
        "source_verified": bool(source.get("verified")),
        "url_reachable": bool(reachability.get("reachable")),
        "identity_verified": bool(identity.get("verified")),
        "source_identity_title": identity.get("observed_title"),
        "source_identity_publisher": identity.get("observed_publisher"),
        "source_identity_method": identity.get("method"),
        "example_is_real_world": True,
        "public_access": bool(source.get("public_access")),
        "privacy_note": "Author names and profile identifiers intentionally omitted.",
        "engagement": {"votes_text": comment.get("votes")},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect a rate-limited GEN-1 pilot from verified public YouTube comments.")
    parser.add_argument("--per-source-limit", type=int, default=50)
    parser.add_argument("--delay-seconds", type=float, default=1.0)
    parser.add_argument("--source-timeout-seconds", type=float, default=120.0)
    parser.add_argument("--source-id", action="append", help="Optionally restrict collection to one or more registry source IDs")
    args = parser.parse_args()
    if args.per_source_limit < 1 or args.per_source_limit > 2000:
        raise SystemExit("--per-source-limit must be between 1 and 2000")
    if args.source_timeout_seconds < 10:
        raise SystemExit("--source-timeout-seconds must be at least 10")

    registry = read_json(PROJECT_ROOT / "config" / "sources.json")
    sources = [
        source for source in registry["sources"]
        if source.get("platform") == "YouTube"
        and source.get("collection_enabled")
        and source.get("verified")
        and source.get("reachability", {}).get("reachable")
        and source.get("identity_verification", {}).get("verified")
        and source.get("public_access")
        and "GEN-1" in source.get("likely_taxonomy_categories", [])
        and (not args.source_id or source.get("source_id") in set(args.source_id))
    ]
    existing_ids = {record["raw_record_id"] for record in read_jsonl(RAW_PATH)}
    new_records: list[dict[str, Any]] = []
    failures: list[str] = []
    for index, source in enumerate(sources):
        retrieved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        source_count = 0
        retrieved_count = 0
        try:
            comments, error = download_comments(
                source["url"], args.per_source_limit, args.source_timeout_seconds,
            )
            if error:
                raise RuntimeError(error)
            for comment in comments:
                retrieved_count += 1
                record = make_record(source, comment, retrieved_at)
                if record is None or record["raw_record_id"] in existing_ids:
                    continue
                existing_ids.add(record["raw_record_id"])
                new_records.append(record)
                source_count += 1
            print(
                f"COLLECTED\t{source['source_id']}\t{source_count} new records"
                f"\t{retrieved_count} returned"
            )
        except Exception as exc:  # collector must fail gracefully per source
            message = f"{source['source_id']}: {type(exc).__name__}: {exc}"
            failures.append(message)
            print(f"FAILED\t{message}")
        if index + 1 < len(sources):
            time.sleep(max(0.0, args.delay_seconds))

    # Re-read immediately before append so a previously started collector cannot
    # cause stale-snapshot duplicates. Raw files remain append-only.
    latest_ids = {record["raw_record_id"] for record in read_jsonl(RAW_PATH)}
    new_records = [record for record in new_records if record["raw_record_id"] not in latest_ids]
    appended = append_jsonl(RAW_PATH, new_records)
    latest_ids.update(record["raw_record_id"] for record in new_records)
    print(f"TOTAL_NEW\t{appended}")
    print(f"TOTAL_STORED_UNIQUE\t{len(latest_ids)}")
    if failures:
        print("FAILURES\t" + " | ".join(failures))


if __name__ == "__main__":
    main()
