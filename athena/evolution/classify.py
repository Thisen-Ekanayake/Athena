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
question 2. Talks to any OpenAI-compatible chat endpoint, so another model
can stand in for the local one.
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


class Classifier:
    def __init__(self, base_url: str | None = None, model: str | None = None, http: httpx.Client | None = None):
        self.base_url = (base_url or get_setting("EVOLUTION_CHAT_URL", "http://127.0.0.1:8080")).rstrip("/")
        self.model = model or get_setting("EVOLUTION_CHAT_MODEL_NAME", "qwen3.5-9b")
        self.http = http or httpx.Client(timeout=300.0)

    def ask(self, prompt: str, schema: dict, name: str) -> dict | None:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": 64,
            "response_format": {"type": "json_schema", "json_schema": {"name": name, "schema": schema}},
            "chat_template_kwargs": {"enable_thinking": False},
        }
        resp = self.http.post(f"{self.base_url}/v1/chat/completions", json=payload)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"].get("content") or ""
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return None

    def classify(self, citing_title: str, cited_title: str, sentence: str, marked: str | None = None) -> Verdict:
        start = time.time()
        answer = self.ask(label_prompt(citing_title, cited_title, sentence, marked), LABEL_SCHEMA,
                          "citation_label") or {}
        label = answer.get("label") if answer.get("label") in LABELS else None
        attributed = None
        if label in LIMITATION_LABELS:
            answer = self.ask(attribution_prompt(citing_title, cited_title, sentence, marked), ATTRIBUTION_SCHEMA,
                              "attribution") or {}
            attributed = answer.get("attributed") if isinstance(answer.get("attributed"), bool) else None
        return Verdict(label, attributed, time.time() - start)
