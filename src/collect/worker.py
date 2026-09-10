from __future__ import annotations

from itertools import islice
from typing import Any

from youtube_comment_downloader import SORT_BY_POPULAR, YoutubeCommentDownloader


def download_worker(url: str, limit: int, sender: Any) -> None:
    """Child-process entry point for a bounded public comment download."""
    try:
        downloader = YoutubeCommentDownloader()
        comments = list(islice(downloader.get_comments_from_url(url, sort_by=SORT_BY_POPULAR), limit))
        sender.send((comments, None))
    except Exception as exc:
        sender.send(([], f"{type(exc).__name__}: {exc}"))
    finally:
        sender.close()
