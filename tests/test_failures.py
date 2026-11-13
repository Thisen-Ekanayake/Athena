"""A failed call tells the page the kind of failure; the exception's own text stays in the log."""
from __future__ import annotations

from types import SimpleNamespace

import httpx
import openai
import pytest

from athena.core import failures, safe_http
from athena.core.models import SourceType
from athena.database import user_sources


def _status_error(status: int, body=None) -> openai.APIStatusError:
    request = httpx.Request("POST", "http://127.0.0.1:8080/v1/chat/completions")
    return openai.APIStatusError("boom at http://127.0.0.1:8080 with key sk-secret",
                                 response=SimpleNamespace(status_code=status, request=request, headers={}),
                                 body=body)


@pytest.mark.parametrize("exc, says", [
    (httpx.ConnectError("connection refused 127.0.0.1:8080"), "could not connect"),
    (httpx.ReadTimeout("timed out reading /srv/athena/secret"), "no answer in time"),
    (TimeoutError("slow"), "no answer in time"),
    (ConnectionRefusedError("127.0.0.1:8080"), "could not connect"),
    (_status_error(404), "HTTP 404 (not found there)"),
    (_status_error(401), "HTTP 401 (the API key was refused)"),
    (_status_error(418), "HTTP 418"),
    (_status_error(400, {"error": {"type": "exceed_context_size_error", "message": "n_ctx 8192 at /models/x"}}),
     "the request is longer than the model's context"),
    (safe_http.Blocked("x is on Athena's own machine"), "that address is on Athena's own machine or network"),
    (KeyError("password=hunter2"), "an unexpected error (KeyError; the server log has the details)"),
])
def test_a_failure_is_described_by_its_kind_never_its_text(exc, says):
    described = failures.describe(exc)
    assert described == says
    for leak in ("127.0.0.1", "sk-secret", "/srv", "/models", "hunter2"):
        assert leak not in described


def test_a_source_that_cannot_be_read_says_what_kind_of_failure(monkeypatch):
    """The preview's error is the kind of failure; the exception's own text stays in the log."""
    from athena.scrapers import rss

    async def fails(self, url):
        raise httpx.ConnectError("[Errno 111] Connection refused to 10.0.0.9:8443 (key=sk-secret)")
    monkeypatch.setattr(user_sources, "detect_source_type", lambda url: SourceType.RSS)
    monkeypatch.setattr(rss.RSSScraper, "fetch", fails)
    preview = user_sources.preview_source("https://blog.example/feed")
    assert preview["error"] == "could not connect" and preview["sample_items"] == []
