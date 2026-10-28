"""
The router preset files, written from the registry.

llama-server in router mode serves every section of its preset file under the section's name, and re-reads the file
on ``GET /models?reload=1`` (a model whose section changed is unloaded; the rest keep running). A context size is
fixed when a model loads, so each context a model offers is a section of its own:

    [qwen3.5-9b]            the default context, under the model's own name (what background work asks for)
    [qwen3.5-9b@32k]        another context users may pick
    [qwen3.5-9b-vision]     the same with its vision projector, for messages with images (and @32k-vision, ...)

Two routers run (run_native.sh): the GPU one on :8080 keeps one model at a time and swaps them, and the CPU one on
:8081 holds a model that runs on the CPU alone, so it stays loaded beside the GPU model. A section goes to the CPU
router when its model is placed on the CPU, or when no layer of it would fit on the GPU at that context.
"""
from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass, field

# Keys the registry writes itself; the rest of a model's ``options`` are copied into its sections as they are.
OWN_KEYS = {"model", "ctx-size", "c", "mmproj", "n-gpu-layers", "ngl", "device", "jinja"}
VISION_SUFFIX = "-vision"


@dataclass
class Section:
    name: str
    values: dict[str, str] = field(default_factory=dict)


def parse(text: str) -> tuple[dict[str, str], list[Section]]:
    """(top-level keys, sections in order) of a preset file; ``[*]`` is a section like the others."""
    top: dict[str, str] = {}
    sections: list[Section] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith((";", "#")):
            continue
        if m := re.fullmatch(r"\[(.+)\]", line):
            sections.append(Section(m.group(1).strip()))
            continue
        key, sep, value = line.partition("=")
        if not sep:
            continue
        (sections[-1].values if sections else top)[key.strip()] = value.strip()
    return top, sections


def render(top: dict[str, str], sections: list[Section], header: str = "") -> str:
    lines = [f"; {h}" if h else ";" for h in header.splitlines()]
    if lines:
        lines.append("")
    lines += [f"{k} = {v}" for k, v in top.items()]
    for s in sections:
        lines += ["", f"[{s.name}]"] + [f"{k} = {v}" for k, v in s.values.items()]
    return "\n".join(lines) + "\n"


def ctx_label(context: int) -> str:
    return f"{context // 1024}k" if context % 1024 == 0 else str(context)


def preset_name(model: str, context: int, default_context: int, vision: bool = False) -> str:
    """The section for ``model`` at ``context``: its own name at the default context, ``name@32k`` otherwise."""
    base = model if context == default_context else f"{model}@{ctx_label(context)}"
    return base + (VISION_SUFFIX if vision else "")


def section(*, name: str, path: str, context: int, role: str, placement: str, device: str, options: dict,
            mmproj: str | None = None, template: bool = True) -> Section:
    """One preset section. ``device`` is the plan's (gpu | split | cpu); ``placement`` what the admin chose."""
    values: dict[str, str] = {"model": path, "ctx-size": str(context)}
    if role == "chat" and template:
        values["jinja"] = "true"
    if device == "cpu":
        values["device"] = "none"          # not even a compute buffer on the GPU
        values["n-gpu-layers"] = "0"
    elif placement == "gpu":
        values["n-gpu-layers"] = "99"      # everything, whatever llama.cpp would fit
    # auto on the GPU router: no n-gpu-layers, so llama-server fits the layers into free VRAM (--fit)
    if mmproj:
        values["mmproj"] = mmproj
        # The projector encodes images on the CPU unless the admin asked otherwise: on an 8 GB card the 9B and
        # its 0.9 GB projector do not fit together beside a desktop.
        values["no-mmproj-offload"] = "false" if str(options.get("mmproj-offload", "")).lower() == "true" else "true"
    for key, value in options.items():
        if key not in OWN_KEYS and key != "mmproj-offload":
            values[key] = str(value).lower() if isinstance(value, bool) else str(value)
    return Section(name, values)


def write_atomic(path: str, text: str) -> bool:
    """Write ``text`` to ``path`` unless it is already there; True when the file changed."""
    try:
        with open(path) as f:
            if f.read() == text:
                return False
    except FileNotFoundError:
        pass
    folder = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".preset-", suffix=".ini")
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.replace(tmp, path)
    return True
