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

from athena.core import llm, usage
from athena.model_server import activity
from athena.core.config_store import get_setting

LABELS = ["addresses_limitation", "criticises", "extends_or_uses", "compares", "background"]
LIMITATION_LABELS = {"addresses_limitation", "criticises"}
SYSTEM_PROMPT = "You classify text from research papers. Reply with JSON only."
THINK_BUDGET = 512  # thinking tokens for a confirmation, sent with each request (the presets may not cap it)
THINK_TOKENS = 900  # thinking plus the short JSON answer


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


def batch_label_prompt(items: list[tuple[str, str, str, str | None]]) -> str:
    """``label_prompt`` for several sentences at once: [(citing title, cited title, sentence, marked)]."""
    listed = "\n".join(
        f"{i}. Citing paper: {citing}\n   Cited paper: {cited}\n   Sentence from the citing paper: {marked or sentence}"
        for i, (citing, cited, sentence, marked) in enumerate(items, 1))
    note = "In each sentence, the citation of the cited paper is marked [[like this]].\n" \
        if any(m for *_, m in items) else ""
    return (
        f"{listed}\n\n{note}"
        "For each numbered sentence: what does it say about its cited paper?\n"
        "- addresses_limitation: the cited work has a problem and the citing paper claims to fix or improve "
        "on it.\n"
        "- criticises: the sentence states a problem or limitation of the cited work, with no fix claimed in "
        "the same sentence.\n"
        "- extends_or_uses: the citing paper builds on or uses the cited method, data or code without "
        "claiming to fix a flaw.\n"
        "- compares: results are compared against the cited work as a baseline.\n"
        "- background: the cited work is mentioned as context.\n"
        "Judge each sentence on its own, only by what it says about its cited paper.\n"
        f'Return {{"labels": [...]}} with {len(items)} labels, one per sentence, in order.'
    )


def batch_label_schema(n: int) -> dict:
    return {"type": "object", "properties": {"labels": {"type": "array", "items": {"type": "string", "enum": LABELS},
                                                        "minItems": n, "maxItems": n}},
            "required": ["labels"], "additionalProperties": False}


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


def is_local() -> bool:
    """Whether the lane's chat endpoint is llama.cpp, so Qwen's thinking switch and /tokenize can be used.

    EVOLUTION_MANAGED_SERVERS=false (from before the shared router) still marks an outside service.
    """
    if get_setting("EVOLUTION_MANAGED_SERVERS").strip().lower() in ("false", "0", "no"):
        return False
    return llm.is_llama_cpp(chat_url())


def chat_url() -> str:
    """The lane's chat endpoint without /v1: EVOLUTION_CHAT_URL to bring another model, else the app's own."""
    return (get_setting("EVOLUTION_CHAT_URL") or llm.server_root(llm.chat_base_url())).rstrip("/")


def embed_url() -> str:
    return (get_setting("EVOLUTION_EMBED_URL") or llm.server_root(llm.embed_base_url())).rstrip("/")


def chat_model_name() -> str:
    return get_setting("EVOLUTION_CHAT_MODEL_NAME") or llm.chat_model()


def embed_model_name() -> str:
    return get_setting("EVOLUTION_EMBED_MODEL_NAME") or llm.embed_model()


def chat_available() -> bool:
    """Whether a chat model is configured at all; says nothing about the GPU being free."""
    return bool(chat_model_name())


def auth_headers(url: str | None = None) -> dict:
    """EVOLUTION_API_KEY, else the app's key for that endpoint; nothing for a keyless local server."""
    url = url or chat_url()
    key = get_setting("EVOLUTION_API_KEY")
    if not key:
        key = llm.embed_api_key() if url == embed_url() and url != chat_url() else llm.chat_api_key()
    return {"Authorization": f"Bearer {key}"} if key and key != "local" else {}


class Classifier:
    def __init__(self, base_url: str | None = None, model: str | None = None, http: httpx.Client | None = None,
                 local: bool | None = None, feature: str = "map_build", wait: dict | None = None):
        self.base_url = (base_url or chat_url()).rstrip("/")
        self.model = model or chat_model_name()
        self.local = is_local() if local is None else local
        self.http = http or httpx.Client(timeout=900.0, headers=auth_headers(self.base_url))
        self.feature = feature  # what its calls count as in the usage log
        # Background use: before each call, wait for chats and the model's turn on the GPU (lane.yield_to_chat's
        # arguments); None calls at once.
        self.wait = wait

    def ask(self, prompt: str, schema: dict, name: str, think: bool = False,
            max_tokens: int | None = None) -> dict | None:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": max_tokens or (THINK_TOKENS if think else 64),
            "response_format": {"type": "json_schema", "json_schema": {"name": name, "schema": schema}},
        }
        if self.local:
            # Qwen's chat template switches thinking per request; other servers may reject the field.
            payload["chat_template_kwargs"] = {"enable_thinking": think}
            if think:
                # The cap travels with the request: the model registry's presets dropped the hand-written
                # reasoning-budget, so thinking ran to max_tokens and was cut off before the answer (16 of 19
                # confirmations, 25 s each, scored as "not attributed", 2026-11-03).
                payload["reasoning_budget_tokens"] = THINK_BUDGET
                payload["reasoning_budget_message"] = llm.BUDGET_MESSAGE
        if self.wait is not None:
            from athena.model_server import lane
            lane.yield_to_chat(**{"who": self.feature, "model": self.model} | self.wait)
        with activity.track(self.feature, self.model) as call:
            resp = self.http.post(f"{self.base_url}/v1/chat/completions", json=payload)
            resp.raise_for_status()
            body = resp.json()
            call.tokens(*usage.tokens_of(body.get("usage")))
        usage.add(self.feature, self.model, *usage.tokens_of(body.get("usage")))
        content = body["choices"][0]["message"].get("content") or ""
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

    def labels(self, items: list[tuple[str, str, str, str | None]]) -> list[str | None]:
        """The first question for several sentences in one request: [(citing title, cited title, sentence,
        marked)] -> a label (or None) each."""
        if len(items) == 1:
            answer = self.ask(label_prompt(*items[0]), LABEL_SCHEMA, "citation_label") or {}
            return [answer.get("label") if answer.get("label") in LABELS else None]
        answer = self.ask(batch_label_prompt(items), batch_label_schema(len(items)), "citation_labels",
                          max_tokens=16 + 12 * len(items)) or {}
        got = answer.get("labels") if isinstance(answer.get("labels"), list) else []
        if len(got) != len(items):
            return [None] * len(items)
        return [label if label in LABELS else None for label in got]

    def classify_many(self, items: list[tuple[str, str, str, str | None]]) -> list[Verdict]:
        """``classify`` for several sentences: their labels in one request, then the attribution questions one
        sentence at a time (only limitation labels get them)."""
        start = time.time()
        out = []
        for (citing, cited, sentence, marked), label in zip(items, self.labels(items)):
            attributed = None
            if label in LIMITATION_LABELS:
                attributed = self.attribution(citing, cited, sentence, marked)
                if attributed and self.local:
                    attributed = self.attribution(citing, cited, sentence, marked, think=True)
            out.append(Verdict(label, attributed, time.time() - start))
        return out

    def is_gap(self, paper_title: str, section_type: str | None, sentence: str) -> str | None:
        answer = self.ask(gap_prompt(paper_title, section_type, sentence), GAP_SCHEMA, "gap") or {}
        return answer.get("label") if answer.get("label") in ("gap", "not_gap") else None

    def theme_label(self, topic_name: str, sentences: list[str]) -> str | None:
        """A short name for a gap theme (the plan's optional labels; TF-IDF terms are the fallback)."""
        answer = self.ask(theme_label_prompt(topic_name, sentences), THEME_LABEL_SCHEMA, "theme_label") or {}
        label = " ".join(str(answer.get("label") or "").split())
        return label if 0 < len(label.split()) <= 8 else None
