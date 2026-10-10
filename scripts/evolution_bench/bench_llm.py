"""
Phase 0 — how well Qwen3.5-9B does the three narrow classification jobs.

Runs Task A (gap sentence), Task B (citing-sentence intent) and Task C
(section type) against the hand labels in labels.csv, with thinking off and
on, using llama-server's JSON-schema constrained output at temperature 0.

Reports per-class precision / recall / F1, JSON validity and latency, and
checks the Phase 0 pass marks.

Usage:
    python -m scripts.evolution_bench.bench_llm                    # all tasks, thinking off and on
    python -m scripts.evolution_bench.bench_llm --tasks B --think off
"""
import argparse
import csv
import json
import statistics
import time
from datetime import datetime

import requests

from scripts.evolution_bench.common import (
    KNOWN_TITLES, LIMITATION_LABELS, OUT_DIR, PAPERS_BY_KEY, RESULTS_PATH, SECTION_TYPES, TASK_LABELS,
    labelled_rows,
)
from scripts.evolution_bench.servers import CHAT_PORT, REASONING_BUDGET, chat_server

SYSTEM_PROMPT = "You classify text from research papers. Reply with JSON only."
MAX_TOKENS = {False: 64, True: REASONING_BUDGET + 200}


def _title(key: str) -> str:
    return KNOWN_TITLES.get(key, key)


def prompt_for(task: str, row: dict) -> str:
    paper = PAPERS_BY_KEY[row["paper"]].title
    if task == "A":
        return (
            f"Paper: {paper}\nSection: {row['section']}\nSentence: {row['sentence']}\n\n"
            "Is this sentence a research gap statement? A gap statement describes a limitation, an unsolved "
            "problem, or something existing methods (or this paper) cannot do. Claims about the paper's own "
            "successful results are not gaps.\n"
            'Return {"label": "gap"} or {"label": "not_gap"}.'
        )
    if task == "B":
        return (
            f"Citing paper: {paper}\nCited paper: {_title(row['cited'])}\n"
            f"Sentence from the citing paper: {row['sentence']}\n\n"
            "What does this sentence say about the cited paper?\n"
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
    return (
        f"Paper: {paper}\nSection heading: {row['section']}\nFirst words of the section: {row['sentence']}\n\n"
        f"Which standard section type is this? One of: {', '.join(SECTION_TYPES)}.\n"
        'Return {"label": "<section type>"}.'
    )


def schema_for(task: str) -> dict:
    return {
        "type": "object",
        "properties": {"label": {"type": "string", "enum": TASK_LABELS[task]}},
        "required": ["label"],
        "additionalProperties": False,
    }


def classify(task: str, row: dict, think: bool) -> dict:
    payload = {
        "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                     {"role": "user", "content": prompt_for(task, row)}],
        "temperature": 0,
        "max_tokens": MAX_TOKENS[think],
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": f"task_{task}", "schema": schema_for(task)}},
        "chat_template_kwargs": {"enable_thinking": think},
    }
    start = time.time()
    try:
        r = requests.post(f"http://127.0.0.1:{CHAT_PORT}/v1/chat/completions", json=payload, timeout=900)
        r.raise_for_status()
        body = r.json()
    except requests.RequestException as exc:
        return {"pred": None, "valid": False, "latency": time.time() - start, "tokens": 0, "error": str(exc)[:200]}
    latency = time.time() - start
    content = body["choices"][0]["message"].get("content") or ""
    tokens = body.get("usage", {}).get("completion_tokens", 0)
    try:
        pred = json.loads(content)["label"]
        valid = pred in TASK_LABELS[task]
    except (json.JSONDecodeError, KeyError, TypeError):
        pred, valid = None, False
    return {"pred": pred if valid else None, "valid": valid, "latency": latency, "tokens": tokens,
            "error": "" if valid else content[:200]}


def per_class(gold: list[str], pred: list[str | None], labels: list[str]) -> dict:
    out = {}
    for label in labels:
        tp = sum(g == label and p == label for g, p in zip(gold, pred))
        fp = sum(g != label and p == label for g, p in zip(gold, pred))
        fn = sum(g == label and p != label for g, p in zip(gold, pred))
        precision = tp / (tp + fp) if tp + fp else float("nan")
        recall = tp / (tp + fn) if tp + fn else float("nan")
        f1 = 2 * precision * recall / (precision + recall) if precision + recall and tp else 0.0
        out[label] = {"p": precision, "r": recall, "f1": f1, "support": tp + fn}
    return out


def run(task: str, think: bool) -> dict:
    rows = labelled_rows(task)
    if not rows:
        print(f"Task {task}: no labelled rows, skipping")
        return {}
    preds = []
    for i, row in enumerate(rows, 1):
        result = classify(task, row, think)
        preds.append(result)
        print(f"\r  task {task} think={'on' if think else 'off'}: {i}/{len(rows)}", end="", flush=True)
    print()

    gold = [r["label"] for r in rows]
    pred = [p["pred"] for p in preds]
    labels = [lb for lb in TASK_LABELS[task] if lb in gold]
    stats = per_class(gold, pred, labels)
    if task == "B":
        # Binary view used by the pass mark: does the sentence state a limitation of the cited paper?
        binary = per_class(["limitation" if g in LIMITATION_LABELS else "no" for g in gold],
                           ["limitation" if p in LIMITATION_LABELS else "no" for p in pred], ["limitation"])
        stats = {**stats, "states_limitation": binary["limitation"]}
    macro_f1 = statistics.mean(s["f1"] for s in stats.values()) if stats else float("nan")
    accuracy = sum(g == p for g, p in zip(gold, pred)) / len(gold)
    latencies = sorted(p["latency"] for p in preds)
    summary = {
        "task": task, "think": think, "n": len(rows), "accuracy": accuracy, "macro_f1": macro_f1,
        "json_valid": sum(p["valid"] for p in preds) / len(preds),
        "latency_mean": statistics.mean(latencies),
        "latency_p95": latencies[min(len(latencies) - 1, int(0.95 * len(latencies)))],
        "tokens_mean": statistics.mean(p["tokens"] for p in preds),
        "per_class": stats,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_DIR / f"predictions_{task}_think-{'on' if think else 'off'}.csv", "w", newline="",
              encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["id", "gold", "pred", "valid", "latency", "tokens", "error"])
        writer.writeheader()
        for row, p in zip(rows, preds):
            writer.writerow({"id": row["id"], "gold": row["label"], "pred": p["pred"], "valid": p["valid"],
                             "latency": round(p["latency"], 2), "tokens": p["tokens"], "error": p["error"]})
    return summary


def report(summaries: list[dict]):
    stamp = datetime.now().isoformat(timespec="seconds")
    rows = []
    print("\n=== Results ===")
    for s in summaries:
        mode = "on" if s["think"] else "off"
        print(f"\nTask {s['task']} · thinking {mode} · n={s['n']}  accuracy {s['accuracy']:.2f}  "
              f"macro-F1 {s['macro_f1']:.2f}  valid JSON {s['json_valid']:.0%}  "
              f"latency mean {s['latency_mean']:.1f}s p95 {s['latency_p95']:.1f}s  "
              f"~{s['tokens_mean']:.0f} tokens out")
        for label, c in s["per_class"].items():
            print(f"    {label:22s} P {c['p']:.2f}  R {c['r']:.2f}  F1 {c['f1']:.2f}  (n={c['support']})")
        setting = f"task={s['task']},think={mode}"
        for metric in ("accuracy", "macro_f1", "json_valid", "latency_mean", "latency_p95", "tokens_mean"):
            rows.append({"timestamp": stamp, "bench": "llm", "setting": setting, "metric": metric,
                         "value": round(s[metric], 3)})
        for label, c in s["per_class"].items():
            for k in ("p", "r", "f1"):
                rows.append({"timestamp": stamp, "bench": "llm", "setting": setting, "metric": f"{label}_{k}",
                             "value": round(c[k], 3)})

    new = not RESULTS_PATH.exists()
    with open(RESULTS_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["timestamp", "bench", "setting", "metric", "value"])
        if new:
            writer.writeheader()
        writer.writerows(rows)

    print("\n=== Pass marks ===")
    by = {(s["task"], s["think"]): s for s in summaries}
    for think in (False, True):
        b = by.get(("B", think))
        if b and "states_limitation" in b["per_class"]:
            p = b["per_class"]["states_limitation"]["p"]
            role = ("9B decides strict links" if p >= 0.8 else
                    "strict links need a cue rule and the 9B to agree" if p >= 0.6 else
                    "strict links from rules + manual checks; 9B only for loose links")
            print(f"  Task B 'states a limitation' precision (thinking {'on' if think else 'off'}): {p:.2f} -> {role}")
        a = by.get(("A", think))
        if a and "gap" in a["per_class"]:
            f1 = a["per_class"]["gap"]["f1"]
            print(f"  Task A gap F1 (thinking {'on' if think else 'off'}): {f1:.2f} "
                  f"-> {'pass' if f1 >= 0.7 else 'below 0.7'}")
    for s in summaries:
        if s["json_valid"] < 0.99:
            print(f"  Valid JSON below 99%: task {s['task']} thinking {'on' if s['think'] else 'off'} "
                  f"({s['json_valid']:.0%})")
    for task in "ABC":
        off, on = by.get((task, False)), by.get((task, True))
        if off and on:
            gain = on["macro_f1"] - off["macro_f1"]
            print(f"  Thinking gain, task {task}: {gain:+.2f} macro-F1 "
                  f"({'worth it' if gain >= 0.1 else 'not worth it'}; "
                  f"{on['latency_mean'] / max(off['latency_mean'], 1e-6):.0f}x slower)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tasks", default="ABC", help="subset of A, B, C")
    ap.add_argument("--think", choices=["off", "on", "both"], default="both")
    args = ap.parse_args()

    modes = {"off": [False], "on": [True], "both": [False, True]}[args.think]
    summaries = []
    with chat_server():
        for think in modes:
            for task in args.tasks.upper():
                s = run(task, think)
                if s:
                    summaries.append(s)
    report(summaries)


if __name__ == "__main__":
    main()
