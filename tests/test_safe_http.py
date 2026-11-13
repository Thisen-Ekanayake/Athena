"""Addresses from outside (sources, feed links, article pages) are fetched from public hosts only, wherever the
fetch happens."""
from __future__ import annotations

import ipaddress
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from athena.api.config import settings
from athena.api.deps import get_db
from athena.api.main import app
from athena.core import safe_http
from athena.core.models import SourceType
from athena.database import user_sources

PUBLIC = "93.184.216.34"


def resolve_to(monkeypatch, table: dict[str, list[str]]) -> list[str]:
    """Names answer from ``table`` instead of DNS; returns the names that were looked up."""
    asked: list[str] = []
    real = socket.getaddrinfo

    def getaddrinfo(host, port, *args, **kwargs):
        try:
            ipaddress.ip_address(host)
            return real(host, port, *args, **kwargs)  # an address needs no lookup: the socket being opened
        except ValueError:
            pass
        if host not in table:
            raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
        asked.append(host)
        return [(socket.AF_INET6 if ":" in a else socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, port))
                for a in table[host]]

    monkeypatch.setattr(safe_http.socket, "getaddrinfo", getaddrinfo)
    return asked


@pytest.fixture
def local_server():
    """A web server on this machine: /feed answers, /hop redirects to its own address."""
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/hop":
                self.send_response(302)
                self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/feed")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"inside")

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_port
    server.shutdown()
    server.server_close()


# ── which addresses ──────────────────────────────────────────────────


@pytest.mark.parametrize("address", [
    "127.0.0.1", "10.1.2.3", "172.16.0.9", "192.168.1.20", "169.254.169.254", "100.64.0.1", "0.0.0.0", "224.0.0.1",
    "::1", "fe80::1", "fc00::1", "::ffff:127.0.0.1", "::ffff:10.0.0.1", "2002:7f00:1::",
])
def test_addresses_on_the_machine_or_its_network_are_not_public(address):
    assert not safe_http._public(ipaddress.ip_address(address))


@pytest.mark.parametrize("address", ["8.8.8.8", PUBLIC, "2606:4700:4700::1111"])
def test_addresses_out_on_the_internet_are(address):
    assert safe_http._public(ipaddress.ip_address(address))


@pytest.mark.parametrize("url, why", [
    ("file:///etc/passwd", "Only http"),
    ("ftp://example.org/feed", "Only http"),
    ("gopher://127.0.0.1:6379/_FLUSHALL", "Only http"),
    ("http:///feed", "no host"),
    ("http://127.0.0.1:6333/collections", "own machine or network"),
    ("http://[::1]:8080/v1/models", "own machine or network"),
    ("http://169.254.169.254/latest/meta-data/", "own machine or network"),
    ("http://qdrant:6333/", "own machine or network"),              # a name on the private network
    ("https://both.example/feed", "own machine or network"),        # one public address, one private
    ("https://nowhere.example/feed", "was not found"),
])
def test_addresses_athena_will_not_fetch(monkeypatch, url, why):
    resolve_to(monkeypatch, {"qdrant": ["172.18.0.4"], "both.example": [PUBLIC, "10.0.0.7"]})
    with pytest.raises(safe_http.Blocked, match=why):
        safe_http.check_url(url)


def test_a_public_address_passes_and_named_private_hosts_are_allowed(monkeypatch):
    resolve_to(monkeypatch, {"blog.example": [PUBLIC], "bridge.lan": ["192.168.1.20"]})
    assert safe_http.check_url("  https://blog.example/feed.xml ") == "https://blog.example/feed.xml"
    with pytest.raises(safe_http.Blocked):
        safe_http.check_url("http://bridge.lan:1200/feed")
    monkeypatch.setattr(settings, "FETCH_ALLOW_HOSTS", ["bridge.lan", "10.8.0.0/24"])
    assert safe_http.check_url("http://bridge.lan:1200/feed")
    assert safe_http.check_url("http://10.8.0.5/feed")
    with pytest.raises(safe_http.Blocked):
        safe_http.check_url("http://10.9.0.5/feed")


def test_a_host_is_matched_whole_not_as_text():
    assert safe_http.host_is("https://export.arxiv.org/api/query", "arxiv.org")
    assert safe_http.host_is("https://ARXIV.org/abs/1706.03762", "arxiv.org")
    assert not safe_http.host_is("https://example.com/arxiv.org", "arxiv.org")
    assert not safe_http.host_is("https://arxiv.org.example.com/", "arxiv.org")
    assert not safe_http.host_is("https://notarxiv.org/", "arxiv.org")


# ── the clients ──────────────────────────────────────────────────────


def test_the_client_does_not_connect_to_this_machine(local_server):
    with safe_http.client(timeout=5) as client:
        with pytest.raises(safe_http.Blocked):
            client.get(f"http://127.0.0.1:{local_server}/feed")
        with pytest.raises(safe_http.Blocked):
            client.get(f"http://localhost:{local_server}/feed")


async def test_nor_does_the_async_client(local_server):
    async with safe_http.async_client(timeout=5) as client:
        with pytest.raises(safe_http.Blocked):
            await client.get(f"http://127.0.0.1:{local_server}/feed")


def test_a_redirect_to_a_private_address_ends_there(monkeypatch, local_server):
    """feeds.test is allowed by name (and answers from this machine, standing in for a public site); the address
    it redirects to is not."""
    resolve_to(monkeypatch, {"feeds.test": ["127.0.0.1"]})
    monkeypatch.setattr(settings, "FETCH_ALLOW_HOSTS", ["feeds.test"])
    with safe_http.client(timeout=5) as client:
        assert client.get(f"http://feeds.test:{local_server}/feed").text == "inside"
        with pytest.raises(safe_http.Blocked):
            client.get(f"http://feeds.test:{local_server}/hop")


def test_the_socket_goes_to_the_address_that_was_checked(monkeypatch):
    """A name that answers with a public address for the check and a private one afterwards (DNS rebinding) is
    looked up once: the connection is made to what was checked."""
    asked = resolve_to(monkeypatch, {"rebind.example": [PUBLIC]})
    backend, connected = safe_http._Backend(), []
    backend._inner = SimpleNamespace(connect_tcp=lambda address, port, **kw: connected.append((address, port)) or "s")
    assert backend.connect_tcp("rebind.example", 443) == "s"
    assert connected == [(PUBLIC, 443)] and asked == ["rebind.example"]


def test_behind_a_proxy_each_request_is_checked_instead(monkeypatch, local_server):
    monkeypatch.setattr(safe_http, "_proxied", lambda: True)
    with safe_http.client(timeout=5, trust_env=False) as client:
        with pytest.raises(safe_http.Blocked):
            client.get(f"http://127.0.0.1:{local_server}/feed")


def test_a_guard_that_no_longer_fits_httpx_fails_loudly():
    with pytest.raises(RuntimeError, match="httpx changed"):
        safe_http._guarded(SimpleNamespace(), safe_http._Backend())


# ── the browser ──────────────────────────────────────────────────────


class FakeRoute:
    def __init__(self):
        self.outcome = None

    async def continue_(self):
        self.outcome = "continued"

    async def abort(self, reason):
        self.outcome = reason


class FakePage:
    """Goes where it is told; ``lands`` is where the browser ended up after its own redirects."""

    def __init__(self, lands: str | None = None, answered: str | None = None):
        self.url, self.lands, self.answered, self.visited = "about:blank", lands, answered, []

    async def goto(self, url, **kwargs):
        self.visited.append(url)
        self.url = url if url == "about:blank" else (self.lands or url)
        answered = self.answered

        async def server_addr():
            return {"ipAddress": answered, "port": 443} if answered else None
        return SimpleNamespace(server_addr=server_addr)


async def test_the_browser_cannot_ask_this_machine_for_anything(monkeypatch):
    resolve_to(monkeypatch, {"blog.example": [PUBLIC]})
    handlers = []

    async def route(pattern, handler):
        handlers.append(handler)
    await safe_http.guard_browser(SimpleNamespace(route=route))

    async def outcome(url):
        r = FakeRoute()
        await handlers[0](r, SimpleNamespace(url=url))
        return r.outcome
    assert await outcome("https://blog.example/post") == "continued"
    assert await outcome("data:text/plain,hello") == "continued"
    assert await outcome("http://127.0.0.1:6333/collections") == "blockedbyclient"  # a script asking Qdrant
    assert await outcome("http://localhost:8080/v1/chat/completions") == "blockedbyclient"
    assert await outcome("file:///etc/passwd") == "blockedbyclient"


async def test_a_page_is_refused_before_it_loads_and_when_a_private_address_answered(monkeypatch):
    resolve_to(monkeypatch, {"blog.example": [PUBLIC], "intranet.example": ["10.0.0.7"]})
    page = FakePage()
    with pytest.raises(safe_http.Blocked):
        await safe_http.goto(page, "file:///etc/passwd")
    with pytest.raises(safe_http.Blocked):
        await safe_http.goto(page, "http://127.0.0.1:6333/")
    assert page.visited == []

    fine = FakePage(answered=PUBLIC)
    await safe_http.goto(fine, "https://blog.example/post")
    assert fine.url == "https://blog.example/post"

    redirected = FakePage(lands="http://intranet.example/admin")
    with pytest.raises(safe_http.Blocked):
        await safe_http.goto(redirected, "https://blog.example/post")
    assert redirected.url == "about:blank"   # what it loaded is not left for the scraper to read

    rebound = FakePage(answered="127.0.0.1")
    with pytest.raises(safe_http.Blocked):
        await safe_http.goto(rebound, "https://blog.example/post")
    assert rebound.url == "about:blank"


# ── sources ──────────────────────────────────────────────────────────


def test_known_publishers_are_told_by_host(monkeypatch):
    monkeypatch.setattr(safe_http, "client", lambda **kw: (_ for _ in ()).throw(AssertionError("no fetch needed")))
    assert user_sources.detect_source_type("https://export.arxiv.org/api/query") == SourceType.API
    assert user_sources.detect_source_type("https://www.lesswrong.com/feed.xml") == SourceType.SCRAPE


def test_a_page_that_only_mentions_a_publisher_is_fetched_like_any_other(monkeypatch):
    fetched = []

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get(self, url):
            fetched.append(url)
            return SimpleNamespace(headers={"Content-Type": "application/rss+xml"}, text="")
    monkeypatch.setattr(safe_http, "client", lambda **kw: Client())
    assert user_sources.detect_source_type("https://example.com/?next=arxiv.org") == SourceType.RSS
    assert fetched == ["https://example.com/?next=arxiv.org"]


def test_a_source_on_athenas_own_network_is_refused_before_anything_is_fetched(monkeypatch):
    monkeypatch.setattr(user_sources, "preview_source", lambda *a, **kw: pytest.fail("nothing should be fetched"))
    app.dependency_overrides[get_db] = lambda: None
    try:
        api = TestClient(app)
        for url in ("http://127.0.0.1:6333/collections", "file:///etc/passwd", "http://169.254.169.254/"):
            refused = api.post("/api/v1/sources", json={"url": url})
            assert refused.status_code == 400 and "cannot be a source" in refused.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_db, None)
