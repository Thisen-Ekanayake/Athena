"""
The model registry: the GGUF files an admin added in Settings → Models and keys, and the router presets written
from them (athena.model_server.presets).

The first time it runs, the registry takes in the hand-written ``config/llama-router.ini`` (the 9B, its vision
preset and the embedder), so nothing changes for a setup that never opens the page. From then on it writes
``config/llama-router.generated.ini`` (the GPU router) and ``config/llama-router.cpu.ini`` (the CPU router), which
run_native.sh starts llama-server with, and asks both routers to read them again.

``snapshot()`` is what the rest of Athena reads (athena.core.llm, the chat routes): every model with, per context,
its preset names, which router serves it and where it would load. It is cached for a few seconds per process.

Run ``python3 -m athena.model_server.registry`` to take in the hand-written file and write the presets (run_native.sh
does, before it starts the routers).
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx
from loguru import logger

from athena.model_server import gguf, gpu, presets

REPO = Path(__file__).resolve().parents[2]
CONFIG = REPO / "config"
BASE_FILE = CONFIG / "llama-router.ini"
GPU_FILE = CONFIG / "llama-router.generated.ini"
CPU_FILE = CONFIG / "llama-router.cpu.ini"
DEFAULT_CPU_URL = "http://127.0.0.1:8081/v1"
CONTEXT_STEPS = (8192, 16384, 32768, 65536)
SNAPSHOT_SECONDS = 10.0
HEADER = ("Written by Athena from the model registry (Settings -> Models and keys); edits here are overwritten.\n"
          "The hand-written presets it started from are in config/llama-router.ini.")

_snapshot: tuple[float, list[dict]] | None = None
_lock = threading.Lock()


# ── where things are ────────────────────────────────────────────────────


def cpu_base_url() -> str:
    from athena.core.config_store import get_setting
    return (get_setting("LLM_CPU_BASE_URL") or DEFAULT_CPU_URL).rstrip("/")


def writable() -> str | None:
    """None when the registry can write the router presets here; otherwise why not (Docker: the API container
    cannot see the host's files or the model server)."""
    if not BASE_FILE.exists():
        return ("The model server's presets are not on this machine (Athena runs in Docker), so models are added "
                "on the host: edit config/llama-router.ini there.")
    if not os.access(CONFIG, os.W_OK):
        return f"Athena cannot write to {CONFIG}."
    return None


def resolve(path: str) -> str:
    """A preset path as llama-server sees it (relative paths are from the repository root)."""
    return path if os.path.isabs(path) else str(REPO / path)


def fingerprint(path: str) -> str:
    st = os.stat(resolve(path))
    return f"{st.st_size}-{int(st.st_mtime)}"


def default_contexts(context_train: int | None, default: int) -> list[int]:
    ceiling = min(context_train or 32768, max(CONTEXT_STEPS))
    return sorted({c for c in CONTEXT_STEPS if c <= ceiling} | {default})


# ── taking in the hand-written presets ─────────────────────────────────


def seed(session) -> int:
    """Register the models in config/llama-router.ini when the registry is empty; returns how many."""
    from athena.core import llm
    from athena.database import model_registry as db
    if db.all_models(session) or not BASE_FILE.exists():
        return 0
    _, sections = presets.parse(BASE_FILE.read_text())
    sections = [s for s in sections if s.name != "*" and s.values.get("model")]
    thinking = llm.reasoning_models()
    added = 0
    for s in sections:
        if s.values.get("mmproj") and any(o is not s and o.values.get("model") == s.values["model"]
                                          and not o.values.get("mmproj") for o in sections):
            continue  # a vision preset: the projector joins the text preset with the same file below
        path = s.values["model"]
        try:
            info = gguf.describe(resolve(path))
        except (OSError, gguf.NotGGUF) as exc:
            logger.warning(f"Registry: {path} from {BASE_FILE.name} is not readable: {exc}")
            info = {}
        mmproj = s.values.get("mmproj") or next(
            (o.values["mmproj"] for o in sections if o.values.get("model") == path and o.values.get("mmproj")), None)
        embed = s.values.get("embedding", "").lower() == "true" or info.get("role") == "embed"
        context = int(s.values.get("ctx-size") or s.values.get("c") or 8192)
        options = {k: v for k, v in s.values.items() if k not in presets.OWN_KEYS and k != "no-mmproj-offload"}
        db.add_model(session, name=s.name, path=path, mmproj_path=None if embed else mmproj,
                     size_bytes=info.get("size_bytes") or 0,
                     mmproj_bytes=os.path.getsize(resolve(mmproj)) if mmproj and not embed and
                     os.path.exists(resolve(mmproj)) else None,
                     fingerprint=fingerprint(path) if os.path.exists(resolve(path)) else "", info=info,
                     role="embed" if embed else "chat", reasoning=s.name in thinking,
                     tools=bool(info.get("tools", True)), placement="auto",
                     contexts=[context] if embed else default_contexts(info.get("context_train"), context),
                     default_context=context, options=options, plans={}, enabled=True)
        added += 1
    logger.info(f"Registry: took in {added} models from {BASE_FILE.name}")
    return added


# ── plans and presets ──────────────────────────────────────────────────


def layers_of(m) -> int:
    return int((m.info or {}).get("layers") or 32) + 1  # llama.cpp counts the output layer


def plan_for(m, context: int, info: dict | None) -> dict:
    """Where ``m`` loads at ``context`` (athena.model_server.gpu.plan), from its measured projections when it has
    them, else from the GGUF header."""
    points = (m.plans or {}).get("points") if (m.plans or {}).get("fingerprint") == m.fingerprint else None
    projected = gpu.projection(points or [], context)
    if projected is None:
        full, zero = gpu.estimate(m.info or {}, m.size_bytes or 0, context)
        projected = (float(full), float(zero))
    plan = gpu.plan(layers=layers_of(m), size_bytes=m.size_bytes or 0, placement=m.placement,
                    full_mb=projected[0], zero_mb=projected[1], info=info)
    plan["measured"] = bool(points)
    return plan


def measure(model_id) -> None:
    """Project the model's memory with llama-fit-params at its smallest and largest context (two runs; the rest
    follow from them) and keep the result. Runs off the request: each run takes a few seconds."""
    from athena.database import model_registry as db
    from athena.database.db import SessionLocal
    with SessionLocal() as session:
        m = db.get_model(session, model_id)
        if m is None:
            return
        targets = sorted({min(m.contexts or [m.default_context]), max(m.contexts or [m.default_context])})
        points = []
        for context in targets:
            got = gpu.measure(resolve(m.path), context, cwd=str(REPO))
            if got:
                points.append([context, got[0], got[1]])
        if points:
            db.update_model(session, m, plans={"fingerprint": m.fingerprint, "points": points})
            logger.info(f"Registry: projected {m.name}: {points}")
    invalidate()
    write_presets()


def prepare(model_id, benchmark: bool = True) -> None:
    """After a model is added or changed: project its memory, rewrite the presets, then benchmark the contexts
    it has no speed for yet."""
    measure(model_id)
    if benchmark:
        from athena.model_server import bench
        bench.run(str(model_id))


def prepare_soon(model_id, benchmark: bool = True) -> None:
    threading.Thread(target=_quietly, args=(prepare, model_id, benchmark), daemon=True,
                     name=f"prepare-{model_id}").start()


def _quietly(fn, *args) -> None:
    try:
        fn(*args)
    except Exception as exc:
        logger.warning(f"Registry: {fn.__name__} failed: {exc}")


def server_for(plan: dict) -> str:
    return "cpu" if plan["device"] == "cpu" else "gpu"


def build(models: list, info: dict | None) -> list[dict]:
    """The snapshot rows for ``models`` (see ``snapshot``)."""
    out = []
    for m in models:
        contexts = sorted(set(m.contexts or [m.default_context]) | {m.default_context})
        rows = []
        for context in contexts:
            plan = plan_for(m, context, info)
            rows.append({"context": context, "plan": plan, "server": server_for(plan),
                         "preset": presets.preset_name(m.name, context, m.default_context),
                         "vision_preset": presets.preset_name(m.name, context, m.default_context, vision=True)
                         if m.mmproj_path else None})
        out.append({"id": str(m.id), "name": m.name, "path": m.path, "mmproj_path": m.mmproj_path,
                    "size_bytes": m.size_bytes or 0, "mmproj_bytes": m.mmproj_bytes, "fingerprint": m.fingerprint,
                    "info": m.info or {}, "role": m.role, "reasoning": bool(m.reasoning), "tools": bool(m.tools),
                    "vision": bool(m.mmproj_path), "placement": m.placement, "default_context": m.default_context,
                    "contexts": rows, "options": m.options or {}, "enabled": bool(m.enabled),
                    "layers": layers_of(m)})
    return out


def render(rows: list[dict]) -> dict[str, str]:
    """The text of both preset files for snapshot rows: {"gpu": ..., "cpu": ...}."""
    top: dict[str, str] = {"version": "1"}
    common = {"parallel": "1"}
    if BASE_FILE.exists():
        base_top, base_sections = presets.parse(BASE_FILE.read_text())
        top |= base_top
        star = next((s for s in base_sections if s.name == "*"), None)
        if star:
            common = {k: v for k, v in star.values.items() if k not in ("n-gpu-layers", "ngl")}
    files: dict[str, list] = {"gpu": [presets.Section("*", dict(common))], "cpu": [presets.Section("*", dict(common))]}
    for r in rows:
        if not r["enabled"]:
            continue
        template = (r["info"] or {}).get("has_template", True)
        for c in r["contexts"]:
            kwargs = {"path": r["path"], "context": c["context"], "role": r["role"], "placement": r["placement"],
                      "device": c["plan"]["device"], "options": r["options"], "template": template}
            files[c["server"]].append(presets.section(name=c["preset"], **kwargs))
            if c["vision_preset"]:
                files[c["server"]].append(presets.section(name=c["vision_preset"], mmproj=r["mmproj_path"], **kwargs))
    return {k: presets.render(top, v, HEADER) for k, v in files.items()}


def write_presets(reload: bool = True) -> dict:
    """Write both preset files from the registry and, when one changed, ask its router to read it again."""
    from athena.database import model_registry as db
    from athena.database.db import SessionLocal
    if writable():
        return {"changed": False}
    with _lock, SessionLocal() as session:
        seed(session)
        texts = render(build(db.all_models(session), gpu.gpu()))
    changed = {"gpu": presets.write_atomic(str(GPU_FILE), texts["gpu"]),
               "cpu": presets.write_atomic(str(CPU_FILE), texts["cpu"])}
    invalidate()
    if reload:
        from athena.core import llm
        for kind, url in (("gpu", llm.chat_base_url()), ("cpu", cpu_base_url())):
            if changed[kind]:
                reload_router(url)
    return {"changed": any(changed.values()), **changed}


def reload_router(url: str) -> bool:
    """Ask a router to read its preset file again; False when it does not answer."""
    from athena.core import llm
    try:
        httpx.get(f"{llm.server_root(url)}/models", params={"reload": "1"}, timeout=10.0).raise_for_status()
        return True
    except httpx.HTTPError as exc:
        logger.info(f"Registry: the router at {url} did not reload: {exc}")
        return False


# ── what the rest of Athena reads ──────────────────────────────────────


def invalidate() -> None:
    global _snapshot
    _snapshot = None


def snapshot() -> list[dict]:
    """Every registered model (see ``build``), cached briefly; [] without a database or registry."""
    global _snapshot
    if _snapshot and time.monotonic() - _snapshot[0] < SNAPSHOT_SECONDS:
        return _snapshot[1]
    try:
        from athena.database import model_registry as db
        from athena.database.db import SessionLocal
        with SessionLocal() as session:
            rows = build(db.all_models(session), gpu.gpu())
    except Exception as exc:
        logger.debug(f"Registry unavailable: {exc}")
        rows = []
    _snapshot = (time.monotonic(), rows)
    return rows


def find(model: str) -> dict | None:
    return next((r for r in snapshot() if r["name"] == model), None)


def preset_info(preset: str) -> dict | None:
    """{model, context, vision, server, plan} for a preset name, or None when the registry does not know it."""
    for r in snapshot():
        for c in r["contexts"]:
            if preset in (c["preset"], c["vision_preset"]):
                return {"model": r["name"], "context": c["context"], "vision": preset == c["vision_preset"],
                        "server": c["server"], "plan": c["plan"], "row": r}
    return None


def is_local(url: str) -> bool:
    return (urlparse(url).hostname or "") in ("127.0.0.1", "localhost", "::1", "host.docker.internal")


if __name__ == "__main__":
    print(write_presets(reload=False))
