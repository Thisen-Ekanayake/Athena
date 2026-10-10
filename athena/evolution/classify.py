"""
Classify citing sentences with the local 9B: what does the citing paper say about the cited one?

Two short questions, each answered as schema-constrained JSON at temperature
0 with thinking off (Phase 0: thinking gained at most 0.04 F1 and was 34-43x
slower):

1. The Phase 0 Task B label: addresses_limitation, criticises,
   extends_or_uses, compares or background.
2. Only for the two limitation labels: is the problem attributed to the
   cited paper's own method? Phase 0's false positives all stated a real
   problem that was not the cited paper's: R-CNN's speed, cited through Fast
   R-CNN's timing table, or a finding the cited paper reports about
   something else.

A strict gap -> resolution link needs a limitation label and a yes to
question 2, asked twice: as above, then again with thinking on. Hand-checking
all 148 strict links of the first run (Claude's blind answers): question 2
alone gave precision 0.69; confirmed with thinking, 0.85 (95% interval
0.77-0.91), keeping 88 of the 97 true links. Thinking costs ~15 s, so it is
spent only on sentences that already passed. Talks to any OpenAI-compatible
chat endpoint, so another model can stand in for the local one (thinking is a
local Qwen switch, so there the confirmation is skipped).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass

import httpx

from athena.core.config_store import get_setting

LABELS = ["addresses_limitation", "criticises", "extends_or_uses", "compares", "background"]
LIMITATION_LABELS = {"addresses_limitation", "criticises"}
SYSTEM_PROMPT = "You classify text from research papers. Reply with JSON only."
THINK_TOKENS = 900  # the server caps thinking at 512 tokens (--reasoning-budget); the answer follows


_MARK_NOTE = "The citation of the cited paper is marked [[like this]].\n"


def _header(citing_title: str, cited_title: str, sentence: str, marked: str | None) -> str:
    return (f"Citing paper: {citing_title}\nCited paper: {cited_title}\n"
            f"Sentence from the citing paper: {marked or sentence}\n" + (_MARK_NOTE if marked else "") + "\n")


def label_prompt(citing_title: str, cited_title: str, sentence: str, marked: str | None = None) -> str:
    return (
        _header(citing_title, cited_title, sentence, marked)
        + "What does this sentence say about the cited paper?\n"
        "- addresses_limitation: the cited work has a problem and the citing paper claims to fix or improve "
        "on it.\n"
        "- criticises: the sentence states a problem or limitation of the cited work, with no fix claimed in "
        "the same sentence.\n"
        "- extends_or_uses: the citing paper builds on or uses the cited method, data or code without "
        "claiming to fix a flaw.\n"
        "- compares: results are compared against the cited work as a baseline.\n"
        "- background: the cited work is mentioned as context.\n"
        "Judge only what the sentence says about the cited paper.\n"
        'Return {"label": "<one of the five labels>"}.'
    )


def attribution_prompt(citing_title: str, cited_title: str, sentence: str, marked: str | None = None) -> str:
    return (
        _header(citing_title, cited_title, sentence, marked)
        + "Does this sentence say that the cited paper's own method, model or results have a problem or "
        "limitation? Count it when the cited paper is one of several works criticised together. Do not count "
        "it when the cited paper is only the source of a measurement or finding about a different method.\n"
        'Return {"attributed": true} or {"attributed": false}.'
    )


def gap_prompt(paper_title: str, section_type: str | None, sentence: str) -> str:
    """Phase 0 Task A: precision 1.00, recall 0.77 (F1 0.87) on 48 labelled sentences."""
    return (
        f"Paper: {paper_title}\nSection: {section_type or 'unknown'}\nSentence: {sentence}\n\n"
        "Is this sentence a research gap statement? A gap statement describes a limitation, an unsolved "
        "problem, or something existing methods (or this paper) cannot do. Claims about the paper's own "
        "successful results are not gaps.\n"
        'Return {"label": "gap"} or {"label": "not_gap"}.'
    )


def theme_label_prompt(topic_name: str, sentences: list[str]) -> str:
    listed = "\n".join(f"- {s}" for s in sentences)
    return (
        f"Research topic: {topic_name}\nThese sentences from research papers state the same kind of research gap:\n"
        f"{listed}\n\n"
        # The examples come from other fields so they cannot be copied as labels for these topics.
        "Name that gap in at most six words, as a short noun phrase (for example \"Noisy labels in crowdsourced "
        "data\" or \"High latency of speech decoding\"). Use no author names.\n"
        'Return {"label": "<at most six words>"}.'
    )


THEME_LABEL_SCHEMA = {"type": "object", "properties": {"label": {"type": "string", "maxLength": 60}},
                      "required": ["label"], "additionalProperties": False}
GAP_SCHEMA = {"type": "object", "properties": {"label": {"type": "string", "enum": ["gap", "not_gap"]}},
              "required": ["label"], "additionalProperties": False}
LABEL_SCHEMA = {"type": "object", "properties": {"label": {"type": "string", "enum": LABELS}},
                "required": ["label"], "additionalProperties": False}
ATTRIBUTION_SCHEMA = {"type": "object", "properties": {"attributed": {"type": "boolean"}},
                      "required": ["attributed"], "additionalProperties": False}


@dataclass
class Verdict:
    label: str | None
    attributed: bool | None
    seconds: float

    @property
    def strict(self) -> bool:
        return self.label in LIMITATION_LABELS and self.attributed is True


def managed_servers() -> bool:
    """True when the lane runs its own llama-server (the default); False for any OpenAI-compatible endpoint.

    With EVOLUTION_MANAGED_SERVERS=false, EVOLUTION_CHAT_URL and EVOLUTION_EMBED_URL point at another
    service (without the trailing /v1), EVOLUTION_API_KEY is sent as a bearer token, and nothing
    llama.cpp-specific is sent to it.
    """
    return get_setting("EVOLUTION_MANAGED_SERVERS", "true").strip().lower() not in ("false", "0", "no")


def auth_headers() -> dict:
    key = get_setting("EVOLUTION_API_KEY")
    return {"Authorization": f"Bearer {key}"} if key else {}


class Classifier:
    def __init__(self, base_url: str | None = None, model: str | None = None, http: httpx.Client | None = None,
                 local: bool | None = None):
        self.base_url = (base_url or get_setting("EVOLUTION_CHAT_URL", "http://127.0.0.1:8080")).rstrip("/")
        self.model = model or get_setting("EVOLUTION_CHAT_MODEL_NAME", "qwen3.5-9b")
        self.local = managed_servers() if local is None else local
        self.http = http or httpx.Client(timeout=900.0, headers=auth_headers())

    def ask(self, prompt: str, schema: dict, name: str, think: bool = False) -> dict | None:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": THINK_TOKENS if think else 64,
            "response_format": {"type": "json_schema", "json_schema": {"name": name, "schema": schema}},
        }
        if self.local:
            # Qwen's chat template switches thinking per request; other servers may reject the field.
            payload["chat_template_kwargs"] = {"enable_thinking": think}
        resp = self.http.post(f"{self.base_url}/v1/chat/completions", json=payload)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"].get("content") or ""
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return None

    @property
    def model_tag(self) -> str:
        """Stored with each label, so labels made without the thinking confirmation can be found."""
        return f"{self.model}+think" if self.local else self.model

    def attribution(self, citing_title: str, cited_title: str, sentence: str, marked: str | None,
                    think: bool = False) -> bool | None:
        answer = self.ask(attribution_prompt(citing_title, cited_title, sentence, marked), ATTRIBUTION_SCHEMA,
                          "attribution", think=think) or {}
        return answer.get("attributed") if isinstance(answer.get("attributed"), bool) else None

    def classify(self, citing_title: str, cited_title: str, sentence: str, marked: str | None = None) -> Verdict:
        start = time.time()
        answer = self.ask(label_prompt(citing_title, cited_title, sentence, marked), LABEL_SCHEMA,
                          "citation_label") or {}
        label = answer.get("label") if answer.get("label") in LABELS else None
        attributed = None
        if label in LIMITATION_LABELS:
            attributed = self.attribution(citing_title, cited_title, sentence, marked)
            if attributed and self.local:
                attributed = self.attribution(citing_title, cited_title, sentence, marked, think=True)
        return Verdict(label, attributed, time.time() - start)

    def is_gap(self, paper_title: str, section_type: str | None, sentence: str) -> str | None:
        answer = self.ask(gap_prompt(paper_title, section_type, sentence), GAP_SCHEMA, "gap") or {}
        return answer.get("label") if answer.get("label") in ("gap", "not_gap") else None

    def theme_label(self, topic_name: str, sentences: list[str]) -> str | None:
        """A short name for a gap theme (the plan's optional labels; TF-IDF terms are the fallback)."""
        answer = self.ask(theme_label_prompt(topic_name, sentences), THEME_LABEL_SCHEMA, "theme_label") or {}
        label = " ".join(str(answer.get("label") or "").split())
        return label if 0 < len(label.split()) <= 8 else None
