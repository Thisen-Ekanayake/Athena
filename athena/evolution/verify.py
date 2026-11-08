"""
Does each cited source support its sentence? (feedback 2026-11-07, problem 4)

The 9B cited Kaldi, a speech recogniser, for "recognition and translation systems", and a medical-leaflet MT paper
for hallucination mitigation: real sources, given to it, that do not say what the sentence says. Checking that a
citation number was given (``review.check_citations``) cannot catch that.

After a section is written, every (sentence, cited source) pair goes to the model with the source's text, a batch
at a time: yes, partly or no. A "no" citation is removed; a sentence left with no citation is removed too, since
the review makes no uncited claims. If the model's answer cannot be read, the batch is kept as it was.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable

from loguru import logger

BATCH = 8               # claims per call
EVIDENCE_CHARS = 1500   # per source
VERIFY_TOKENS = 400
CITATION = re.compile(r"\[(\d+(?:\s*[,–-]\s*\d+)*)\]")
SENTENCE_END = re.compile(r"(?<=[.!?])(?:\s*\[[\d,\s–-]+\])*\s+(?=[A-Z\"“(])")

Chat = Callable[[list[dict], int], tuple[str, int, int]]

SYSTEM = ("You check citations in a literature review. For each claim, read the cited source's text and say whether "
          "it supports the claim: \"yes\" (it states or clearly implies it), \"partly\" (it supports part of it, or a "
          "weaker version), or \"no\" (it does not say this, or is about something else). Judge only from the text "
          "given. Answer with JSON only.")


@dataclass
class Claim:
    line: int
    start: int
    end: int
    text: str
    cited: list[int]


def _numbers(group: str) -> list[int]:
    from athena.evolution.review import _numbers as numbers
    return numbers(group)


def sentences(line: str) -> list[tuple[int, int]]:
    """(start, end) of each sentence of one line, its trailing citations included."""
    out, start = [], 0
    for m in SENTENCE_END.finditer(line):
        out.append((start, m.start()))
        start = m.end()
    if start < len(line):
        out.append((start, len(line)))
    return out


def claims(text: str) -> list[Claim]:
    found = []
    for i, line in enumerate(text.split("\n")):
        for start, end in sentences(line):
            sentence = line[start:end]
            cited = list(dict.fromkeys(n for m in CITATION.finditer(sentence) for n in _numbers(m.group(1))))
            if cited:
                found.append(Claim(i, start, end, sentence.strip(), cited))
    return found


def messages(pairs: list[tuple[int, Claim, int]], evidence: dict[int, str]) -> list[dict]:
    used = sorted({n for _, _, n in pairs})
    sources = "\n\n".join(f"[{n}]\n{evidence[n][:EVIDENCE_CHARS]}" for n in used)
    listed = "\n".join(f"C{k}: {CITATION.sub('', c.text).strip()}  (cites [{n}])" for k, c, n in pairs)
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"Sources:\n\n{sources}\n\nClaims:\n{listed}\n\nAnswer as "
                                        '{"C1": "yes" | "partly" | "no", ...}, one entry per claim.'}]


def parse(text: str) -> dict[str, str] | None:
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    return {str(k).upper(): str(v).strip().lower() for k, v in data.items()}


def _strip(sentence: str, drop: set[int]) -> str:
    def fix(m: re.Match) -> str:
        keep = [n for n in dict.fromkeys(_numbers(m.group(1))) if n not in drop]
        return f"[{', '.join(map(str, keep))}]" if keep else ""
    return re.sub(r"[ \t]+([.,;:])", r"\1", CITATION.sub(fix, sentence)).rstrip()


def verify(text: str, evidence: dict[int, str], chat: Chat) -> tuple[str, dict]:
    """``text`` without the citations its sources do not support. Returns the text and counts of the verdicts."""
    found = claims(text)
    pairs = [(c, n) for c in found for n in c.cited if evidence.get(n)]
    counts = {"checked": 0, "yes": 0, "partly": 0, "no": 0, "unread": 0, "sentences_removed": 0}
    drop: dict[int, set[int]] = {}   # claim index -> citations to remove
    index = {id(c): i for i, c in enumerate(found)}
    for b in range(0, len(pairs), BATCH):
        batch = [(k + 1, c, n) for k, (c, n) in enumerate(pairs[b:b + BATCH])]
        try:
            answer, *_ = chat(messages(batch, evidence), VERIFY_TOKENS)
            verdicts = parse(answer)
        except Exception as exc:
            logger.warning(f"Citation check: the model did not answer: {exc}")
            verdicts = None
        if verdicts is None:
            counts["unread"] += len(batch)
            continue
        for k, c, n in batch:
            verdict = verdicts.get(f"C{k}", "")
            verdict = "no" if verdict.startswith("no") else "partly" if verdict.startswith("part") else \
                "yes" if verdict.startswith("yes") else ""
            if not verdict:
                counts["unread"] += 1
                continue
            counts["checked"] += 1
            counts[verdict] += 1
            if verdict == "no":
                drop.setdefault(index[id(c)], set()).add(n)
    if not drop:
        return text, counts
    lines = text.split("\n")
    # Edit each line from its last sentence back, so earlier offsets stay right.
    for i in sorted(drop, key=lambda i: (found[i].line, -found[i].start)):
        c = found[i]
        line = lines[c.line]
        sentence = line[c.start:c.end]
        if set(c.cited) <= drop[i]:
            new, counts["sentences_removed"] = "", counts["sentences_removed"] + 1
        else:
            new = _strip(sentence, drop[i])
        lines[c.line] = line[:c.start] + new + line[c.end:]
    edited = {found[i].line for i in drop}
    # A line the check emptied goes, list markers and all.
    lines = [ln for k, ln in enumerate(lines) if k not in edited or not re.fullmatch(r"\s*(?:[-*]|\d+\.)?\s*", ln)]
    out = "\n".join(re.sub(r"[ \t]{2,}", " ", ln).rstrip() for ln in lines)
    return re.sub(r"\n{3,}", "\n\n", out).strip(), counts
