"""
Method names from citing sentences: "LoRA [28]" in many citing papers -> "LoRA".

No third-party imports, so the API image can use it.
"""
from __future__ import annotations

import re

# A token that looks like a coined name: internal capital, two capitals, or a digit ("LoRA", "R-CNN", "YOLOv3").
NAME_TOKEN = re.compile(r"[a-z][A-Z]|[A-Z].*[A-Z]|\d")
# Words that precede citation markers without naming the cited method.
_NOT_NAMES = {"al", "et", "e.g", "i.e", "eg", "ie", "see", "fig", "figure", "table", "eq", "sec", "section",
              "appendix", "cnn", "cnns", "rnn", "rnns", "dnn", "dnns", "gpu", "gpus", "nlp", "llm", "llms", "ai",
              "sota", "api", "and", "or", "by", "in", "of", "the"}


def detect_method_name(mentions: dict[str, int], title: str, citers: int,
                       min_citers: int = 3, min_share: float = 0.3) -> str | None:
    """The name other papers use when citing a paper: "LoRA [28]" in many citing sentences -> "LoRA".

    ``mentions`` counts, per word, how many distinct citing papers put it right before a marker of this
    paper; ``citers`` is how many citing papers have any sentence citing it. A name must look coined
    (internal capital, two capitals, a digit) or appear in the paper's title ("Prefix-tuning").
    """
    title_words = {w.lower() for w in re.findall(r"[\w\-]+", title)}
    best, best_count = None, 0
    for word, count in mentions.items():
        if word.lower().rstrip(".") in _NOT_NAMES or len(word) < 2:
            continue
        if not (NAME_TOKEN.search(word) or (word[0].isupper() and word.lower() in title_words)):
            continue
        if count > best_count:
            best, best_count = word, count
    if best is None or best_count < min_citers or best_count < min_share * citers:
        return None
    return best
