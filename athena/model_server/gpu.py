"""
Where a model goes when it loads: all on the GPU, split between GPU and CPU, or all on the CPU.

llama-server fits the layers into free VRAM itself (``--fit``, on unless n-gpu-layers is set). Athena works out the
same answer ahead of time, for the picker and the registry: ``llama-fit-params -v`` projects the device memory a
model needs at a context with every layer on the GPU and with none, and memory grows in step with the context, so
two contexts give every other one. The VRAM a model may use is the card's total less what other programs (the
desktop) hold; the GPU router keeps one model at a time, so models it already holds do not count against it.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time

from loguru import logger

MARGIN_MB = 1024           # llama.cpp's own --fit-target: VRAM left free for the desktop and spikes
CACHE_SECONDS = 5.0
FIT_TIMEOUT = 180
_gpu_cache: tuple[float, dict | None] | None = None


def _smi(query: str, kind: str = "gpu") -> list[list[str]]:
    flag = "--query-gpu" if kind == "gpu" else "--query-compute-apps"
    out = subprocess.run(["nvidia-smi", f"{flag}={query}", "--format=csv,noheader,nounits"], capture_output=True,
                         text=True, timeout=10)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or "nvidia-smi failed")
    return [[c.strip() for c in line.split(",")] for line in out.stdout.strip().splitlines() if line.strip()]


def _mb(value: str) -> int:
    try:
        return int(float(value))
    except ValueError:
        return 0


def _router_ports() -> set[str] | None:
    """The ports of the models Athena's routers run now (each model is a llama-server child on a port of its
    own, which the router lists); None when no router answers, so nothing can be told apart."""
    import httpx

    from athena.core import llm
    from athena.model_server import registry
    ports, answered = set(), False
    for url in (llm.chat_base_url(), registry.cpu_base_url()):
        try:
            resp = httpx.get(f"{llm.server_root(url)}/models", timeout=2.0)
            resp.raise_for_status()
        except (httpx.HTTPError, ValueError):
            continue
        answered = True
        for m in resp.json().get("data") or []:
            args = (m.get("status") or {}).get("args") or []
            if "--port" in args and args.index("--port") + 1 < len(args):
                ports.add(str(args[args.index("--port") + 1]))
    return ports if answered else None


def _managed(pid: str, ports: set[str] | None) -> bool:
    """Whether a llama-server process is a model one of Athena's routers runs, by the port on its command line.
    Without /proc (not Linux) or a router to ask, every one counts as managed."""
    if ports is None:
        return True
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            args = f.read().decode(errors="replace").split("\0")
    except OSError:
        return True
    if "--models-preset" in args:
        return True  # a router itself
    port = args[args.index("--port") + 1] if "--port" in args and args.index("--port") + 1 < len(args) else None
    return port is None or port in ports


def gpu() -> dict | None:
    """The first NVIDIA GPU: {name, total_mb, used_mb, llama_mb, others_mb, stray, available_mb}; None without one.

    ``llama_mb`` is what the routers' models hold; ``available_mb`` is what a model may use once the router has
    unloaded its own (total less everything else, less the margin). ``stray`` lists llama-server processes no
    router started (an old server left running): their memory counts as taken, since a router cannot free it, and
    while they hold it llama.cpp fits new models onto the CPU."""
    global _gpu_cache
    if _gpu_cache and time.monotonic() - _gpu_cache[0] < CACHE_SECONDS:
        return _gpu_cache[1]
    info = None
    if shutil.which("nvidia-smi"):
        try:
            rows = _smi("name,memory.total,memory.used")
            if rows:
                name, total, used = rows[0][0], _mb(rows[0][1]), _mb(rows[0][2])
                llama, stray = 0, []
                try:
                    apps = [a for a in _smi("pid,process_name,used_memory", "apps") if "llama-server" in a[1]]
                    ports = _router_ports() if apps else set()
                    for pid, _process, mem in apps:
                        if _managed(pid, ports):
                            llama += _mb(mem)
                        else:
                            stray.append({"pid": int(pid), "mb": _mb(mem)})
                except Exception:  # per-process figures are missing on some drivers
                    pass
                others = max(used - llama, 0)
                info = {"name": name, "total_mb": total, "used_mb": used, "llama_mb": llama, "others_mb": others,
                        "stray": stray, "available_mb": max(total - others - MARGIN_MB, 0)}
        except Exception as exc:
            logger.info(f"No GPU figures: {exc}")
    _gpu_cache = (time.monotonic(), info)
    return info


def device_key(info: dict | None = None) -> str:
    """The GPU's name, or cpu: benchmarks are kept per device."""
    info = info if info is not None else gpu()
    return info["name"] if info else "cpu"


# ── projections ─────────────────────────────────────────────────────────


def fit_binary() -> str | None:
    """llama-fit-params beside the llama-server Athena starts (LLAMA_SERVER_BIN), else on the PATH."""
    from athena.core.config_store import get_setting
    server = get_setting("LLAMA_SERVER_BIN") or os.getenv("LLAMA_SERVER_BIN") or shutil.which("llama-server")
    if server:
        candidate = os.path.join(os.path.dirname(os.path.abspath(server)), "llama-fit-params")
        if os.access(candidate, os.X_OK):
            return candidate
    return shutil.which("llama-fit-params")


PROJECTED = re.compile(r"projected to use (\d+) MiB of device memory")
NO_LAYERS = re.compile(r"n_layer=\s*0,.*?mem=\s*(\d+) MiB")


def measure(path: str, context: int, cwd: str | None = None) -> tuple[int, int | None] | None:
    """(MiB with every layer on the GPU, MiB with none) at ``context``, from llama-fit-params; None without it."""
    binary = fit_binary()
    if not binary:
        return None
    try:
        out = subprocess.run([binary, "-v", "-m", path, "-c", str(context)], capture_output=True, text=True,
                             timeout=FIT_TIMEOUT, cwd=cwd)
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.warning(f"llama-fit-params on {path}: {exc}")
        return None
    log = out.stdout + out.stderr
    full = PROJECTED.search(log)
    if not full:
        logger.warning(f"llama-fit-params printed no projection for {path} (exit {out.returncode})")
        return None
    zero = NO_LAYERS.search(log)
    return int(full.group(1)), (int(zero.group(1)) if zero else None)


def estimate(info: dict, size_bytes: int, context: int) -> tuple[int, int]:
    """(full, none) MiB from the GGUF header when llama-fit-params is missing: weights, the KV cache (only the
    attention layers of a hybrid model keep one) and a compute buffer."""
    layers = info.get("layers") or 32
    interval = info.get("full_attention_interval") or 1
    attention = max(layers // interval, 1)
    heads_kv = info.get("head_count_kv") or info.get("head_count") or 8
    head_dim = info.get("key_length") or ((info.get("embedding_length") or 4096) // (info.get("head_count") or 32))
    kv_mb = attention * 2 * heads_kv * head_dim * 2 * context / (1 << 20)
    weights_mb = size_bytes / (1 << 20)
    return int(weights_mb + kv_mb + 300 + context * 0.01), int(300 + context * 0.05)


def projection(points: list[list[int]], context: int) -> tuple[float, float | None] | None:
    """(full, none) MiB at ``context`` from measured points [[ctx, full, none], ...]: memory grows in a straight
    line with the context, so it is read off (or past the ends of) the line through the two nearest."""
    pts = sorted(p for p in points if p and p[1])
    if not pts:
        return None
    if len(pts) == 1:
        return float(pts[0][1]), (float(pts[0][2]) if pts[0][2] else None)
    lo, hi = pts[0], pts[-1]
    for a, b in zip(pts, pts[1:]):
        if a[0] <= context <= b[0]:
            lo, hi = a, b
            break
    else:
        lo, hi = (pts[-2], pts[-1]) if context > pts[-1][0] else (pts[0], pts[1])
    t = (context - lo[0]) / (hi[0] - lo[0]) if hi[0] != lo[0] else 0.0

    def line(i: int) -> float | None:
        if not lo[i] or not hi[i]:
            return float(lo[i] or hi[i]) if (lo[i] or hi[i]) else None
        return lo[i] + (hi[i] - lo[i]) * t

    return line(1), line(2)


def plan(*, layers: int, size_bytes: int, placement: str, full_mb: float, zero_mb: float | None,
         info: dict | None) -> dict:
    """Where a model at one context goes: {device: gpu | split | cpu, gpu_layers, layers, vram_mb, ram_mb, fits}.

    ``layers`` counts the output layer too, as llama.cpp does (a 32-block model has 33)."""
    size_mb = size_bytes / (1 << 20)
    if zero_mb is None:
        zero_mb = max(full_mb - size_mb, 300)
    per_layer = max((full_mb - zero_mb) / max(layers, 1), 1)

    def out(device: str, k: int, fits: bool = True) -> dict:
        vram = 0 if device == "cpu" else (full_mb if k >= layers else zero_mb + k * per_layer)
        return {"device": device, "gpu_layers": k, "layers": layers, "vram_mb": int(vram),
                "ram_mb": int(size_mb * (1 - k / max(layers, 1))) + (int(full_mb - size_mb) if device == "cpu" else 0),
                "fits": fits}

    if placement == "cpu" or not info:
        return out("cpu", 0)
    available = info["available_mb"]
    if placement == "gpu":
        return out("gpu", layers, fits=full_mb <= available)
    if full_mb <= available:
        return out("gpu", layers)
    k = int((available - zero_mb) // per_layer)
    if k <= 0:
        return out("cpu", 0)
    return out("split", min(k, layers - 1))
