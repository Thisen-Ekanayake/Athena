"""
How fast a model answers at each context, for the picker and the registry.

Writing an answer reads every active weight once per token, so its speed is set by memory bandwidth: the part of the
model on the GPU is read at the card's speed, the rest at the CPU's. A measured speed (the benchmark run when the model
was added, kept current by real chat turns) wins; a context that was not measured scales a measured one by how its
GPU/CPU split differs; a model never measured gets the bandwidth formula, calibrated by whatever this machine has
measured for other models. The source is returned with the number, so the page can mark estimates with "~".
"""
from __future__ import annotations

from statistics import median

DEFAULT_GPU_BYTES_PER_S = 180e9   # a mid-range card's effective bandwidth for quantised weights
DEFAULT_CPU_BYTES_PER_S = 55e9    # dual-channel DDR5, effective (a 9B Q4_K_M wrote 11 tok/s on a laptop's)
DEFAULT_LOAD_BYTES_PER_S = 2.5e9  # weights from the page cache onto the GPU
LOAD_OVERHEAD_S = 1.5             # starting the process and the context


def active_bytes(row: dict) -> float:
    """Bytes read per token: all of a dense model; for a mixture of experts, the shared part and the experts used."""
    info = row.get("info") or {}
    size = float(row.get("size_bytes") or 0)
    experts, used = info.get("experts") or 0, info.get("experts_used") or 0
    if experts and used:
        return size * (0.15 + 0.85 * used / experts)
    return size


def _split(plan: dict) -> float:
    return (plan.get("gpu_layers") or 0) / max(plan.get("layers") or 1, 1)


def formula(row: dict, plan: dict, gpu_bw: float, cpu_bw: float) -> float:
    active = active_bytes(row) or 1.0
    on_gpu = _split(plan) if plan.get("device") != "cpu" else 0.0
    seconds = active * on_gpu / gpu_bw + active * (1 - on_gpu) / cpu_bw
    return 1 / seconds if seconds > 0 else 0.0


def bandwidths(rows: list[dict], benches: list[dict]) -> tuple[float, float]:
    """(GPU, CPU) effective bytes a second, from measured runs that sat wholly on one side."""
    by_model = {r["id"]: r for r in rows}
    gpu, cpu = [], []
    for b in benches:
        r = by_model.get(b["model_id"])
        if not r or not b.get("gen_tps"):
            continue
        plan = next((c["plan"] for c in r["contexts"] if c["context"] == b["context"]), None)
        if plan is None:
            continue
        if plan["device"] == "gpu":
            gpu.append(active_bytes(r) * b["gen_tps"])
        elif plan["device"] == "cpu":
            cpu.append(active_bytes(r) * b["gen_tps"])
    return (median(gpu) if gpu else DEFAULT_GPU_BYTES_PER_S), (median(cpu) if cpu else DEFAULT_CPU_BYTES_PER_S)


def load_rate(rows: list[dict], benches: list[dict]) -> float:
    by_model = {r["id"]: r for r in rows}
    rates = [by_model[b["model_id"]]["size_bytes"] / max(b["load_seconds"] - LOAD_OVERHEAD_S, 0.3)
             for b in benches if b.get("load_seconds") and b["model_id"] in by_model]
    return median(rates) if rates else DEFAULT_LOAD_BYTES_PER_S


def estimates(rows: list[dict], benches: list[dict], device_of) -> dict[str, dict[int, dict]]:
    """{model name: {context: {tps, prompt_tps, load_seconds, source}}}; source is measured | scaled | estimate.

    ``benches`` are this file's and this machine's rows ({model_id, context, device, gen_tps, prompt_tps,
    load_seconds, samples, source}); ``device_of(plan)`` names the device a plan runs on, as benchmarks key it."""
    gpu_bw, cpu_bw = bandwidths(rows, benches)
    rate = load_rate(rows, benches)
    out: dict[str, dict[int, dict]] = {}
    for r in rows:
        mine = [b for b in benches if b["model_id"] == r["id"]]
        per: dict[int, dict] = {}
        for c in r["contexts"]:
            plan = c["plan"]
            exact = next((b for b in mine if b["context"] == c["context"] and b["device"] == device_of(plan)), None)
            guess = formula(r, plan, gpu_bw, cpu_bw)
            load = (exact or {}).get("load_seconds") or next(
                (b["load_seconds"] for b in mine if b.get("load_seconds") and b["device"] == device_of(plan)), None)
            load = load or LOAD_OVERHEAD_S + r["size_bytes"] / rate
            if exact and exact.get("gen_tps"):
                per[c["context"]] = {"tps": exact["gen_tps"], "prompt_tps": exact.get("prompt_tps"),
                                     "load_seconds": load, "source": "measured", "samples": exact.get("samples")}
                continue
            near = [b for b in mine if b.get("gen_tps")]
            if near:  # the nearest measured context, scaled by how this one's split differs
                b = min(near, key=lambda b: abs(b["context"] - c["context"]))
                their = next((x["plan"] for x in r["contexts"] if x["context"] == b["context"]), plan)
                base = formula(r, their, gpu_bw, cpu_bw)
                per[c["context"]] = {"tps": b["gen_tps"] * (guess / base if base else 1),
                                     "prompt_tps": b.get("prompt_tps"), "load_seconds": load, "source": "scaled"}
                continue
            per[c["context"]] = {"tps": guess, "prompt_tps": None, "load_seconds": load, "source": "estimate"}
        out[r["name"]] = per
    return out
