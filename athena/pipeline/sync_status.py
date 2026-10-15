"""One sync's progress and log, kept in Redis so any page, and a reload, can show it.

A sync is one crawl_source task per active source. Its keys, kept for a day after it starts:

- ``athena:sync:current``: the latest sync's id
- ``athena:sync:running``: that id while the sync runs; it expires when no source reports for RUNNING_TTL
- ``athena:sync:<id>``: hash of started_at, finished_at, trigger, total and the counts below
- ``athena:sync:<id>:sources``: hash of source id -> JSON {name, state, expected, started_at, ...}
- ``athena:sync:<id>:log``: the sync's log lines as JSON {seq, line}, the last LOG_LINES of them

Every source moves queued -> running (-> retrying -> running) -> done | empty | error, and only its own
task writes its entry, so the hash needs no locking. The counters are HINCRBY, so the task that brings
``completed`` up to ``total`` is the one that closes the sync.
"""
from __future__ import annotations

import json
import time
import uuid

PREFIX = "athena:sync"
CURRENT = f"{PREFIX}:current"
RUNNING = f"{PREFIX}:running"
KEEP = 24 * 3600            # a sync's keys outlive it by a day, so its result and log stay readable
RUNNING_TTL = 30 * 60       # a sync no source has reported on for this long counts as stalled
LOG_LINES = 1000
DEFAULT_EXPECTED = 10.0     # seconds, for a source with no fetch history
WAITING_AFTER = 30          # seconds without any source starting before the UI says the worker is idle
FINISHED = {"done", "empty", "error"}


def _s(v) -> str | None:
    return v.decode() if isinstance(v, bytes) else v


def _key(sync_id: str, part: str = "") -> str:
    return f"{PREFIX}:{sync_id}{':' + part if part else ''}"


def running(r) -> str | None:
    """The id of the sync that is running, if any."""
    return _s(r.get(RUNNING))


def start(r, sources: list[tuple[str, str, float | None]], trigger: str) -> str | None:
    """Open a sync over ``sources`` (id, name, expected seconds); None when one is already running."""
    sync_id = uuid.uuid4().hex[:12]
    if not r.set(RUNNING, sync_id, nx=True, ex=RUNNING_TTL):
        return None
    now = time.time()
    r.hset(_key(sync_id), mapping={
        "started_at": now, "trigger": trigger, "total": len(sources),
        "completed": 0, "errors": 0, "empty": 0, "new_items": 0,
    })
    for source_id, name, expected in sources:
        r.hset(_key(sync_id, "sources"), source_id, json.dumps(
            {"name": name, "state": "queued", "expected": max(2.0, expected or DEFAULT_EXPECTED)}))
    for part in ("", "sources"):
        r.expire(_key(sync_id, part), KEEP)
    r.set(CURRENT, sync_id, ex=KEEP)
    return sync_id


def source_ids(r, sync_id: str) -> list[str]:
    return [_s(k) for k in r.hgetall(_key(sync_id, "sources"))]


def _source(r, sync_id: str, source_id: str) -> dict | None:
    raw = r.hget(_key(sync_id, "sources"), source_id)
    return json.loads(_s(raw)) if raw else None


def _put(r, sync_id: str, source_id: str, entry: dict) -> None:
    r.hset(_key(sync_id, "sources"), source_id, json.dumps(entry))
    if running(r) == sync_id:
        r.expire(RUNNING, RUNNING_TTL)  # still alive


def source_started(r, sync_id: str | None, source_id: str) -> None:
    entry = sync_id and _source(r, sync_id, source_id)
    if not entry or entry["state"] in FINISHED:
        return
    entry.update(state="running", started_at=time.time())
    entry.pop("retry_at", None)
    _put(r, sync_id, source_id, entry)


def source_retrying(r, sync_id: str | None, source_id: str, error: str, retry_at: float) -> None:
    entry = sync_id and _source(r, sync_id, source_id)
    if not entry or entry["state"] in FINISHED:
        return
    entry.update(state="retrying", error=error, retry_at=retry_at)
    _put(r, sync_id, source_id, entry)


def source_finished(r, sync_id: str | None, source_id: str, outcome: str, new: int = 0,
                    error: str | None = None) -> None:
    """Record a source's outcome (done, empty or error); the last one to finish closes the sync."""
    entry = sync_id and _source(r, sync_id, source_id)
    if not entry or entry["state"] in FINISHED:
        return
    entry.update(state=outcome, finished_at=time.time(), new=new, error=error)
    entry.pop("retry_at", None)
    _put(r, sync_id, source_id, entry)
    key = _key(sync_id)
    if new:
        r.hincrby(key, "new_items", new)
    if outcome == "error":
        r.hincrby(key, "errors", 1)
    elif outcome == "empty":
        r.hincrby(key, "empty", 1)
    completed = r.hincrby(key, "completed", 1)
    if completed >= int(_s(r.hget(key, "total")) or 0):
        r.hset(key, "finished_at", time.time())
        if running(r) == sync_id:
            r.delete(RUNNING)


def log(r, sync_id: str, line: str) -> None:
    key = _key(sync_id, "log")
    seq = r.hincrby(_key(sync_id), "log_seq", 1)
    r.rpush(key, json.dumps({"seq": seq, "line": line}))
    r.ltrim(key, -LOG_LINES, -1)
    r.expire(key, KEEP)


def progress(sources: list[dict], started_at: float, now: float) -> tuple[float, float | None]:
    """Percent done and seconds left, weighting each source by how long it usually takes.

    A running source earns its share as time passes (to 90% of it until it reports), so the bar moves
    while a slow scrape runs. Seconds left come from the pace so far, once there is some to go on, and
    are at least as long as the wait for any source's retry. When a source runs past its usual time
    there is nothing to say how much longer it needs, so a short estimate becomes none ("finishing").
    """
    total = sum(s["expected"] for s in sources) or 1.0
    credit = 0.0
    floor = 0.0
    overdue = False
    for s in sources:
        if s["state"] in FINISHED:
            credit += s["expected"]
        elif s["state"] == "running":
            ran = now - s.get("started_at", now)
            credit += min(ran, 0.9 * s["expected"])
            overdue = overdue or ran > s["expected"]
        elif s["state"] == "retrying":
            floor = max(floor, s.get("retry_at", now) - now + s["expected"])
    pct = 100.0 * credit / total
    if all(s["state"] in FINISHED for s in sources):
        return 100.0, 0.0
    elapsed = now - started_at
    eta = elapsed * (100.0 - pct) / pct if pct >= 5.0 else None
    if overdue and (eta is None or eta < 10):
        eta = None
    if floor:
        eta = max(eta or 0.0, floor)
    return min(pct, 99.0), eta


def status(r, *, with_log: bool = False, log_after: int = 0) -> dict:
    """The latest sync for the UI: its state, percent, seconds left, sources and (for admins) new log lines."""
    sync_id = _s(r.get(CURRENT))
    meta = {_s(k): _s(v) for k, v in r.hgetall(_key(sync_id)).items()} if sync_id else {}
    if not meta:
        return {"state": "idle"}
    sources = [dict(json.loads(_s(v)), id=_s(k)) for k, v in r.hgetall(_key(sync_id, "sources")).items()]
    now = time.time()
    started = float(meta["started_at"])
    total, errors, empty = int(meta["total"]), int(meta["errors"]), int(meta["empty"])
    if meta.get("finished_at"):
        state = "error" if errors and errors == total else "partial" if errors or empty else "done"
        pct, eta = 100.0, 0.0
    elif running(r) != sync_id:
        state, (pct, eta) = "stalled", progress(sources, started, now)
        eta = None
    else:
        state, (pct, eta) = "running", progress(sources, started, now)
    out = {
        "id": sync_id,
        "state": state,
        "trigger": meta.get("trigger"),
        "started_at": started,
        "finished_at": float(meta["finished_at"]) if meta.get("finished_at") else None,
        "total": total,
        "completed": int(meta["completed"]),
        "errors": errors,
        "empty": empty,
        "new_items": int(meta["new_items"]),
        "percent": round(pct, 1),
        "eta_seconds": round(eta) if eta is not None else None,
        # Nothing has started yet: the worker is busy elsewhere or not running at all
        "waiting_for_worker": state == "running" and now - started > WAITING_AFTER
        and all(s["state"] == "queued" for s in sources),
        "sources": sorted(
            ({k: s.get(k) for k in ("id", "name", "state", "new", "error", "retry_at")} for s in sources),
            key=lambda s: s["name"] or ""),
    }
    if with_log:
        lines = [json.loads(_s(x)) for x in r.lrange(_key(sync_id, "log"), 0, -1)]
        out["log"] = [x for x in lines if x["seq"] > log_after]
    return out
