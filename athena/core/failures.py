"""
What a failed call may tell the person looking at the page.

An exception's own text belongs in the log: it can carry the model server's address, a file path, a key inside a
URL or a line of SQL, and it reaches whoever is signed in. ``describe(exc)`` gives the kind of failure instead
(could not connect, no answer in time, HTTP 404, the model's context is full), which is the part the reader can
act on. Log the exception where it is caught, then show ``describe(exc)``:

    except Exception as exc:
        logger.warning(f"Ask {slug}: the answer failed: {exc!r}")
        yield {"error": f"The model did not answer: {failures.describe(exc)}"}

Athena's own exceptions that were written to be read (a ValueError saying "Pick a .gguf file") are not what this
is for; those are raised with their message as the response.
"""
from __future__ import annotations

import json

import httpx
import openai

from athena.core import safe_http

# What an HTTP status usually means for the reader; other statuses are shown as the number alone
STATUS = {
    400: "the request was refused",
    401: "the API key was refused",
    403: "access was refused",
    404: "not found there",
    408: "no answer in time",
    413: "the request was too large",
    429: "too many requests for now",
    500: "the server failed",
    502: "the server behind it did not answer",
    503: "the server is not ready",
    504: "no answer in time",
}


def _status(exc: BaseException) -> int | None:
    """The HTTP status an exception carries (openai's and httpx's status errors), if any."""
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    return status if isinstance(status, int) and 100 <= status <= 599 else None


def _context_full(exc: BaseException) -> bool:
    """llama.cpp and OpenAI-style servers name this error in the body; the text itself is not shown."""
    body = getattr(exc, "body", None)
    kind = code = ""
    if isinstance(body, dict):
        inner = body.get("error") if isinstance(body.get("error"), dict) else body
        kind, code = str(inner.get("type") or ""), str(inner.get("code") or "")
    return "exceed_context_size" in kind or "context_length_exceeded" in (kind, code)


def describe(exc: BaseException) -> str:
    """A short reason for ``exc`` that is safe to show anyone: its kind, never its text."""
    if isinstance(exc, safe_http.Blocked):
        return "that address is on Athena's own machine or network"
    if _context_full(exc):
        return "the request is longer than the model's context"
    status = _status(exc)
    if status is not None:
        meaning = STATUS.get(status)
        return f"HTTP {status} ({meaning})" if meaning else f"HTTP {status}"
    if isinstance(exc, (openai.APITimeoutError, httpx.TimeoutException, TimeoutError)):
        return "no answer in time"
    if isinstance(exc, (openai.APIConnectionError, httpx.TransportError, ConnectionError)):
        return "could not connect"
    if isinstance(exc, httpx.TooManyRedirects):
        return "too many redirects"
    if isinstance(exc, (json.JSONDecodeError, openai.APIResponseValidationError, httpx.DecodingError)):
        return "the answer could not be read"
    return f"an unexpected error ({type(exc).__name__}; the server log has the details)"
