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
LLM_PRICE_IN_PER_M, LLM_PRICE_OUT_PER_M, EMBED_PRICE_PER_M (USD per million tokens, 0 for local models),
EMBED_BASE_URL, EMBED_API_KEY, EMBED_MODEL, EMBED_DIMENSIONS.

``chat_json`` and ``embed`` count each call in the usage log (``athena.core.usage``) under the ``feature`` they
are given; callers of the raw clients count their own.
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


def base_url_for(model: str | None = None) -> str:
    """The server for ``model``: the CPU router for a preset the registry put there, else the chat server."""
    url = chat_base_url()
    if model and (found := _registry_preset(model)) and found["server"] == "cpu":
        from athena.model_server import registry
        return registry.cpu_base_url()
    return url


def chat_client(timeout: float = 600.0, model: str | None = None) -> OpenAI:
    """A client for the chat server; with ``model``, the server that serves it (athena.model_server)."""
    return OpenAI(base_url=base_url_for(model or chat_model()), api_key=chat_api_key(), timeout=timeout,
                  max_retries=2)


def async_chat_client(timeout: float = 600.0, model: str | None = None) -> AsyncOpenAI:
    return AsyncOpenAI(base_url=base_url_for(model or chat_model()), api_key=chat_api_key(), timeout=timeout,
                       max_retries=2)


def chat_extra(think: bool = False) -> dict:
    """``extra_body`` for a chat call: Qwen's template switches thinking per request on llama.cpp."""
    return {"chat_template_kwargs": {"enable_thinking": think}} if is_llama_cpp(chat_base_url()) else {}


# ── models and effort for chats (athena.projects) ──────────────────────

# Thinking tokens per effort. Qwen's template only switches thinking on or off, so effort is a budget; llama-server
# ends the thinking when it runs out, with Qwen's own words for that.
EFFORT_BUDGETS = {"off": 0, "low": 1024, "medium": 4096, "high": 8192}
EFFORTS = tuple(EFFORT_BUDGETS)
BUDGET_MESSAGE = ("\n\nConsidering the limited time by the user, I have to give the solution based on the thinking "
                  "directly now.\n")
DEFAULT_VISION_MODEL = "qwen3.5-9b-vision"
DEFAULT_CONTEXT = 8192    # a model's context when its preset does not say
MODELS_TTL = 5.0         # the picker's "loaded" marks follow the routers within a few seconds
_models_cache: tuple[float, list[dict]] | None = None
_cpu_cache: tuple[float, list[dict]] | None = None


def forget_server_models() -> None:
    """Drop the cached router lists, after a load or unload this process asked for."""
    global _models_cache, _cpu_cache
    _models_cache = _cpu_cache = None


def _names(setting: str, default: str = "") -> list[str]:
    return [n.strip() for n in (get_setting(setting) or default).split(",") if n.strip()]


def reasoning_models() -> set[str]:
    """Models that think (CHAT_REASONING_MODELS, comma-separated, and the registry's): the chat offers them an
    effort."""
    return set(_names("CHAT_REASONING_MODELS", DEFAULT_CHAT_MODEL)) | {r["name"] for r in _registry() if r["reasoning"]}


def _registry() -> list[dict]:
    """The model registry's models (athena.model_server.registry) when chats run on llama.cpp; [] otherwise."""
    if not is_llama_cpp(chat_base_url()):
        return []
    from athena.model_server import registry
    return registry.snapshot()


def _registry_preset(preset: str) -> dict | None:
    if not is_llama_cpp(chat_base_url()):
        return None
    from athena.model_server import registry
    return registry.preset_info(preset)


def vision_model() -> str:
    """The model messages with images go to (CHAT_VISION_MODEL): on the local router, the chat model's GGUF with
    its vision projector, a preset of its own so text chats keep the projector's VRAM."""
    return get_setting("CHAT_VISION_MODEL") or DEFAULT_VISION_MODEL


def _preset_context(preset: str | None) -> int | None:
    for line in (preset or "").splitlines():
        key, _, value = line.partition("=")
        if key.strip() in ("ctx-size", "c", "LLAMA_ARG_CTX_SIZE") and value.strip().isdigit():
            return int(value.strip())
    return None


def _server_models() -> list[dict]:
    """What llama-server's router lists, cached briefly; [] when it does not answer."""
    import time
    global _models_cache
    if _models_cache and time.monotonic() - _models_cache[0] < MODELS_TTL:
        return _models_cache[1]
    try:
        resp = httpx.get(f"{chat_base_url()}/models", headers={"Authorization": f"Bearer {chat_api_key()}"},
                         timeout=5.0)
        resp.raise_for_status()
        data = resp.json().get("data") or []
    except Exception:
        return []
    _models_cache = (time.monotonic(), data)
    return data


def chat_models() -> list[dict]:
    """The models a chat may pick: [{id, reasoning, vision, tools, context, loaded, contexts?, ...}].

    With the model registry, its enabled chat models, each with the contexts users may pick and, per context, where
    it loads and how fast it answers (``registry_chat_models``). Without one, on llama.cpp, every model the router
    lists except the embedder and the vision preset (images go there by themselves); elsewhere (a hosted API lists
    everything it has), the configured chat model and the reasoning ones.
    """
    if rows := [r for r in _registry() if r["role"] == "chat" and r["enabled"] and r.get("complete", True)]:
        return registry_chat_models(rows)
    thinking, vision = reasoning_models(), vision_model()
    hidden = {embed_model(), vision}
    listed = _server_models() if is_llama_cpp(chat_base_url()) else []
    out = []
    for m in listed:
        mid = m.get("id") or ""
        if not mid or mid in hidden or "embed" in mid.lower():
            continue
        status = m.get("status") or {}
        modalities = (m.get("architecture") or {}).get("input_modalities") or []
        out.append({"id": mid, "reasoning": mid in thinking, "vision": "image" in modalities, "tools": True,
                    "context": _preset_context(status.get("preset")) or DEFAULT_CONTEXT,
                    "loaded": status.get("value") == "loaded" if isinstance(status, dict) else False})
    if not out:
        for mid in dict.fromkeys([chat_model()] + sorted(thinking)):
            out.append({"id": mid, "reasoning": mid in thinking, "vision": False, "tools": True,
                        "context": model_context(mid), "loaded": False})
    return out


def registry_chat_models(rows: list[dict]) -> list[dict]:
    """The registry's chat models as the picker shows them, with what each router has loaded now."""
    from athena.model_server import stats
    loaded = {m.get("id") for m in _server_models() + _cpu_models()
              if (m.get("status") or {}).get("value") == "loaded"}
    speeds = stats.estimates()
    out = []
    for r in rows:
        contexts, loaded_context = [], None
        for c in r["contexts"]:
            est = speeds.get(r["name"], {}).get(c["context"]) or {}
            is_loaded = c["preset"] in loaded or (c["vision_preset"] or "") in loaded
            loaded_context = c["context"] if is_loaded else loaded_context
            plan = c["plan"]
            contexts.append({"tokens": c["context"], "device": plan["device"], "gpu_layers": plan["gpu_layers"],
                             "layers": plan["layers"], "vram_mb": plan["vram_mb"], "ram_mb": plan["ram_mb"],
                             "fits": plan["fits"], "tps": round(est["tps"], 1) if est.get("tps") else None,
                             "prompt_tps": round(est["prompt_tps"]) if est.get("prompt_tps") else None,
                             "speed_source": est.get("source"), "load_seconds": round(est.get("load_seconds") or 0, 1),
                             "server": c["server"], "loaded": is_loaded})
        info = r["info"] or {}
        out.append({"id": r["name"], "reasoning": r["reasoning"], "vision": r["vision"], "tools": r["tools"],
                    "context": r["default_context"], "default_context": r["default_context"],
                    "loaded": loaded_context is not None, "loaded_context": loaded_context, "contexts": contexts,
                    "size_bytes": r["size_bytes"], "params": info.get("params"), "quant": info.get("quant"),
                    "architecture": info.get("architecture"), "placement": r["placement"]})
    return out


def _cpu_models() -> list[dict]:
    """What the CPU router lists (athena.model_server), cached like ``_server_models``; [] when it is not running."""
    import time
    global _cpu_cache
    if _cpu_cache and time.monotonic() - _cpu_cache[0] < MODELS_TTL:
        return _cpu_cache[1]
    from athena.model_server import registry
    try:
        resp = httpx.get(f"{server_root(registry.cpu_base_url())}/models", timeout=2.0)
        resp.raise_for_status()
        data = resp.json().get("data") or []
    except Exception:
        data = []
    _cpu_cache = (time.monotonic(), data)
    return data


class TextOnlyModel(ValueError):
    """Images were sent to a model without a vision projector."""


def chat_preset(model: str, context: int | None = None, images: bool = False) -> str:
    """The name a chat turn sends for ``model`` at ``context``: with the registry, the preset for that context (its
    vision preset when the message has images; TextOnlyModel when there is none). Without one, the model itself, or
    CHAT_VISION_MODEL for images."""
    for r in _registry():
        if r["name"] != model:
            continue
        contexts = {c["context"]: c for c in r["contexts"]}
        c = contexts.get(context or r["default_context"]) or contexts.get(r["default_context"]) or r["contexts"][0]
        if images:
            if not c["vision_preset"]:
                raise TextOnlyModel(f"{model} reads text only. Switch to a model that takes images to send them.")
            return c["vision_preset"]
        return c["preset"]
    return vision_model() if images else model


def model_context(model: str) -> int:
    """The context ``model`` (a preset name) was started with: the registry's, else its router preset's ctx-size,
    else CHAT_CONTEXT_TOKENS."""
    if found := _registry_preset(model):
        return found["context"]
    for m in _server_models() if is_llama_cpp(chat_base_url()) else []:
        if m.get("id") == model and (ctx := _preset_context((m.get("status") or {}).get("preset"))):
            return ctx
    try:
        return int(get_setting("CHAT_CONTEXT_TOKENS") or DEFAULT_CONTEXT)
    except ValueError:
        return DEFAULT_CONTEXT


def effort_extra(model: str, effort: str | None) -> tuple[dict, int]:
    """``extra_body`` for a chat turn at ``effort``, and the thinking budget it allows.

    A model that does not reason, or effort off, gets thinking switched off. On llama.cpp the effort is a thinking
    budget; a hosted API gets the OpenAI-style ``reasoning_effort`` instead.
    """
    budget = EFFORT_BUDGETS.get(effort or "off", 0) if model in reasoning_models() else 0
    if not is_llama_cpp(chat_base_url()):
        return ({"reasoning_effort": effort} if budget else {}), budget
    if not budget:
        return {"chat_template_kwargs": {"enable_thinking": False}}, 0
    return {"chat_template_kwargs": {"enable_thinking": True}, "reasoning_budget_tokens": budget,
            "reasoning_budget_message": BUDGET_MESSAGE}, budget


def chat_json(prompt: str, schema: dict, name: str, system: str | None = None, task: str | None = None,
              max_tokens: int = 300, timeout: float = 120.0, feature: str | None = None,
              user_id=None) -> tuple[dict | None, dict]:
    """One schema-constrained JSON answer at temperature 0 with thinking off.

    Returns (answer, usage); the answer is None when the reply does not parse. ``usage`` has the model and its
    input and output token counts, for logging and per-user allowances. With a ``feature`` the call is counted in
    the usage log, against ``user_id`` when someone asked for it.
    """
    import json

    from athena.core import usage as usage_log

    from athena.model_server import activity

    model = chat_model(task)
    messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    with activity.track(feature, model, user_id=user_id) as call:
        resp = chat_client(timeout=timeout, model=model).chat.completions.create(
            model=model, messages=messages, temperature=0, max_tokens=max_tokens,
            response_format={"type": "json_schema", "json_schema": {"name": name, "schema": schema}},
            extra_body=chat_extra(),
        )
        usage = {"model": model, "input_tokens": getattr(resp.usage, "prompt_tokens", 0) or 0,
                 "output_tokens": getattr(resp.usage, "completion_tokens", 0) or 0}
        call.tokens(usage["input_tokens"], usage["output_tokens"])
    if feature:
        usage_log.add(feature, model, usage["input_tokens"], usage["output_tokens"], user_id=user_id)
    try:
        answer = json.loads(resp.choices[0].message.content or "")
    except json.JSONDecodeError:
        return None, usage
    return (answer if isinstance(answer, dict) else None), usage


def cost(input_tokens: int, output_tokens: int, kind: str = "chat") -> float:
    """USD for a call at the configured prices; local models cost nothing. Embeddings have one price."""
    def price(key: str) -> float:
        try:
            return float(get_setting(key) or 0)
        except ValueError:
            return 0.0
    if kind == "embed":
        return input_tokens * price("EMBED_PRICE_PER_M") / 1_000_000
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


def embed(texts: list[str], instruct: str | None = None, timeout: float = 120.0, feature: str | None = None,
          user_id=None) -> np.ndarray:
    """Unit vectors of EMBED_DIM dimensions, one per text.

    ``instruct`` marks the texts as queries in Qwen3-Embedding's format; documents go in as they are. With a
    ``feature`` the call is counted in the usage log.
    """
    from athena.core import usage
    from athena.model_server import activity

    if instruct:
        texts = [f"Instruct: {instruct}\nQuery: {t}" for t in texts]
    url, model = embed_base_url(), embed_model()
    kwargs = {}
    if get_setting("EMBED_DIMENSIONS"):
        kwargs["dimensions"] = int(get_setting("EMBED_DIMENSIONS"))
    with activity.track(feature, model, kind="embed", user_id=user_id) as call:  # tokenizing loads the model too
        if is_llama_cpp(url):
            with httpx.Client(timeout=timeout) as http:
                def count(text: str) -> int:
                    resp = http.post(f"{server_root(url)}/tokenize", json={"content": text, "model": model})
                    resp.raise_for_status()
                    return len(resp.json()["tokens"])
                texts = [fit(t, EMBED_MAX_TOKENS, count)[0] for t in texts]
        client = OpenAI(base_url=url, api_key=embed_api_key(), timeout=timeout, max_retries=2)
        resp = client.embeddings.create(input=texts, model=model, **kwargs)
        call.tokens(usage.tokens_of(getattr(resp, "usage", None))[0])
    if feature:
        usage.add(feature, model, usage.tokens_of(resp.usage)[0], kind="embed", user_id=user_id)
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
