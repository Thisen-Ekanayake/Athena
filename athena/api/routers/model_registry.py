"""
The model registry (admin): the GGUF files the local model server serves, where each loads and how fast it runs
(athena.model_server). Settings → Models and keys.

GET    /api/v1/models                    — every model with its contexts (device, memory, speed, router status),
                                           the GPU, both routers, the running benchmark and the model folders
GET    /api/v1/models/browse?path=       — a folder's folders and .gguf files, and the places to start from
POST   /api/v1/models/inspect            — {path}: what the file says, with a name, projector and contexts to suggest
POST   /api/v1/models                    — {path, name, mmproj_path?, role, reasoning, tools, placement, contexts,
                                           default_context}: register it; it is measured and benchmarked next
PATCH  /api/v1/models/{id}               — any of those but path, or {enabled}
DELETE /api/v1/models/{id}
POST   /api/v1/models/{id}/benchmark     — {force}: measure its speed again (only missing contexts without force)
POST   /api/v1/models/{id}/default       — make a chat model the default (LLM_CHAT_MODEL)
POST   /api/v1/models/{id}/unload        — take it out of GPU or CPU memory now; says which background work
                                           (summaries, ...) used it lately and will load it again unless paused

Turning the default chat model off makes another chat model the default; turning any model off unloads it.
"""
from __future__ import annotations

import os
import re
import time
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from athena.api import auth
from athena.api.deps import get_db
from athena.api.routers import model_activity
from athena.core import llm
from athena.core.models import User
from athena.database import model_registry as db
from athena.model_server import bench, files, gguf, gpu, loading, presets, registry, stats

router = APIRouter(prefix="/api/v1/models", tags=["Model registry"])

NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,59}$")
MIN_CONTEXT, MAX_CONTEXTS = 512, 8


class ModelFields(BaseModel):
    name: str | None = Field(None, max_length=60)
    mmproj_path: str | None = Field(None, max_length=1000)
    role: Literal["chat", "embed"] | None = None
    reasoning: bool | None = None
    tools: bool | None = None
    placement: Literal["auto", "gpu", "cpu"] | None = None
    contexts: list[int] | None = Field(None, max_length=MAX_CONTEXTS)
    default_context: int | None = None
    enabled: bool | None = None


class ModelAdd(ModelFields):
    path: str = Field(..., max_length=1000)


class PathBody(BaseModel):
    path: str = Field(..., max_length=1000)


class BenchBody(BaseModel):
    force: bool = False


def _writable() -> None:
    if reason := registry.writable():
        raise HTTPException(status_code=409, detail=reason)


def _describe(path: str, kind: str = "model") -> dict:
    """The GGUF file's header; ``info["path"]`` is the resolved path that was checked, the one to use from here."""
    try:
        path = files.checked(path)
    except PermissionError:
        path = None
    if path is None or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="No .gguf file there (system folders are never read)")
    try:
        info = gguf.describe(path, check=kind == "model")
    except (OSError, gguf.NotGGUF) as exc:
        raise HTTPException(status_code=422, detail=f"Not a model llama.cpp can load: {exc}")
    if info["kind"] != kind:
        raise HTTPException(status_code=422, detail="That is a vision projector, not a model" if kind == "model"
                            else "That file is a model, not a vision projector")
    info["size_bytes"] = files.total_size(path)
    return info


def _contexts(contexts: list[int] | None, default: int | None, info: dict, role: str) -> tuple[list[int], int]:
    trained = info.get("context_train") or 1_048_576
    default = default or (min(16384, trained) if role == "chat" else min(2048, trained))
    contexts = sorted({c for c in (contexts or registry.default_contexts(trained, default)) if c} | {default})
    if role == "embed":
        contexts = [default]
    if any(c < MIN_CONTEXT or c > trained for c in contexts):
        raise HTTPException(status_code=422, detail=f"Contexts must be between {MIN_CONTEXT} and the {trained:,} "
                                                    "tokens the model was trained for")
    if len(contexts) > MAX_CONTEXTS:
        raise HTTPException(status_code=422, detail=f"At most {MAX_CONTEXTS} context sizes")
    return contexts, default


def _check_name(session: Session, name: str, model_id=None) -> str:
    name = name.strip().lower()
    if not NAME.match(name) or name.endswith(presets.VISION_SUFFIX):
        raise HTTPException(status_code=422, detail="Names use lower-case letters, digits, dots and dashes, and "
                                                    "do not end in -vision")
    other = db.by_name(session, name)
    if other is not None and other.id != model_id:
        raise HTTPException(status_code=409, detail=f"A model is already called {name}")
    return name


def _incomplete(info: dict) -> str:
    have, need = info.get("size_bytes") or 0, info.get("needed_bytes") or 0
    return (f"This file is incomplete: it holds {have / 1e9:.1f} GB of the {need / 1e9:.1f} GB its weights need, "
            "so llama.cpp cannot load it. A download was probably cut short; download it again.")


def _uses(name: str) -> list[str]:
    """What background work sends this model's name (its settings in the form below)."""
    out = []
    if llm.chat_model() == name:
        out.append("default chat model")
    if llm.embed_model() == name:
        out.append("embeddings")
    for task, label in (("summary", "summaries"), ("qa", "Q&A"), ("lit_review", "literature reviews")):
        if llm.chat_model(task) == name and llm.chat_model() != name:
            out.append(label)
    return out


def _view() -> dict:
    registry.invalidate()
    stats.invalidate()
    rows = registry.snapshot()
    speeds = stats.estimates()
    gpu_url, cpu_url = llm.chat_base_url(), registry.cpu_base_url()
    listed = {"gpu": loading.router_models(gpu_url), "cpu": loading.router_models(cpu_url)}
    status = {m.get("id"): ((m.get("status") or {}).get("value"), (m.get("status") or {}).get("failed"))
              for kind in listed for m in listed[kind]}
    benches = stats.benches()
    out = []
    for r in rows:
        mine = [b for b in benches if b["model_id"] == r["id"]]
        contexts = []
        for c in r["contexts"]:
            est = speeds.get(r["name"], {}).get(c["context"]) or {}
            st = status.get(c["preset"])
            contexts.append({"tokens": c["context"], "preset": c["preset"], "vision_preset": c["vision_preset"],
                             "server": c["server"], **c["plan"],
                             "tps": est.get("tps"), "prompt_tps": est.get("prompt_tps"),
                             "speed_source": est.get("source"), "load_seconds": est.get("load_seconds"),
                             "samples": next((b["samples"] for b in mine if b["context"] == c["context"]), 0),
                             "status": "failed" if st and st[1] else (st[0] if st else None)})
        exists = os.path.exists(registry.resolve(r["path"]))
        changed = exists and registry.fingerprint(r["path"]) != r["fingerprint"]
        whole = registry.completeness(r["path"], r["fingerprint"]) if exists else {}
        trained = (r["info"] or {}).get("context_train") or 32768
        out.append({k: r[k] for k in ("id", "name", "path", "mmproj_path", "size_bytes", "mmproj_bytes", "info",
                                      "role", "reasoning", "tools", "vision", "placement", "default_context",
                                      "enabled", "layers")}
                   | {"contexts": contexts, "exists": exists, "changed": changed, "used_for": _uses(r["name"]),
                      "benchmarked": any(b["source"] == "benchmark" for b in mine),
                      "complete": r["complete"], "needed_bytes": whole.get("needed_bytes"),
                      "is_default": r["role"] == "chat" and llm.chat_model() == r["name"],
                      "loaded": any(c["status"] in ("loaded", "loading") for c in contexts),
                      "last_benchmark": bench.last(r["id"]),
                      "context_steps": sorted({c for c in registry.ALL_STEPS if c <= trained}
                                              | {c["tokens"] for c in contexts})})
    wanted = {"gpu": set(), "cpu": set()}
    for r in rows:
        if r["enabled"]:
            for c in r["contexts"]:
                wanted[c["server"]].update(p for p in (c["preset"], c["vision_preset"]) if p)
    servers = {}
    for kind, url in (("gpu", gpu_url), ("cpu", cpu_url)):
        ids = {m.get("id") for m in listed[kind]}
        loaded = [m.get("id") for m in listed[kind] if (m.get("status") or {}).get("value") == "loaded"]
        servers[kind] = {"url": url, "online": bool(listed[kind]), "serves_registry": wanted[kind] <= ids,
                         "missing": sorted(wanted[kind] - ids)[:5], "loaded": loaded}
    return {"models": out, "gpu": gpu.gpu(), "servers": servers, "benchmark": bench.status(),
            "writable": registry.writable() is None, "read_only_reason": registry.writable(),
            "fit_tool": gpu.fit_binary() is not None, "roots": files.roots(), "margin_mb": gpu.MARGIN_MB}


@router.get("")
def list_models(user: User = Depends(auth.require_admin)):
    return _view()


@router.get("/browse")
def browse(path: str | None = None, user: User = Depends(auth.require_admin)):
    try:
        return files.browse(path)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="No such folder")


@router.post("/inspect")
def inspect(body: PathBody, session: Session = Depends(get_db), user: User = Depends(auth.require_admin)):
    info = _describe(body.path)
    name = gguf.suggested_name(info)
    base, n = name, 2
    while db.by_name(session, name) is not None:
        name, n = f"{base}-{n}", n + 1
    contexts, default = _contexts(None, None, info, info["role"])
    projectors = files.projectors_for(info["path"], info) if info["role"] == "chat" else []
    preview = []
    for c in contexts:
        full, zero = gpu.estimate(info, info["size_bytes"], c)
        plan = gpu.plan(layers=(info.get("layers") or 32) + 1, size_bytes=info["size_bytes"], placement="auto",
                        full_mb=full, zero_mb=zero, info=gpu.gpu())
        preview.append({"tokens": c, **plan})
    taken = [r["path"] for r in registry.snapshot() if os.path.realpath(registry.resolve(r["path"])) == info["path"]]
    return {"info": info, "name": name, "contexts": contexts, "default_context": default, "projectors": projectors,
            "reasoning": info["thinks"], "tools": info["tools"], "preview": preview, "already": bool(taken)}


@router.post("", status_code=201)
def add_model(body: ModelAdd, session: Session = Depends(get_db), user: User = Depends(auth.require_admin)):
    _writable()
    info = _describe(body.path)
    if not info.get("complete", True):
        raise HTTPException(status_code=422, detail=_incomplete(info))
    role = body.role or info["role"]
    name = _check_name(session, body.name or gguf.suggested_name(info))
    mmproj = None
    if body.mmproj_path and role == "chat":
        mmproj = _describe(body.mmproj_path, "mmproj")
    contexts, default = _contexts(body.contexts, body.default_context, info, role)
    options = {"embedding": "true", "pooling": "last" if info.get("architecture", "").startswith("qwen") else "mean",
               "batch-size": "2048", "ubatch-size": "2048"} if role == "embed" else {}
    m = db.add_model(session, name=name, path=info["path"], mmproj_path=mmproj and mmproj["path"],
                     size_bytes=info["size_bytes"], mmproj_bytes=mmproj and mmproj["size_bytes"],
                     fingerprint=registry.fingerprint(info["path"]), info=info, role=role,
                     reasoning=info["thinks"] if body.reasoning is None else body.reasoning,
                     tools=info["tools"] if body.tools is None else body.tools, placement=body.placement or "auto",
                     contexts=contexts, default_context=default, options=options, plans={},
                     enabled=True if body.enabled is None else body.enabled)
    registry.invalidate()
    registry.write_presets()
    registry.prepare_soon(m.id, benchmark=role == "chat")
    return next(x for x in _view()["models"] if x["id"] == str(m.id))


@router.patch("/{model_id}")
def update_model(model_id: UUID, body: ModelFields, session: Session = Depends(get_db),
                 user: User = Depends(auth.require_admin)):
    _writable()
    m = db.get_model(session, model_id)
    if m is None:
        raise HTTPException(status_code=404, detail="Model not found")
    fields: dict = {}
    if body.name is not None and body.name.strip().lower() != m.name:
        if _uses(m.name):
            raise HTTPException(status_code=409, detail=f"{m.name} is used for {', '.join(_uses(m.name))}; point "
                                                        "those at another model before renaming it")
        fields["name"] = _check_name(session, body.name, m.id)
    role = body.role or m.role
    if body.role is not None:
        fields["role"] = role
    if body.mmproj_path is not None:
        fields["mmproj_path"], fields["mmproj_bytes"] = None, None
        if body.mmproj_path and role == "chat":
            proj = _describe(body.mmproj_path, "mmproj")
            fields["mmproj_path"], fields["mmproj_bytes"] = proj["path"], proj["size_bytes"]
    for key in ("reasoning", "tools", "placement", "enabled"):
        if (value := getattr(body, key)) is not None:
            fields[key] = value
    if body.enabled is False and m.enabled:
        _hand_over(session, m)
    remeasure = False
    if body.contexts is not None or body.default_context is not None or body.role is not None:
        contexts, default = _contexts(body.contexts if body.contexts is not None else m.contexts,
                                      body.default_context or m.default_context, m.info or {}, role)
        points = [p[0] for p in (m.plans or {}).get("points", [])]
        remeasure = bool(points) and (min(contexts) < min(points) or max(contexts) > max(points))
        # The default context keeps the model's own name, so background work follows a new default.
        fields["contexts"], fields["default_context"] = contexts, default
    if os.path.exists(registry.resolve(m.path)) and registry.fingerprint(m.path) != m.fingerprint:
        fields["fingerprint"], remeasure = registry.fingerprint(m.path), True
        fields["size_bytes"] = files.total_size(registry.resolve(m.path))
    row = registry.find(m.name)
    db.update_model(session, m, **fields)
    if body.enabled is False and row:
        loading.unload(row)  # off: out of memory now, not when the router next needs the room
    registry.invalidate()
    registry.write_presets()
    if remeasure or "contexts" in fields:
        registry.prepare_soon(m.id, benchmark=m.role == "chat" and m.enabled)
    return next(x for x in _view()["models"] if x["id"] == str(m.id))


def _hand_over(session: Session, m) -> None:
    """Before ``m`` goes off or away: background work stops naming it. The default chat model passes to another
    chat model; task overrides naming it go back to the default. The embedder cannot go: every stored vector came
    from it."""
    from athena.core.config_store import set_setting
    if llm.embed_model() == m.name:
        raise HTTPException(status_code=409, detail=f"{m.name} makes the embeddings; switching it means re-embedding "
                                                    "everything (Embeddings, below)")
    if llm.chat_model() == m.name:
        others = [r for r in registry.snapshot() if r["role"] == "chat" and r["enabled"] and r.get("complete", True)
                  and r["name"] != m.name]
        if not others:
            raise HTTPException(status_code=409, detail=f"{m.name} is the only chat model; add or turn on another "
                                                        "first, since summaries and Q&A need one")
        set_setting("LLM_CHAT_MODEL", others[0]["name"])
    for task in ("SUMMARY", "QA", "LIT_REVIEW"):
        if llm.chat_model(task.lower()) == m.name:
            set_setting(f"LLM_{task}_MODEL", "")


@router.delete("/{model_id}", status_code=204)
def remove_model(model_id: UUID, session: Session = Depends(get_db), user: User = Depends(auth.require_admin)):
    _writable()
    m = db.get_model(session, model_id)
    if m is None:
        raise HTTPException(status_code=404, detail="Model not found")
    _hand_over(session, m)
    if row := registry.find(m.name):
        loading.unload(row)
    db.remove_model(session, m)
    registry.invalidate()
    registry.write_presets()


@router.post("/{model_id}/benchmark", status_code=202)
async def benchmark(model_id: UUID, body: BenchBody, session: Session = Depends(get_db),
                    user: User = Depends(auth.require_admin)):
    m = db.get_model(session, model_id)
    if m is None:
        raise HTTPException(status_code=404, detail="Model not found")
    if m.role != "chat":
        raise HTTPException(status_code=422, detail="Only chat models are benchmarked")
    running = bench.status()
    if running and running.get("state") == "running" and time.time() - running.get("at", 0) < 900:
        raise HTTPException(status_code=409, detail=f"{running.get('model')} is being benchmarked")
    await run_in_threadpool(bench.start, str(m.id), body.force)
    return {"started": True}


@router.post("/{model_id}/default")
def make_default(model_id: UUID, session: Session = Depends(get_db), user: User = Depends(auth.require_admin)):
    """The chat model new chats start with and background work (summaries, Q&A, titles) uses."""
    from athena.core.config_store import set_setting
    m = db.get_model(session, model_id)
    if m is None:
        raise HTTPException(status_code=404, detail="Model not found")
    if m.role != "chat":
        raise HTTPException(status_code=422, detail="Only a chat model can be the default; the embedding model is set "
                                                    "under Embeddings below")
    if not m.enabled:
        db.update_model(session, m, enabled=True)
        registry.invalidate()
        registry.write_presets()
    set_setting("LLM_CHAT_MODEL", m.name)
    registry.invalidate()
    return next(x for x in _view()["models"] if x["id"] == str(m.id))


@router.post("/{model_id}/unload")
def unload_model(model_id: UUID, session: Session = Depends(get_db), user: User = Depends(auth.require_admin)):
    m = db.get_model(session, model_id)
    if m is None:
        raise HTTPException(status_code=404, detail="Model not found")
    row = registry.find(m.name)
    unloaded = loading.unload(row) if row else []
    # Background work that keeps using the model loads it straight back; the page offers to pause it.
    return {"unloaded": unloaded, "reloaded_by": model_activity.reloads(set(unloaded))}
