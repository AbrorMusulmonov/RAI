from __future__ import annotations

import argparse
import html
import json
import re
import urllib.parse
import urllib.request
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any

from src.utils.io import PROJECT_ROOT, read_json
from src.utils.text import normalized_for_comparison


USER_AGENT = "Mozilla/5.0 (compatible; Uzbek-RAI-Research/1.0; public-source-verification)"


def fetch(url: str, timeout_seconds: int) -> tuple[int | None, str, bytes, str | None]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return response.status, response.geturl(), response.read(), None
    except Exception as exc:
        return None, url, b"", f"{type(exc).__name__}: {exc}"


def title_matches(expected: str, observed: str) -> tuple[bool, float]:
    expected_norm = normalized_for_comparison(expected)
    observed_norm = normalized_for_comparison(observed)
    if not expected_norm or not observed_norm:
        return False, 0.0
    score = SequenceMatcher(None, expected_norm, observed_norm, autojunk=False).ratio()
    contained = expected_norm in observed_norm or observed_norm in expected_norm
    return contained or score >= 0.84, round(score, 4)


def youtube_identity(source: dict[str, Any], timeout_seconds: int) -> dict[str, Any]:
    endpoint = "https://www.youtube.com/oembed?" + urllib.parse.urlencode({
        "format": "json", "url": source["url"],
    })
    status, final_url, payload, error = fetch(endpoint, timeout_seconds)
    if status != 200:
        return {
            "verified": False, "method": "YouTube oEmbed metadata", "metadata_status": status,
            "observed_title": None, "observed_publisher": None, "platform_match": False,
            "title_match": False, "title_similarity": 0.0, "error": error,
        }
    try:
        metadata = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {
            "verified": False, "method": "YouTube oEmbed metadata", "metadata_status": status,
            "observed_title": None, "observed_publisher": None, "platform_match": False,
            "title_match": False, "title_similarity": 0.0, "error": str(exc),
        }
    observed_title = str(metadata.get("title") or "")
    platform_match = metadata.get("provider_name") == "YouTube" and "youtube.com" in urllib.parse.urlparse(final_url).netloc
    matches, similarity = title_matches(source["name"], observed_title)
    return {
        "verified": bool(platform_match and matches),
        "method": "YouTube oEmbed metadata",
        "metadata_status": status,
        "observed_title": observed_title,
        "observed_publisher": metadata.get("author_name"),
        "platform_match": platform_match,
        "title_match": matches,
        "title_similarity": similarity,
        "error": error,
    }


def telegram_identity(source: dict[str, Any], page_payload: bytes) -> dict[str, Any]:
    page = page_payload.decode("utf-8", errors="replace")
    title_element = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', page, re.IGNORECASE)
    observed_title = html.unescape(title_element.group(1)).strip() if title_element else ""
    platform_match = "tgme_page" in page and urllib.parse.urlparse(source["url"]).netloc == "t.me"
    matches, similarity = title_matches(source["name"], observed_title)
    return {
        "verified": bool(platform_match and matches),
        "method": "Telegram public-preview HTML metadata",
        "observed_title": observed_title or None,
        "observed_publisher": None,
        "platform_match": platform_match,
        "title_match": matches,
        "title_similarity": similarity,
        "error": None,
    }


def verify_source(source: dict[str, Any], timeout_seconds: int, checked_at: str) -> dict[str, Any]:
    status, final_url, payload, error = fetch(source["url"], timeout_seconds)
    reachable = status is not None and 200 <= status < 400
    reachability = {
        "reachable": reachable,
        "http_status": status,
        "final_url": final_url,
        "checked_at": checked_at,
        "error": error,
    }
    if not reachable:
        identity = {
            "verified": False, "method": "not attempted because URL was unreachable",
            "observed_title": None, "observed_publisher": None, "platform_match": False,
            "title_match": False, "title_similarity": 0.0, "checked_at": checked_at,
            "error": error,
        }
    elif source["platform"] == "YouTube":
        identity = youtube_identity(source, timeout_seconds)
        identity["checked_at"] = checked_at
    elif source["platform"] == "Telegram":
        identity = telegram_identity(source, payload)
        identity["checked_at"] = checked_at
    else:
        identity = {
            "verified": False, "method": "no platform identity verifier implemented",
            "observed_title": None, "observed_publisher": None, "platform_match": False,
            "title_match": False, "title_similarity": 0.0, "checked_at": checked_at,
            "error": None,
        }
    return {"reachability": reachability, "identity_verification": identity}


def main() -> None:
    parser = argparse.ArgumentParser(description="Separately verify URL reachability and page identity metadata.")
    parser.add_argument("--write", action="store_true", help="Update verification evidence in sources.json")
    parser.add_argument("--timeout", type=int, default=20)
    args = parser.parse_args()

    path = PROJECT_ROOT / "config" / "sources.json"
    registry = read_json(path)
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    for source in registry["sources"]:
        result = verify_source(source, args.timeout, now)
        reachable = result["reachability"]["reachable"]
        identity = result["identity_verification"]
        print(
            f"{source['source_id']}\treachable={reachable}\tstatus={result['reachability']['http_status']}"
            f"\tidentity={identity['verified']}\ttitle_match={identity['title_match']}"
            f"\tobserved={identity.get('observed_title')!r}"
        )
        if args.write:
            old_verified = bool(source.get("verified"))
            source.update(result)
            # Flat fields are the stable machine-facing contract.  The nested
            # evidence remains available for audit and backwards compatibility.
            source["reachability_verified"] = bool(reachable)
            source["identity_verified"] = bool(identity["verified"])
            source["verified_title"] = identity.get("observed_title") or ""
            source["verified_publisher"] = identity.get("observed_publisher") or ""
            source["identity_verification_method"] = identity.get("method") or ""
            source["verified"] = bool(reachable and identity["verified"])
            source["verified_at"] = now if source["verified"] else None
            if old_verified and not source["verified"]:
                marker = "Verification evidence changed; affected records require re-review."
                if marker not in source.get("notes", ""):
                    source["notes"] = (source.get("notes", "") + " " + marker).strip()
    if args.write:
        registry["last_updated"] = now
        registry["verification_note"] = (
            "URL reachability and page identity are recorded separately. verified=true requires both a reachable URL "
            "and platform/title metadata matching the registry."
        )
        path.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
