"""
What a GGUF file says about itself: architecture, size, quantisation, layers, trained context and what its chat
template supports. Only the header is read (the key/value section before the tensors), so a 6 GB file takes
well under a second; nothing here loads weights.
"""
from __future__ import annotations

import os
import re
import struct
from typing import BinaryIO

MAGIC = b"GGUF"

# llama_ftype: general.file_type in the header
FILE_TYPES = {
    0: "F32", 1: "F16", 2: "Q4_0", 3: "Q4_1", 7: "Q8_0", 8: "Q5_0", 9: "Q5_1", 10: "Q2_K", 11: "Q3_K_S",
    12: "Q3_K_M", 13: "Q3_K_L", 14: "Q4_K_S", 15: "Q4_K_M", 16: "Q5_K_S", 17: "Q5_K_M", 18: "Q6_K",
    19: "IQ2_XXS", 20: "IQ2_XS", 21: "Q2_K_S", 22: "IQ3_XS", 23: "IQ3_XXS", 24: "IQ1_S", 25: "IQ4_NL",
    26: "IQ3_S", 27: "IQ3_M", 28: "IQ2_S", 29: "IQ2_M", 30: "IQ4_XS", 31: "IQ1_M", 32: "BF16", 36: "TQ1_0",
    37: "TQ2_0", 38: "MXFP4",
}
# Bits per weight, for a parameter count when the header has no size label
BITS = {"F32": 32, "F16": 16, "BF16": 16, "Q8_0": 8.5, "Q6_K": 6.6, "Q5_K_M": 5.7, "Q5_K_S": 5.5, "Q5_0": 5.5,
        "Q5_1": 6, "Q4_K_M": 4.9, "Q4_K_S": 4.6, "Q4_0": 4.5, "Q4_1": 5, "IQ4_XS": 4.3, "IQ4_NL": 4.5,
        "Q3_K_M": 3.9, "Q3_K_L": 4.3, "Q3_K_S": 3.5, "Q2_K": 3.4, "MXFP4": 4.25}
EMBED_ARCHES = {"bert", "nomic-bert", "nomic-bert-moe", "jina-bert-v2", "jina-bert-v3", "t5encoder", "modern-bert"}

# value types
_U8, _I8, _U16, _I16, _U32, _I32, _F32, _BOOL, _STR, _ARR, _U64, _I64, _F64 = range(13)
_SCALARS = {_U8: "<B", _I8: "<b", _U16: "<H", _I16: "<h", _U32: "<I", _I32: "<i", _F32: "<f", _BOOL: "<?",
            _U64: "<Q", _I64: "<q", _F64: "<d"}
# Arrays longer than this (token lists, merges) are skipped rather than kept
KEEP_ARRAY = 64


class NotGGUF(ValueError):
    """The file is not a GGUF model."""


def _read(f: BinaryIO, fmt: str):
    size = struct.calcsize(fmt)
    data = f.read(size)
    if len(data) != size:
        raise NotGGUF("The file ends inside its header")
    return struct.unpack(fmt, data)[0]


def _string(f: BinaryIO) -> str:
    n = _read(f, "<Q")
    if n > 1 << 26:
        raise NotGGUF("A header string is implausibly long")
    return f.read(n).decode("utf-8", errors="replace")


def _skip_string(f: BinaryIO) -> None:
    f.seek(_read(f, "<Q"), os.SEEK_CUR)


def _value(f: BinaryIO, kind: int):
    if kind in _SCALARS:
        return _read(f, _SCALARS[kind])
    if kind == _STR:
        return _string(f)
    if kind == _ARR:
        item, count = _read(f, "<I"), _read(f, "<Q")
        if count > KEEP_ARRAY:
            if item == _STR:
                for _ in range(count):
                    _skip_string(f)
            elif item in _SCALARS:
                f.seek(struct.calcsize(_SCALARS[item]) * count, os.SEEK_CUR)
            else:
                for _ in range(count):
                    _value(f, item)
            return None
        return [_value(f, item) for _ in range(count)]
    raise NotGGUF(f"Unknown value type {kind} in the header")


def read_header(path: str) -> dict:
    """Every key/value in the header; long arrays (the vocabulary) come back as None."""
    return _parse(path)[0]


def _parse(path: str, tensors: bool = False) -> tuple[dict, int | None]:
    """(header, bytes the tensor data needs to end at) — the second only with ``tensors``."""
    with open(path, "rb") as raw:
        f = _Buffered(raw)
        if f.read(4) != MAGIC:
            raise NotGGUF("Not a GGUF file")
        version = _read(f, "<I")
        if version < 2:
            raise NotGGUF(f"GGUF version {version} is too old for llama.cpp")
        n_tensors = _read(f, "<Q")
        count = _read(f, "<Q")
        out = {}
        for _ in range(count):
            key = _string(f)
            out[key] = _value(f, _read(f, "<I"))
        if not tensors:
            return out, None
        end = 0
        for _ in range(n_tensors):
            _skip_string(f)
            dims = [_read(f, "<Q") for _ in range(_read(f, "<I"))]
            kind, offset = _read(f, "<I"), _read(f, "<Q")
            elements = 1
            for d in dims:
                elements *= d
            block, size = TYPE_SIZES.get(kind, (1, 0))
            end = max(end, offset + elements // block * size)
        align = int(out.get("general.alignment") or 32)
        start = f.tell()
        start += (align - start % align) % align
        return out, start + end


# ggml tensor types: (elements per block, bytes per block), for how long a file must be
TYPE_SIZES = {
    0: (1, 4), 1: (1, 2), 2: (32, 18), 3: (32, 20), 6: (32, 22), 7: (32, 24), 8: (32, 34), 9: (32, 36),
    10: (256, 84), 11: (256, 110), 12: (256, 144), 13: (256, 176), 14: (256, 210), 15: (256, 292),
    16: (256, 66), 17: (256, 74), 18: (256, 98), 19: (256, 50), 20: (32, 18), 21: (256, 110), 22: (256, 82),
    23: (256, 136), 24: (1, 1), 25: (1, 2), 26: (1, 4), 27: (1, 8), 28: (1, 8), 29: (256, 56), 30: (1, 2),
    34: (256, 54), 35: (256, 66), 39: (32, 17),
}


def completeness(path: str) -> dict:
    """{complete, needed_bytes, size_bytes}: whether the file holds all of its tensors' data. A download cut short
    loads in llama.cpp as "data is not within the file bounds". Split models (several parts) are not checked."""
    header, needed = _parse(path, tensors=True)
    size = os.path.getsize(path)
    if int(header.get("split.count") or 1) > 1 or not needed:
        return {"complete": True, "needed_bytes": None, "size_bytes": size}
    return {"complete": size >= needed, "needed_bytes": needed, "size_bytes": size}


class _Buffered:
    """Seeks forward inside a read buffer: skipping 250k vocabulary strings one seek at a time is slow."""

    def __init__(self, raw: BinaryIO, size: int = 1 << 20):
        self.raw, self.size, self.buf, self.pos = raw, size, b"", 0

    def _fill(self, n: int) -> None:
        if len(self.buf) - self.pos < n:
            self.buf = self.buf[self.pos:] + self.raw.read(max(self.size, n))
            self.pos = 0

    def read(self, n: int) -> bytes:
        self._fill(n)
        out = self.buf[self.pos:self.pos + n]
        self.pos += len(out)
        return out

    def tell(self) -> int:
        return self.raw.tell() - (len(self.buf) - self.pos)

    def seek(self, n: int, whence: int = os.SEEK_CUR) -> None:
        assert whence == os.SEEK_CUR
        if n <= len(self.buf) - self.pos:
            self.pos += n
        else:
            self.raw.seek(n - (len(self.buf) - self.pos), os.SEEK_CUR)
            self.buf, self.pos = b"", 0


def _quant(header: dict, filename: str) -> str | None:
    if (ft := header.get("general.file_type")) in FILE_TYPES:
        return FILE_TYPES[ft]
    m = re.search(r"(?i)(I?Q\d_[A-Z0-9_]+|BF16|F16|F32|Q8_0|MXFP4)", filename)
    return m.group(1).upper() if m else None


def _size_label(header: dict, size: int, quant: str | None, filename: str) -> str | None:
    if label := header.get("general.size_label"):
        return str(label)
    m = re.search(r"(?i)(\d+(?:\.\d+)?)[bm](?![a-z])", filename)
    if m:
        return m.group(0).upper()
    if quant in BITS:
        billions = size * 8 / BITS[quant] / 1e9
        return f"{billions:.1f}B" if billions < 10 else f"{billions:.0f}B"
    return None


def describe(path: str, check: bool = False) -> dict:
    """What Athena needs to register ``path``: kind (model | mmproj), name, size, layers, context, capabilities.
    With ``check``, also whether the file holds all its tensor data (``complete``, ``needed_bytes``)."""
    header = read_header(path)
    size = os.path.getsize(path)
    filename = os.path.basename(path)
    arch = str(header.get("general.architecture") or "")
    is_mmproj = arch == "clip" or header.get("general.type") == "mmproj"

    def a(key: str, default=None):
        return header.get(f"{arch}.{key}", default)

    if is_mmproj:
        return {"kind": "mmproj", "path": path, "filename": filename, "size_bytes": size,
                "name": header.get("general.name"),
                "vision": bool(header.get("clip.has_vision_encoder", True)),
                "audio": bool(header.get("clip.has_audio_encoder", False)),
                "projector": header.get("clip.projector_type") or header.get("clip.vision.projector_type")}

    template = str(header.get("tokenizer.chat_template") or "")
    quant = _quant(header, filename)
    heads = a("attention.head_count")
    heads = max(heads) if isinstance(heads, list) and heads else heads
    kv_heads = a("attention.head_count_kv")
    kv_heads = max(kv_heads) if isinstance(kv_heads, list) and kv_heads else kv_heads
    embedding = bool(a("pooling_type") is not None or arch in EMBED_ARCHES or "embed" in filename.lower())
    return {
        "kind": "model", "path": path, "filename": filename, "size_bytes": size,
        **({"complete": True} if not check else {k: v for k, v in completeness(path).items() if k != "size_bytes"}),
        "name": header.get("general.name"),
        "architecture": arch,
        "params": _size_label(header, size, quant, filename),
        "quant": quant,
        "layers": a("block_count"),
        "context_train": a("context_length"),
        "embedding_length": a("embedding_length"),
        "head_count": heads,
        "head_count_kv": kv_heads,
        "key_length": a("attention.key_length"),
        "value_length": a("attention.value_length"),
        "full_attention_interval": a("full_attention_interval"),
        "experts": a("expert_count"),
        "experts_used": a("expert_used_count"),
        "role": "embed" if embedding else "chat",
        "has_template": bool(template),
        "thinks": bool(re.search(r"<think>|enable_thinking|reasoning_content", template)),
        "tools": bool(re.search(r"\btools\b", template)),
    }


def suggested_name(info: dict) -> str:
    """A preset name from the file: lower case, no quantisation suffix (Qwen3.5-9B-Q4_K_M.gguf -> qwen3.5-9b)."""
    stem = os.path.splitext(info["filename"])[0]
    if info.get("quant"):
        stem = re.sub(rf"[-_.]?{re.escape(info['quant'])}$", "", stem, flags=re.I)
    stem = re.sub(r"[-_.](i?q\d[_a-z0-9]*|bf16|f16|f32)$", "", stem, flags=re.I)
    name = re.sub(r"[^a-z0-9.\-]+", "-", stem.lower()).strip("-.")
    return name[:60] or "model"
