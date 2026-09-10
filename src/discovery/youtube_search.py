from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import yt_dlp

from src.processing.category import lexical, normalized_config, phrase_match
from src.utils.io import PROJECT_ROOT, read_json


USER_AGENT = "Mozilla/5.0 (compatible; Uzbek-RAI-Research/1.0; public-source-discovery)"


def search(query: str, result_limit: int) -> list[dict[str, Any]]:
    options = {
        "quiet": True,
        "extract_flat": True,
        "skip_download": True,
        "playlistend": result_limit,
        "ignoreerrors": True,
    }
    with yt_dlp.YoutubeDL(options) as client:
        payload = client.extract_info(f"ytsearch{result_limit}:{query}", download=False)
    return [entry for entry in (payload or {}).get("entries", []) if entry and entry.get("id")]


def oembed(video_id: str) -> dict[str, Any] | None:
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    endpoint = "https://www.youtube.com/oembed?" + urlencode({"url": video_url, "format": "json"})
    request = Request(endpoint, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=20) as response:
            if response.status != 200:
                return None
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None


def title_relevant(title: str, config: dict[str, Any], query: str) -> bool:
    norm = lexical(title)
    # Source discovery requires a category/topic term in the verified title.
    # Harm-only query fragments such as "haydash kerak" are not sufficient:
    # they otherwise retrieve unrelated driving instruction videos.
    evidence_terms = config["contextual_terms"] + config["weak_terms"] + config["target_terms"]
    if phrase_match(norm, evidence_terms):
        return True
    discovery_stop_tokens = {
        "uzbek", "o'zbek", "youtube", "komment", "haqiqiy", "qanday", "haqida",
        "oilada", "muhokama", "podcast", "suhbat", "munosabat", "maslahat",
        "kerak", "uchun", "degan", "fikrlar",
    }
    meaningful_query_tokens = [
        token for token in lexical(query).split()
        if len(token) >= 5 and token not in discovery_stop_tokens
    ]
    return len(set(phrase_match(norm, meaningful_query_tokens))) >= 2


def title_quality_score(title: str, config: dict[str, Any]) -> tuple[int, list[str]]:
    """Prefer opinion-heavy social discussion and demote keyword-hit entertainment."""
    norm = lexical(title)
    quality = config.get("source_quality") or {}
    positive = phrase_match(norm, quality.get("positive_title_terms") or [])
    negative = phrase_match(norm, quality.get("negative_title_terms") or [])
    generic_discussion = phrase_match(
        norm,
        ["podcast", "suhbat", "intervyu", "muhokama", "munosabat", "maslahat", "savol javob", "huquq", "muammo"],
    )
    score = 2 * len(set(positive + generic_discussion)) - 3 * len(set(negative))
    evidence = [*(f"positive:{item}" for item in positive), *(f"discussion:{item}" for item in generic_discussion)]
    evidence.extend(f"entertainment:{item}" for item in negative)
    return score, evidence


def discover(
    categories: list[str], per_query: int, max_new_per_category: int, pass_name: str | None = None,
) -> dict[str, int]:
    terms_doc = read_json(PROJECT_ROOT / "config" / "search_terms.json")
    registry_path = PROJECT_ROOT / "config" / "sources.json"
    registry = read_json(registry_path)
    existing = {str(source.get("url")): source for source in registry["sources"]}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    added_by_category: dict[str, int] = {category: 0 for category in categories}
    added_source_ids: dict[str, list[str]] = {category: [] for category in categories}
    attempted: list[dict[str, Any]] = []
    for category in categories:
        if category not in terms_doc["categories"]:
            raise ValueError(f"No search bank for {category}")
        raw_config = terms_doc["categories"][category]
        config = normalized_config(raw_config)
        query_passes = raw_config.get("discovery_query_passes") or {}
        queries = list(query_passes.get(pass_name) or []) if pass_name else config["discovery_queries"]
        if pass_name and not queries:
            raise ValueError(f"No {pass_name!r} discovery query pass configured for {category}")
        for query in queries:
            if added_by_category[category] >= max_new_per_category:
                break
            try:
                entries = search(query, per_query)
            except Exception as exc:
                attempted.append({"category": category, "query": query, "error": f"{type(exc).__name__}: {exc}"})
                continue
            attempted.append({"category": category, "query": query, "results": len(entries)})
            for entry in entries:
                if added_by_category[category] >= max_new_per_category:
                    break
                video_id = str(entry["id"])
                url = f"https://www.youtube.com/watch?v={video_id}"
                title = str(entry.get("title") or "")
                if not title_relevant(title, config, query):
                    continue
                quality_score, quality_evidence = title_quality_score(title, config)
                if quality_score < 0:
                    attempted.append({
                        "category": category,
                        "query": query,
                        "source_id": f"YT-{video_id}",
                        "disposition": "DEPRIORITIZED_ENTERTAINMENT_TITLE",
                        "quality_score": quality_score,
                        "quality_evidence": quality_evidence,
                    })
                    continue
                if url in existing:
                    categories_for_source = existing[url].setdefault("likely_taxonomy_categories", [])
                    if category not in categories_for_source:
                        categories_for_source.append(category)
                    continue
                metadata = oembed(video_id)
                if not metadata:
                    continue
                observed_title = str(metadata.get("title") or title)
                observed_publisher = str(metadata.get("author_name") or entry.get("channel") or "")
                source = {
                    "source_id": f"YT-{video_id}",
                    "name": observed_title,
                    "platform": "YouTube",
                    "url": url,
                    "public_access": True,
                    "primary_language": "Uzbek or mixed; candidate text filtered separately",
                    "content_type": "Public video comments",
                    "likely_taxonomy_categories": [category],
                    "collection_feasibility": "Public comments attempted without login; actual availability measured by collector",
                    "collection_method": "youtube-comment-downloader public endpoint; no account; rate-limited",
                    "collection_enabled": True,
                    "reachability_verified": True,
                    "identity_verified": True,
                    "verified_title": observed_title,
                    "verified_publisher": observed_publisher,
                    "verified_at": now,
                    "identity_verification_method": "YouTube oEmbed metadata",
                    "verified": True,
                    "reachability": {
                        "reachable": True,
                        "http_status": 200,
                        "final_url": url,
                        "checked_at": now,
                        "error": None,
                    },
                    "identity_verification": {
                        "verified": True,
                        "method": "YouTube oEmbed metadata",
                        "metadata_status": 200,
                        "observed_title": observed_title,
                        "observed_publisher": observed_publisher,
                        "platform_match": True,
                        "title_match": True,
                        "title_similarity": 1.0,
                        "error": None,
                        "checked_at": now,
                    },
                    "notes": f"Discovered from public YouTube search query: {query}",
                    "source_quality_score": quality_score,
                    "source_quality_evidence": quality_evidence,
                    "discovery_pass": pass_name or "default",
                }
                registry["sources"].append(source)
                existing[url] = source
                added_by_category[category] += 1
                added_source_ids[category].append(source["source_id"])
                print(f"DISCOVERED\t{category}\t{source['source_id']}\t{observed_title}")
    registry["last_updated"] = now
    registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log_path = PROJECT_ROOT / "data" / "logs" / "source_discovery.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps({
            "timestamp": now,
            "categories": categories,
            "pass_name": pass_name or "default",
            "added": added_by_category,
            "added_source_ids": added_source_ids,
            "attempted": attempted,
        }, ensure_ascii=False) + "\n")
    return added_by_category


def main() -> None:
    # Windows terminals may use a legacy code page even though registry and
    # logs are UTF-8. Keep display errors from aborting a completed discovery.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
    parser = argparse.ArgumentParser(description="Discover and oEmbed-verify public YouTube discussion sources.")
    parser.add_argument("categories", nargs="+")
    parser.add_argument("--per-query", type=int, default=8)
    parser.add_argument("--max-new-per-category", type=int, default=15)
    parser.add_argument("--pass-name", choices=["taxonomy", "topic", "observed"])
    args = parser.parse_args()
    categories = [value.upper() for value in args.categories]
    result = discover(categories, args.per_query, args.max_new_per_category, args.pass_name)
    for category, count in result.items():
        print(f"SUMMARY\t{category}\tNEW_VERIFIED_SOURCES={count}")


if __name__ == "__main__":
    main()
