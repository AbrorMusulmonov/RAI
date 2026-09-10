from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from multiprocessing import get_context
from typing import Any
from urllib.parse import urlparse

from src.collect.worker import download_worker
from src.processing.category import source_verified
from src.utils.io import PROJECT_ROOT, append_jsonl, read_json, read_jsonl


def stable_raw_id(source_id: str, source_item_id: str, original_text: str) -> str:
    payload = "\u241f".join((source_id, source_item_id, original_text)).encode("utf-8")
    return "RAW-" + hashlib.sha256(payload).hexdigest()[:16]


def direct_permalink(comment: dict[str, Any]) -> str | None:
    """Accept only a direct URL literally returned by the platform response."""
    for field in ("permalink", "comment_url", "url"):
        value = comment.get(field)
        if not isinstance(value, str) or not value.startswith(("https://", "http://")):
            continue
        host = urlparse(value).netloc.casefold()
        if host.endswith("youtube.com") or host.endswith("youtu.be"):
            return value
    return None


def parent_context(comment: dict[str, Any]) -> str | None:
    for field in ("parent_text", "reply_to_text", "parent_comment_text"):
        value = comment.get(field)
        if isinstance(value, str) and value.strip():
            return value
    return None


def identity(source: dict[str, Any]) -> dict[str, Any]:
    return source.get("identity_verification") or {}


def download_comments(url: str, limit: int, timeout_seconds: float) -> tuple[list[dict[str, Any]], str | None]:
    """Download in a child process and fail closed after a bounded wait."""
    context = get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=download_worker, args=(url, limit, sender), daemon=True)
    process.start()
    sender.close()
    try:
        if receiver.poll(timeout_seconds):
            comments, error = receiver.recv()
            process.join(timeout=5)
            return comments, error
        return [], f"TimeoutError: comment endpoint exceeded {timeout_seconds:g} seconds"
    finally:
        receiver.close()
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
        if process.is_alive() and hasattr(process, "kill"):
            process.kill()
            process.join(timeout=5)


def make_record(source: dict[str, Any], category: str, comment: dict[str, Any], retrieved_at: str) -> dict[str, Any] | None:
    text = comment.get("text")
    item_id = comment.get("cid")
    if not isinstance(text, str) or not text.strip() or not item_id:
        return None
    permalink = direct_permalink(comment)
    parent = parent_context(comment)
    source_identity = identity(source)
    return {
        "raw_record_id": stable_raw_id(str(source["source_id"]), str(item_id), text),
        "candidate_id": None,
        "original_text": text,
        "normalized_text": None,
        "surrounding_context": None,
        "platform_parent_context": parent,
        "context_unavailable": parent is None,
        "source_platform": "YouTube",
        "source_name": source.get("name"),
        "source_url": source.get("url"),
        "content_url": permalink,
        "direct_permalink_available": permalink is not None,
        "source_item_id": str(item_id),
        "parent_item_id": comment.get("parent"),
        "published_at": None,
        "platform_time_text": comment.get("time"),
        "search_term": None,
        "retrieval_method": "youtube-comment-downloader public endpoint",
        "retrieved_at": retrieved_at,
        "suspected_category": category,
        "retrieval_signal": None,
        "stance_hint": None,
        "source_verified": True,
        "url_reachable": True,
        "identity_verified": True,
        "source_identity_title": source.get("verified_title") or source_identity.get("observed_title"),
        "source_identity_publisher": source.get("verified_publisher") or source_identity.get("observed_publisher"),
        "source_identity_method": source_identity.get("method") or source.get("identity_verification_method"),
        "human_readable_provenance": f"{source.get('name', '')} | {source.get('url', '')} | Source Item ID: {item_id}",
        "example_is_real_world": True,
        "public_access": True,
        "privacy_note": "Author names and profile identifiers intentionally omitted.",
        "engagement": {"votes_text": comment.get("votes")},
    }


def collect(
    categories: list[str], per_source_limit: int, delay_seconds: float, source_ids: set[str],
    source_timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    registry = read_json(PROJECT_ROOT / "config" / "sources.json")
    taxonomy_codes = {item["code"] for item in read_json(PROJECT_ROOT / "config" / "taxonomy.json")["subcategories"]}
    invalid = sorted(set(categories) - taxonomy_codes)
    if invalid:
        raise ValueError(f"Unknown categories: {invalid}")
    if "GEN-1" in categories:
        raise ValueError("GEN-1 is protected in the generalized collector; use its dedicated collector only when explicitly necessary.")
    sources = [
        source for source in registry["sources"]
        if source.get("platform") == "YouTube"
        and source.get("collection_enabled", True)
        and source_verified(source)
        and (not source_ids or source.get("source_id") in source_ids)
        and set(categories) & set(source.get("likely_taxonomy_categories", []))
    ]
    cache: dict[str, tuple[list[dict[str, Any]], str | None]] = {}
    summary: dict[str, Any] = {category: {"new": 0, "returned": 0, "sources": 0, "failures": []} for category in categories}
    for index, source in enumerate(sources):
        url = str(source["url"])
        relevant = sorted(set(categories) & set(source.get("likely_taxonomy_categories", [])))
        if url not in cache:
            comments, error = download_comments(url, per_source_limit, source_timeout_seconds)
            cache[url] = (comments, error)
            if index + 1 < len(sources):
                time.sleep(max(0.0, delay_seconds))
        comments, error = cache[url]
        retrieved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for category in relevant:
            summary[category]["sources"] += 1
            summary[category]["returned"] += len(comments)
            if error:
                summary[category]["failures"].append({"source_id": source.get("source_id"), "error": error})
                print(f"FAILED\t{category}\t{source.get('source_id')}\t{error}")
                continue
            path = PROJECT_ROOT / "data" / "raw" / "youtube" / f"{category}.jsonl"
            existing = {record.get("raw_record_id") for record in read_jsonl(path)}
            records = [make_record(source, category, comment, retrieved_at) for comment in comments]
            new_records = [record for record in records if record and record["raw_record_id"] not in existing]
            appended = append_jsonl(path, new_records)
            summary[category]["new"] += appended
            print(f"COLLECTED\t{category}\t{source.get('source_id')}\tNEW={appended}\tRETURNED={len(comments)}")
    log_path = PROJECT_ROOT / "data" / "logs" / "collection.jsonl"
    append_jsonl(log_path, [{
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "categories": categories,
        "per_source_limit": per_source_limit,
        "source_timeout_seconds": source_timeout_seconds,
        "source_ids": sorted(source_ids),
        "summary": summary,
    }])
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect real public comments for one or more taxonomy categories.")
    parser.add_argument("category", nargs="?", help="Single taxonomy code")
    parser.add_argument("--categories", nargs="+", help="Controlled category batch")
    parser.add_argument("--per-source-limit", type=int, default=500)
    parser.add_argument("--delay-seconds", type=float, default=1.0)
    parser.add_argument("--source-timeout-seconds", type=float, default=120.0)
    parser.add_argument("--source-id", action="append", default=[])
    args = parser.parse_args()
    categories = [value.upper() for value in (args.categories or ([args.category] if args.category else []))]
    if not categories:
        raise SystemExit("Provide a category or --categories.")
    if not 1 <= args.per_source_limit <= 5000:
        raise SystemExit("--per-source-limit must be between 1 and 5000")
    if args.source_timeout_seconds < 10:
        raise SystemExit("--source-timeout-seconds must be at least 10")
    summary = collect(
        categories, args.per_source_limit, args.delay_seconds, set(args.source_id),
        args.source_timeout_seconds,
    )
    for category in categories:
        values = summary[category]
        print(
            f"SUMMARY\t{category}\tNEW={values['new']}\tRETURNED={values['returned']}"
            f"\tSOURCES={values['sources']}\tFAILURES={len(values['failures'])}"
        )


if __name__ == "__main__":
    main()
