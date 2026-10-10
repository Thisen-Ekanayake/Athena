"""
Start and stop llama-server for the benchmarks (adapted from /ml-backup/Qwen/paper_qa.py).

The two models do not fit in 8 GB of VRAM together, so each benchmark runs
exactly one of them on the GPU. A server already listening on the port is
reused instead of started.
"""
import subprocess
import time
from contextlib import contextmanager

import requests

from scripts.evolution_bench.common import MODELS_DIR, OUT_DIR

EMBED_MODEL = MODELS_DIR / "Qwen3-Embedding-8B-Q4_K_M.gguf"
CHAT_MODEL = MODELS_DIR / "Qwen3.5-9B-Q4_K_M.gguf"
EMBED_PORT, CHAT_PORT = 8081, 8080
# Unbounded thinking ran past 4,096 tokens (~2 min) for one classification in the smoke test.
REASONING_BUDGET = 512
REASONING_BUDGET_MESSAGE = "\n\nThinking budget reached. I will give the final answer now.\n"


class ServerStartError(RuntimeError):
    """llama-server exited before becoming healthy (usually out of VRAM)."""


def server_up(port: int) -> bool:
    try:
        return requests.get(f"http://127.0.0.1:{port}/health", timeout=2).status_code == 200
    except requests.ConnectionError:
        return False


@contextmanager
def llama_server(port: int, args: list[str], log_name: str):
    """Run llama-server for the duration of the block (or reuse a running one)."""
    if server_up(port):
        print(f"[reusing server on :{port}; its launch flags may differ from this benchmark's]")
        yield
        return
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    log_path = OUT_DIR / log_name
    with open(log_path, "w") as log:
        proc = subprocess.Popen(["llama-server", "--port", str(port), *args],
                                stdout=log, stderr=subprocess.STDOUT)
    try:
        print(f"[starting llama-server on :{port}, log: {log_path}]", end="", flush=True)
        while not server_up(port):
            if proc.poll() is not None:
                print()
                raise ServerStartError(f"llama-server exited early, see {log_path}")
            print(".", end="", flush=True)
            time.sleep(1)
        print(" ready")
        yield
    finally:
        proc.terminate()
        proc.wait()


def embed_server(parallel: int = 4, ctx: int = 4096, ubatch: int = 1024):
    # Weights (4.7 GB) + KV cache + compute buffer must fit in ~7.3 GB free VRAM;
    # -c 8192 with -ub 2048 ran out of memory. Every input must fit in one ubatch.
    args = ["-m", str(EMBED_MODEL), "--embedding", "--pooling", "last", "-ngl", "99",
            "-c", str(ctx), "-np", str(parallel), "-b", "2048", "-ub", str(ubatch)]
    return llama_server(EMBED_PORT, args, f"embed-server-np{parallel}.log")


def chat_server(ctx: int = 8192):
    args = ["-m", str(CHAT_MODEL), "-ngl", "99", "-c", str(ctx), "-np", "1", "--jinja",
            "--reasoning-budget", str(REASONING_BUDGET), "--reasoning-budget-message", REASONING_BUDGET_MESSAGE]
    return llama_server(CHAT_PORT, args, "chat-server.log")
