"""
Method names from citing sentences: "LoRA [28]" in many citing papers -> "LoRA".

No third-party imports, so the API image can use it.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Hashable, Iterable

# A token that looks like a coined name: internal capital, two capitals, or a digit ("LoRA", "R-CNN", "YOLOv3").
NAME_TOKEN = re.compile(r"[a-z][A-Z]|[A-Z].*[A-Z]|\d")
# Words that precede citation markers without naming the cited method.
_NOT_NAMES = {"al", "et", "e.g", "i.e", "eg", "ie", "see", "fig", "figure", "table", "eq", "sec", "section",
              "appendix", "cnn", "cnns", "rnn", "rnns", "dnn", "dnns", "gpu", "gpus", "nlp", "llm", "llms", "ai",
              "sota", "api", "and", "or", "by", "in", "of", "the"}
# Capitalised words that start sentences rather than names ("Unlike LoRA", "Following DETR").
_NOT_NAME_STARTS = {"the", "in", "our", "we", "unlike", "like", "following", "both", "compared", "recently",
                    "similarly", "moreover", "however", "while", "for", "as", "with", "and", "or", "also", "then",
                    "this", "these", "such", "other", "many", "most", "some", "all", "an", "a", "to", "on", "by"}
EXTEND_SHARE = 0.6  # a longer form must be used by this share of the papers using the one-word name


def _suffixes(phrase: str) -> list[str]:
    words = phrase.split()
    return [" ".join(words[-n:]) for n in range(1, min(3, len(words)) + 1)]


def detect_method_name(mentions: Iterable[tuple[Hashable, str]], title: str, citers: int,
                       min_citers: int = 3, min_share: float = 0.3) -> str | None:
    """The name other papers use when citing a paper.

    ``mentions`` are (citing paper, words before the marker) pairs; ``citers`` is how many citing
    papers have any sentence citing it. The name's last word must look coined (internal capital, two
    capitals, a digit) or appear in the paper's title ("Prefix-tuning"), and be used by at least
    ``min_citers`` papers and ``min_share`` of all citers. It grows to two or three words when most of
    those papers use the longer form ("Faster R-CNN", "Swin Transformer").
    """
    users: dict[str, set] = defaultdict(set)
    for citer, phrase in mentions:
        for suffix in _suffixes(phrase or ""):
            users[suffix].add(citer)
    title_words = {w.lower() for w in re.findall(r"[\w\-+]+", title)}

    def looks_like_name(word: str) -> bool:
        if word.lower().rstrip(".") in _NOT_NAMES or len(word) < 2:
            return False
        return bool(NAME_TOKEN.search(word)) or (word[0].isupper() and word.lower() in title_words)

    singles = [w for w in users if " " not in w and looks_like_name(w)]
    if not singles:
        return None
    name = max(singles, key=lambda w: len(users[w]))
    count = len(users[name])
    if count < min_citers or count < min_share * citers:
        return None
    for _ in range(2):
        longer = [s for s in users if s.endswith(" " + name) and s.count(" ") == name.count(" ") + 1]
        longer = [s for s in longer if s[0].isupper() and s.split()[0].lower() not in _NOT_NAME_STARTS]
        best = max(longer, key=lambda s: len(users[s]), default=None)
        if best is None or len(users[best]) < EXTEND_SHARE * count:
            break
        name = best
    return name
