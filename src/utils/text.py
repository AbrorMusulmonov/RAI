from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher


APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "ʻ": "'", "ʼ": "'", "`": "'", "´": "'"})


def normalized_for_comparison(text: str) -> str:
    value = unicodedata.normalize("NFKC", text).translate(APOSTROPHES).casefold()
    value = re.sub(r"\s+", " ", value).strip()
    return value


def looks_uzbek(text: str) -> bool:
    """High-recall heuristic only; final language judgment remains human."""
    value = normalized_for_comparison(text)
    if not value:
        return False
    signals = (
        "o'z", "g'", "bo'l", "yo'q", "uchun", "kerak", "ayol", "xotin", "qiz",
        "erkak", "ham", "emas", "lekin", "bilan", "bor", "yaxshi", "gap",
        "аёл", "хотин", "қиз", "эркак", "учун", "керак", "эмас", "лекин",
        "билан", "бор", "яхши", "гап", "ў", "қ", "ғ", "ҳ",
    )
    return any(signal in value for signal in signals)


def similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, left, right, autojunk=False).ratio()

