"""
What the model servers are doing (admin), under the model registry in Settings → Models and keys.

GET    /api/v1/models/activity           — the loaded models with their slots (tokens, speed, context in use), calls
                                           in flight, the chat lane, what waits, queued work, recent calls, swaps
                                           and today's totals per feature (athena.model_server.activity)
POST   /api/v1/models/activity/pause     — hold background model work (summaries, cluster labels, feed embeddings,
                                           the maps' lane) until resumed
POST   /api/v1/models/activity/resume
"""
from __future__ import annotations

import time
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from athena.api import auth
from athena.api.deps import get_db
from athena.core import llm
from athena.core.models import User
from athena.model_server import activity, gpu, lane, loading, registry

router = APIRouter(prefix="/api/v1/models/activity", tags=["Model registry"])

# Work that waits in a queue for the model: (label, queues).
QUEUES = [
    ("Feed summaries", ["summary_urgent", "summary_standard", "summary_lazy"]),
    ("Cluster labels", ["summary_cluster"]),
    ("Feed items to embed", ["athena:embedding_queue"]),
    ("Map jobs", ["evolution"]),
]
# What the summary worker, the minute runs and the maps' lane count as: what a pause holds.
BACKGROUND = {"summary", "cluster_label", "feed_embed", "map_build", "map_embed"}
RECENT_SECONDS = 120.0

# The last reading of each slot, to work out tokens per second between two polls: (url, preset, slot) -> (task,
# tokens decoded, time).
_samples: dict[tuple[str, str, int], tuple[int, int, float]] = {}


def _slots(url: str, preset: str) -> list[dict]:
    """llama-server's slots for a loaded preset; never asks the router to load it."""
    try:
        resp = httpx.get(f"{llm.server_root(url)}/slots", params={"model": preset, "autoload": "false"}, timeout=1.5)
        resp.raise_for_status()
        raw = resp.json()
    except (httpx.HTTPError, ValueError):
        return []
    now, out = time.monotonic(), []
    for s in raw if isinstance(raw, list) else []:
        token = (s.get("next_token") or [{}])[0]
        decoded, task = int(token.get("n_decoded") or 0), s.get("id_task")
        key = (url, preset, int(s.get("id", 0)))
        tps = None
        if s.get("is_processing") and (last := _samples.get(key)) and last[0] == task and now > last[2]:
            tps = round(max(decoded - last[1], 0) / (now - last[2]), 1)
        _samples[key] = (task, decoded, now)
        prompt = int(s.get("n_prompt_tokens") or 0)
        out.append({"id": s.get("id"), "processing": bool(s.get("is_processing")), "context": s.get("n_ctx"),
                    "prompt_tokens": prompt, "prompt_done": int(s.get("n_prompt_tokens_processed") or 0),
                    "prompt_cached": int(s.get("n_prompt_tokens_cache") or 0), "decoded": decoded,
                    "max_tokens": s.get("n_predict") if (s.get("n_predict") or -1) > 0 else None,
                    "in_context": prompt + decoded, "tps": tps})
    return out


def _servers() -> list[dict]:
    out = []
    for kind, url in (("gpu", llm.chat_base_url()), ("cpu", registry.cpu_base_url())):
        listed = loading.router_models(url)
        models = []
        for m in listed:
            status = ((m.get("status") or {}).get("value"))
            if status not in ("loaded", "loading"):
                continue
            preset = m.get("id")
            found = registry.preset_info(preset) or {}
            plan = found.get("plan") or {}
            models.append({"preset": preset, "model": found.get("model") or preset, "status": status,
                           "context": found.get("context"), "vision": bool(found.get("vision")),
                           "device": plan.get("device"), "gpu_layers": plan.get("gpu_layers"),
                           "layers": plan.get("layers"), "vram_mb": plan.get("vram_mb"), "ram_mb": plan.get("ram_mb"),
                           "slots": _slots(url, preset) if status == "loaded" else []})
        out.append({"server": kind, "url": url, "online": bool(listed), "models": models})
    return out


def _queues() -> list[dict]:
    try:
        r = activity._redis()
        return [{"label": label, "count": sum(int(r.llen(k) or 0) for k in keys)} for label, keys in QUEUES]
    except Exception:
        return []


def _names(session: Session, rows: list[dict]) -> dict[str, str]:
    ids = {r["user_id"] for r in rows if r.get("user_id")}
    if not ids:
        return {}
    found = session.execute(select(User.id, User.display_name).where(User.id.in_([UUID(i) for i in ids]))).all()
    return {str(i): name for i, name in found}


def _named(rows: list[dict], names: dict[str, str]) -> list[dict]:
    return [r | {"label": activity.label(r.get("feature") or "other"), "user": names.get(r.get("user_id") or ""),
                 "background": r.get("feature") in BACKGROUND} for r in rows]


def reloads(presets: set[str]) -> list[str]:
    """Background work that used one of ``presets`` in the last two minutes, and so will load it again unless
    background work is paused: its features' names."""
    if lane.paused():
        return []
    since = time.time() - RECENT_SECONDS
    features = {r["feature"] for r in activity.recent() + activity.live()
                if r.get("model") in presets and r.get("feature") in BACKGROUND and r.get("started", 0) >= since}
    return sorted(activity.label(f) for f in features)


@router.get("")
def model_activity(session: Session = Depends(get_db), user: User = Depends(auth.require_admin)):
    live, recent = activity.live(), activity.recent()
    names = _names(session, live + recent)
    holder = lane.holder()
    return {"servers": _servers(), "gpu": gpu.gpu(), "calls": _named(live, names),
            "lane": {"holder": holder, "paused": lane.paused(),
                     "waiting": [w | {"label": activity.label(w.get("who") or "background")} for w in lane.waiting()]},
            "queues": _queues(), "recent": _named(recent, names),
            "swaps": [s | {"cause_label": "Unloaded by an admin" if s["cause"] == "unload"
                           else activity.label(s["cause"])} for s in activity.swaps()],
            "today": activity.today(), "now": time.time()}


@router.post("/pause")
def pause(user: User = Depends(auth.require_admin)):
    return {"paused": lane.pause(by=user.display_name)}


@router.post("/resume")
def resume(user: User = Depends(auth.require_admin)):
    lane.resume()
    return {"paused": None}
