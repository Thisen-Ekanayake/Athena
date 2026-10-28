"""
Finding model files on this machine for the admin's picker, the way a file dialog does.

Any folder can be opened except the system ones (SYSTEM); only folders and .gguf files are listed, hidden ones
left out, and a model split into parts (``-00001-of-00003.gguf``) shows once, as its first part with the size of
all of them, which is what llama.cpp loads. The places to start from are ``models/`` in the repository, the
folders registered models live in (their symlinks' targets too), the llama.cpp download cache, any folder in
MODEL_DIRS (separated by commas), the home folder and the whole disk. Only a .gguf file outside the system
folders is ever read, and only its GGUF header.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from athena.model_server import gguf, registry

SPLIT = re.compile(r"-(\d{5})-of-(\d{5})\.gguf$", re.I)
MAX_ENTRIES = 500
SYSTEM = ("/proc", "/sys", "/dev", "/run", "/boot", "/etc")  # never a model folder


def _setting(key: str) -> str:
    from athena.core.config_store import get_setting
    return get_setting(key) or ""


def roots() -> list[str]:
    """The folders models are kept in, real paths, without duplicates or ones inside another."""
    found = [registry.REPO / "models", Path.home() / ".cache" / "llama.cpp", Path.home() / "models"]
    found += [Path(p.strip()).expanduser() for p in _setting("MODEL_DIRS").split(",") if p.strip()]
    for r in registry.snapshot():
        for path in (r["path"], r["mmproj_path"]):
            if path:
                full = Path(registry.resolve(path))
                found += [full.parent, Path(os.path.realpath(full)).parent]
    real = []
    for p in found:
        rp = os.path.realpath(p)
        if os.path.isdir(rp) and rp not in real:
            real.append(rp)
    real.sort(key=len)
    return [r for i, r in enumerate(real) if not any(r.startswith(o.rstrip("/") + "/") for o in real[:i])]


def places() -> list[dict]:
    """[{name, path}]: where the browser can start, the model folders first."""
    home, repo = os.path.realpath(Path.home()), os.path.realpath(registry.REPO / "models")
    cache = os.path.realpath(Path.home() / ".cache" / "llama.cpp")
    named = {repo: "Athena models", cache: "llama.cpp downloads"}
    found = sorted(roots(), key=lambda r: (r not in named, list(named).index(r) if r in named else 0, r.lower()))
    out = [{"name": named.get(r) or os.path.basename(r) or r, "path": r} for r in found]
    for name, path in (("Home", home), ("Computer", "/")):
        if all(p["path"] != path for p in out):
            out.append({"name": name, "path": path})
    return out


def _system(rp: str) -> bool:
    return any(rp == s or rp.startswith(s + "/") for s in SYSTEM)


def checked(path: str) -> str:
    """``path`` resolved (symlinks too), if it is a .gguf file outside the system folders; use what this returns,
    not ``path``, so the file read is the one that was checked."""
    rp = os.path.realpath(os.path.expanduser(path))
    if _system(rp) or not rp.lower().endswith(".gguf"):
        raise PermissionError("Pick a .gguf file outside the system folders")
    return rp


def _kind(name: str) -> str:
    return "mmproj" if "mmproj" in name.lower() or "projector" in name.lower() else "model"


def browse(path: str | None) -> dict:
    """{path, parent, places, entries: [{name, path, kind: dir | model | mmproj, size_bytes, parts}]}; with no
    path, the first place."""
    tops = places()
    rp = os.path.realpath(os.path.expanduser(path or tops[0]["path"]))
    if _system(rp):
        raise PermissionError("System folders hold no models")
    if not os.path.isdir(rp):
        raise FileNotFoundError(rp)
    dirs, files = [], []
    try:
        with os.scandir(rp) as it:
            for e in it:
                if e.name.startswith("."):
                    continue
                try:
                    if e.is_dir():
                        if not _system(os.path.join(rp, e.name)):
                            dirs.append({"name": e.name, "path": os.path.join(rp, e.name), "kind": "dir",
                                         "size_bytes": None})
                    elif e.name.lower().endswith(".gguf") and e.is_file():
                        files.append(e)
                except OSError:
                    continue
    except PermissionError:
        raise PermissionError("Athena is not allowed to read that folder")
    out_files = []
    parts: dict[str, list] = {}
    for e in files:
        if m := SPLIT.search(e.name):
            parts.setdefault(SPLIT.sub("", e.name), []).append((int(m.group(1)), e))
            continue
        out_files.append({"name": e.name, "path": os.path.join(rp, e.name), "kind": _kind(e.name),
                          "size_bytes": e.stat().st_size, "parts": 1})
    for _stem, group in parts.items():
        group.sort(key=lambda x: x[0])
        first = group[0][1]
        out_files.append({"name": first.name, "path": os.path.join(rp, first.name), "kind": _kind(first.name),
                          "size_bytes": sum(e.stat().st_size for _, e in group), "parts": len(group)})
    entries = sorted(dirs, key=lambda d: d["name"].lower()) + sorted(out_files, key=lambda f: f["name"].lower())
    return {"path": rp, "parent": os.path.dirname(rp) if rp != "/" else None, "places": tops,
            "entries": entries[:MAX_ENTRIES]}


def total_size(path: str) -> int:
    """A model's bytes: all its parts when it is split."""
    if m := SPLIT.search(path):
        stem, count = SPLIT.sub("", path), int(m.group(2))
        return sum(os.path.getsize(f"{stem}-{i:05d}-of-{count:05d}.gguf") for i in range(1, count + 1)
                   if os.path.exists(f"{stem}-{i:05d}-of-{count:05d}.gguf"))
    return os.path.getsize(path)


def projectors_for(path: str, info: dict) -> list[dict]:
    """Vision projectors beside a model, the likeliest first (same model name in its header, then any)."""
    folder = os.path.dirname(os.path.realpath(path))
    out = []
    for e in sorted(os.scandir(folder), key=lambda e: e.name):
        if not e.name.lower().endswith(".gguf") or e.path == os.path.realpath(path):
            continue
        if _kind(e.name) != "mmproj":
            continue
        try:
            d = gguf.describe(e.path)
        except (OSError, gguf.NotGGUF):
            continue
        if d["kind"] == "mmproj":
            d["match"] = bool(info.get("name") and d.get("name") == info.get("name"))
            out.append(d)
    out.sort(key=lambda d: not d["match"])
    return out
