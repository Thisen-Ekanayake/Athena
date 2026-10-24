"""
Uploaded files: kept under ATHENA_UPLOADS_DIR (default ~/.athena/uploads), one folder per user.

PDFs and text files are read into text when they arrive, so a chat can use one at once; images stay as they are
and go to the vision model (a project's images also get a caption for search, athena.projects.index). No size
limits: Athena runs on the user's own machine.
"""
from __future__ import annotations

import base64
import io
import os
from pathlib import Path
from uuid import UUID, uuid4

from loguru import logger

TEXT_TYPES = {".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".tex", ".bib", ".py", ".rst", ".yaml", ".yml",
              ".html", ".xml"}
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
               ".gif": "image/gif"}
IMAGE_MAX_SIDE = 1280     # the vision model's tokens grow with the picture; this keeps one under ~2k


class UnsupportedFile(ValueError):
    pass


def uploads_dir() -> Path:
    return Path(os.path.expanduser(os.getenv("ATHENA_UPLOADS_DIR", "~/.athena/uploads")))


def kind_of(filename: str, mime: str | None) -> tuple[str, str]:
    """(kind, mime) for an upload: pdf, text or image; anything else is refused."""
    ext = Path(filename).suffix.lower()
    mime = (mime or "").lower()
    if ext == ".pdf" or mime == "application/pdf":
        return "pdf", "application/pdf"
    if ext in IMAGE_TYPES or mime.startswith("image/"):
        if ext not in IMAGE_TYPES and mime not in IMAGE_TYPES.values():
            raise UnsupportedFile(f"Images can be PNG, JPEG, WebP or GIF, not {mime or ext}")
        return "image", IMAGE_TYPES.get(ext, mime)
    if ext in TEXT_TYPES or mime.startswith("text/"):
        return "text", mime or "text/plain"
    raise UnsupportedFile("Upload PDFs, text or Markdown files, or images")


def save(user_id: UUID, filename: str, data: bytes) -> str:
    """Write the bytes; returns the path relative to the uploads folder."""
    ext = Path(filename).suffix.lower()[:10]
    rel = Path(str(user_id)) / f"{uuid4().hex}{ext}"
    full = uploads_dir() / rel
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_bytes(data)
    return str(rel)


def full_path(rel: str) -> Path:
    path = (uploads_dir() / rel).resolve()
    if uploads_dir().resolve() not in path.parents:
        raise ValueError("Path outside the uploads folder")
    return path


def remove(paths: list[str]) -> None:
    for rel in paths:
        try:
            full_path(rel).unlink(missing_ok=True)
        except Exception as exc:  # a file already gone is no reason to fail a delete
            logger.warning(f"Upload {rel} not removed: {exc}")


def extract_text(kind: str, data: bytes) -> tuple[str | None, int | None]:
    """(text, pages) for a PDF or text file; (None, None) for an image."""
    if kind == "text":
        for encoding in ("utf-8", "utf-16", "latin-1"):
            try:
                return data.decode(encoding), None
            except UnicodeDecodeError:
                continue
        return data.decode("utf-8", errors="ignore"), None
    if kind == "pdf":
        import pdfplumber
        pages = []
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages:
                pages.append(page.extract_text() or "")
        return "\n\n".join(p.strip() for p in pages if p.strip()), len(pages)
    return None, None


def image_data_url(rel: str, mime: str) -> str:
    """The image as a data URL for the vision model, shrunk to IMAGE_MAX_SIDE on its longer side."""
    data = full_path(rel).read_bytes()
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as img:
            if max(img.size) > IMAGE_MAX_SIDE or mime == "image/gif":
                img = img.convert("RGB")
                img.thumbnail((IMAGE_MAX_SIDE, IMAGE_MAX_SIDE))
                out = io.BytesIO()
                img.save(out, format="JPEG", quality=88)
                data, mime = out.getvalue(), "image/jpeg"
    except Exception as exc:  # Pillow missing or an odd file: send it as it is
        logger.debug(f"Image {rel} not resized: {exc}")
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"
