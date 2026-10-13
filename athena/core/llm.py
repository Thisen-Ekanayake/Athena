"""
Every model call in Athena goes through here: one OpenAI-compatible endpoint for chat and one for
embeddings, so moving between local models and a hosted API is a settings change.

The default is llama-server in router mode on this machine (``config/llama-router.ini``). It serves
Qwen3.5-9B and Qwen3-Embedding-8B under their preset names and swaps them on the GPU on demand
(about 1.5 s, since the files stay in the page cache). For OpenAI instead, set
LLM_BASE_URL=https://api.openai.com/v1, LLM_API_KEY, LLM_CHAT_MODEL, EMBED_MODEL and
EMBED_DIMENSIONS=1024 (text-embedding-3 models shorten vectors themselves). Changing the embedding
model means re-embedding: see ``check_embed_space``.

Settings (env or the settings table): LLM_BASE_URL, LLM_API_KEY, LLM_CHAT_MODEL, LLM_<TASK>_MODEL
(SUMMARY, QA, LIT_REVIEW), LLM_SERVER (llama.cpp | other; guessed from the URL when unset),
LLM_PRICE_IN_PER_M, LLM_PRICE_OUT_PER_M (USD per million tokens, 0 for local models),
EMBED_BASE_URL, EMBED_API_KEY, EMBED_MODEL, EMBED_DIMENSIONS.
"""
from __future__ import annotations

import os
from typing import Callable
from urllib.parse import urlparse

import httpx
import numpy as np
from openai import AsyncOpenAI, OpenAI

from athena.core.config_store import get_setting

# Docker compose points this at the host, where the model server and the GPU are; LLM_BASE_URL still wins.
DEFAULT_BASE_URL = os.getenv("LLM_DEFAULT_BASE_URL", "http://127.0.0.1:8080/v1")
DEFAULT_CHAT_MODEL = "qwen3.5-9b"
DEFAULT_EMBED_MODEL = "qwen3-embedding-8b"
EMBED_DIM = 1024          # stored vectors keep the first 1024 dimensions, renormalised (Phase 0: no recall loss)
EMBED_MAX_TOKENS = 900    # the embedder's preset takes each input in one 1024-token ubatch
HOSTED_MAX_TOKENS = 8000  # OpenAI's embedding models take 8191
HOSTED = {"api.openai.com"}


# ── endpoints and models ───────────────────────────────────────────────


def chat_base_url() -> str:
    return (get_setting("LLM_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")


def embed_base_url() -> str:
    return (get_setting("EMBED_BASE_URL") or chat_base_url()).rstrip("/")


def server_root(url: str) -> str:
    """The server's own address: llama.cpp endpoints such as /tokenize and /health sit beside /v1."""
    url = url.rstrip("/")
    return url[:-3] if url.endswith("/v1") else url


def _key(setting: str, url: str) -> str:
    """The key for ``url``. A stored OpenAI key is only ever sent to OpenAI itself."""
    key = get_setting(setting)
    if not key and urlparse(url).hostname in HOSTED:
        key = get_setting("OPENAI_API_KEY")
    return key or "local"  # the SDK wants some key; llama-server ignores it unless started with --api-key


def chat_api_key() -> str:
    return _key("LLM_API_KEY", chat_base_url())


def embed_api_key() -> str:
    if not get_setting("EMBED_API_KEY") and embed_base_url() == chat_base_url():
        return chat_api_key()
    return _key("EMBED_API_KEY", embed_base_url())


def is_llama_cpp(url: str | None = None) -> bool:
    """Whether llama.cpp-only extras (the thinking switch, /tokenize) may be sent. LLM_SERVER overrides the guess."""
    server = get_setting("LLM_SERVER").strip().lower()
    if server:
        return server in ("llama.cpp", "llamacpp", "llama-server")
    return urlparse(url or chat_base_url()).hostname not in HOSTED


def chat_model(task: str | None = None) -> str:
    """The chat model for ``task`` (summary, qa, lit_review), or the shared one."""
    if task and (override := get_setting(f"LLM_{task.upper()}_MODEL")):
        return override
    return get_setting("LLM_CHAT_MODEL") or DEFAULT_CHAT_MODEL


def embed_model() -> str:
    return get_setting("EMBED_MODEL") or DEFAULT_EMBED_MODEL


# ── chat ───────────────────────────────────────────────────────────────


def chat_client(timeout: float = 600.0) -> OpenAI:
    return OpenAI(base_url=chat_base_url(), api_key=chat_api_key(), timeout=timeout, max_retries=2)


def async_chat_client(timeout: float = 600.0) -> AsyncOpenAI:
    return AsyncOpenAI(base_url=chat_base_url(), api_key=chat_api_key(), timeout=timeout, max_retries=2)


def chat_extra(think: bool = False) -> dict:
    """``extra_body`` for a chat call: Qwen's template switches thinking per request on llama.cpp."""
    return {"chat_template_kwargs": {"enable_thinking": think}} if is_llama_cpp(chat_base_url()) else {}


def chat_json(prompt: str, schema: dict, name: str, system: str | None = None, task: str | None = None,
              max_tokens: int = 300, timeout: float = 120.0) -> tuple[dict | None, dict]:
    """One schema-constrained JSON answer at temperature 0 with thinking off.

    Returns (answer, usage); the answer is None when the reply does not parse. ``usage`` has the model and its
    input and output token counts, for logging and per-user allowances.
    """
    import json

    model = chat_model(task)
    messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    resp = chat_client(timeout=timeout).chat.completions.create(
        model=model, messages=messages, temperature=0, max_tokens=max_tokens,
        response_format={"type": "json_schema", "json_schema": {"name": name, "schema": schema}},
        extra_body=chat_extra(),
    )
    usage = {"model": model, "input_tokens": getattr(resp.usage, "prompt_tokens", 0) or 0,
             "output_tokens": getattr(resp.usage, "completion_tokens", 0) or 0}
    try:
        answer = json.loads(resp.choices[0].message.content or "")
    except json.JSONDecodeError:
        return None, usage
    return (answer if isinstance(answer, dict) else None), usage


def cost(input_tokens: int, output_tokens: int) -> float:
    """USD for a call at the configured prices; local models cost nothing."""
    def price(key: str) -> float:
        try:
            return float(get_setting(key) or 0)
        except ValueError:
            return 0.0
    return (input_tokens * price("LLM_PRICE_IN_PER_M") + output_tokens * price("LLM_PRICE_OUT_PER_M")) / 1_000_000


# ── embeddings ─────────────────────────────────────────────────────────


def truncate(vectors: np.ndarray, dim: int = EMBED_DIM) -> np.ndarray:
    """Keep the first ``dim`` dimensions (Qwen3-Embedding is trained for this) and renormalise."""
    cut = np.asarray(vectors, dtype=np.float32)[:, :dim]
    norms = np.linalg.norm(cut, axis=1, keepdims=True)
    return cut / np.where(norms == 0, 1, norms)


def fit(text: str, max_tokens: int, count: Callable[[str], int]) -> tuple[str, bool]:
    """Trim ``text`` by words until ``count`` says it fits. Formula-heavy text runs near four tokens a word."""
    trimmed = False
    while True:
        tokens = count(text)
        if tokens <= max_tokens:
            return text, trimmed
        words = text.split()
        text = " ".join(words[:max(20, int(len(words) * 0.9 * max_tokens / tokens))])
        trimmed = True


def embed_input_tokens() -> int:
    """A first cut for callers that pre-trim with tiktoken; ``embed`` makes the exact one on llama.cpp."""
    return EMBED_MAX_TOKENS if is_llama_cpp(embed_base_url()) else HOSTED_MAX_TOKENS


def embed(texts: list[str], instruct: str | None = None, timeout: float = 120.0) -> np.ndarray:
    """Unit vectors of EMBED_DIM dimensions, one per text.

    ``instruct`` marks the texts as queries in Qwen3-Embedding's format; documents go in as they are.
    """
    if instruct:
        texts = [f"Instruct: {instruct}\nQuery: {t}" for t in texts]
    url, model = embed_base_url(), embed_model()
    if is_llama_cpp(url):
        with httpx.Client(timeout=timeout) as http:
            def count(text: str) -> int:
                resp = http.post(f"{server_root(url)}/tokenize", json={"content": text, "model": model})
                resp.raise_for_status()
                return len(resp.json()["tokens"])
            texts = [fit(t, EMBED_MAX_TOKENS, count)[0] for t in texts]
    kwargs = {}
    if get_setting("EMBED_DIMENSIONS"):
        kwargs["dimensions"] = int(get_setting("EMBED_DIMENSIONS"))
    client = OpenAI(base_url=url, api_key=embed_api_key(), timeout=timeout, max_retries=2)
    resp = client.embeddings.create(input=texts, model=model, **kwargs)
    raw = np.asarray([d.embedding for d in sorted(resp.data, key=lambda d: d.index)], dtype=np.float32)
    if raw.shape[1] < EMBED_DIM:
        raise ValueError(f"{model} returns {raw.shape[1]} dimensions; Athena stores {EMBED_DIM}. "
                         "Use a model with more, or set EMBED_DIMENSIONS for one that shortens its vectors.")
    return truncate(raw)


class EmbedSpaceMismatch(RuntimeError):
    """Stored vectors came from another embedding model, so new ones would not be comparable."""


def check_embed_space(space: str, model: str | None = None, collection_dim: int | None = None) -> None:
    """Refuse to mix vectors from two embedding models in one store.

    The first call records which model fills ``space`` (an app setting, EMBED_SPACE_<SPACE>); later calls
    raise when the configured model differs, or when the collection's vector size does not match.
    """
    from athena.core.config_store import set_setting  # deferred: the database is only needed here
    key = f"EMBED_SPACE_{space.upper()}"
    model, recorded = model or embed_model(), get_setting(key)
    reset = f"Re-embed with scripts/backfill_embeddings.py --reset{'' if space == 'feed' else ' --evolution'}."
    if collection_dim is not None and collection_dim != EMBED_DIM:
        raise EmbedSpaceMismatch(f"The {space} vectors have {collection_dim} dimensions, not {EMBED_DIM}. {reset}")
    if recorded and recorded != model:
        raise EmbedSpaceMismatch(f"The {space} vectors were made by {recorded}, but EMBED_MODEL is {model}. {reset}")
    if not recorded:
        set_setting(key, model)
