"""
Fetching addresses that came from outside: a source an admin typed, a link in a feed or on a page, an item's URL.

None of them may reach Athena's own machine or network (the model server, Redis, Qdrant, a router's admin page,
a cloud metadata address). What a fetch brings back is stored as a feed item or read out by the model, so a source
at ``http://localhost:6333/...`` would publish the vector store to every account. The rule is the same everywhere:
only http(s), and only hosts whose every address is public.

- ``check_url(url)`` says no early, with a sentence for the person who typed the address (the source routes).
- ``client()`` / ``async_client()`` are httpx clients that apply the rule where the connection is made: the name
  is resolved once, every address has to be public, and the socket goes to one of those addresses. A redirect to
  a private address, and a name that answers differently between a check and the fetch (DNS rebinding), end at
  the same refusal. Behind HTTP(S)_PROXY the proxy makes the connection, so there each request's address is
  checked instead.
- ``guard_browser(context)`` and ``goto(page, url)`` do it for Playwright: the browser's requests to private
  addresses are aborted (a page's script cannot ask the model server or Qdrant either), and a page that turns
  out to have been answered from a private address is thrown away.

A feed on the private network (an RSS bridge on the same machine) is allowed by naming its host in
FETCH_ALLOW_HOSTS: host names, addresses or CIDR ranges, comma-separated. It is read from the environment only,
so nothing in the web app can widen it.
"""
from __future__ import annotations

import ipaddress
import socket
import urllib.request
from urllib.parse import urlsplit

import anyio
import httpcore
import httpx
from loguru import logger

SCHEMES = ("http", "https")
PORTS = {"http": 80, "https": 443}


class Blocked(httpx.ConnectError):
    """Athena does not fetch this address; ``str()`` says why. A connection error, so code that already handles
    a failed fetch handles a refused one."""


def _allow_list() -> tuple[set[str], list]:
    from athena.api.config import settings
    names, networks = set(), []
    for part in settings.FETCH_ALLOW_HOSTS:
        try:
            networks.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            names.add(part.lower().rstrip("."))
    return names, networks


def _public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Whether ``ip`` is out on the internet: not loopback, private, link-local, shared, reserved or multicast.
    An IPv4 address carried inside an IPv6 one (mapped, 6to4) is judged as the IPv4 address."""
    inner = getattr(ip, "ipv4_mapped", None) or getattr(ip, "sixtofour", None)
    if inner is not None:
        return _public(inner)
    return ip.is_global and not ip.is_multicast


def _host(host: str) -> str:
    return host.strip().strip("[]").rstrip(".").lower()


def addresses(host: str, port: int) -> list[str]:
    """The addresses ``host`` may be reached at. Raises Blocked when it is, or resolves to, an address that is not
    public (a name with one public and one private address is refused whole), and OSError when it does not
    resolve."""
    host = _host(host)
    names, networks = _allow_list()
    try:
        found = [ipaddress.ip_address(host)]
    except ValueError:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        found = [ipaddress.ip_address(info[4][0].split("%")[0]) for info in infos]
    if host not in names:
        for ip in found:
            if not _public(ip) and not any(ip.version == n.version and ip in n for n in networks):
                raise Blocked(f"{host} is on Athena's own machine or network ({ip}), which is never fetched")
    return list(dict.fromkeys(str(ip) for ip in found))


def host_is(url: str, *domains: str) -> bool:
    """Whether ``url``'s host is one of ``domains`` or under one (export.arxiv.org is arxiv.org). The host is
    compared, not the text, so https://example.com/arxiv.org is not arXiv."""
    try:
        host = _host(urlsplit(url.strip()).hostname or "")
    except ValueError:
        return False
    return any(host == d or host.endswith("." + d) for d in domains)


def check_url(url: str) -> str:
    """``url`` (trimmed) when Athena may fetch it; otherwise raises Blocked with the reason. Looks the host up."""
    url = (url or "").strip()
    try:
        parts = urlsplit(url)
        host, port = parts.hostname, parts.port
    except ValueError:
        raise Blocked("That is not a web address")
    if parts.scheme.lower() not in SCHEMES:
        raise Blocked("Only http:// and https:// addresses are fetched")
    if not host:
        raise Blocked("That address has no host name")
    try:
        addresses(host, port or PORTS[parts.scheme.lower()])
    except Blocked:
        raise
    except (OSError, UnicodeError):
        raise Blocked(f"{host} was not found (the name does not resolve)")
    return url


# ── httpx ──────────────────────────────────────────────────────────────


def _connect_error(host: str, exc: Exception) -> httpcore.ConnectError:
    return httpcore.ConnectError(f"{host}: {exc}")


class _Backend(httpcore.NetworkBackend):
    """Opens sockets only to public addresses: the name is resolved here and the socket goes to what was checked."""

    def __init__(self) -> None:
        self._inner = httpcore.SyncBackend()

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        try:
            found = addresses(host, port)
        except (OSError, UnicodeError) as exc:
            raise _connect_error(host, exc) from exc
        error: Exception | None = None
        for address in found:
            try:
                return self._inner.connect_tcp(address, port, timeout=timeout, local_address=local_address,
                                               socket_options=socket_options)
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                error = exc
        raise error or httpcore.ConnectError(f"{host} has no address")

    def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise Blocked("Unix sockets are never fetched")

    def sleep(self, seconds: float) -> None:
        self._inner.sleep(seconds)


class _AsyncBackend(httpcore.AsyncNetworkBackend):
    def __init__(self) -> None:
        self._inner = httpcore.AnyIOBackend()

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        try:
            found = await anyio.to_thread.run_sync(addresses, host, port)
        except (OSError, UnicodeError) as exc:
            raise _connect_error(host, exc) from exc
        error: Exception | None = None
        for address in found:
            try:
                return await self._inner.connect_tcp(address, port, timeout=timeout, local_address=local_address,
                                                     socket_options=socket_options)
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                error = exc
        raise error or httpcore.ConnectError(f"{host} has no address")

    async def connect_unix_socket(self, path, timeout=None, socket_options=None):
        raise Blocked("Unix sockets are never fetched")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


def _guarded(transport, backend):
    """Put ``backend`` under an httpx transport. httpx offers no argument for it, so this reaches into the pool;
    if a later httpx keeps its pool elsewhere, fail here rather than fetch unguarded."""
    pool = getattr(transport, "_pool", None)
    if not hasattr(pool, "_network_backend"):
        raise RuntimeError("httpx changed where its connection pool lives; update athena.core.safe_http")
    pool._network_backend = backend
    return transport


def _check_request(request: httpx.Request) -> None:
    check_url(str(request.url))


async def _check_request_async(request: httpx.Request) -> None:
    await anyio.to_thread.run_sync(check_url, str(request.url))


def _proxied() -> bool:
    return any(scheme in urllib.request.getproxies() for scheme in ("http", "https", "all"))


def client(**kwargs) -> httpx.Client:
    """An httpx.Client for addresses from outside; redirects are followed (and checked) unless told otherwise."""
    kwargs.setdefault("follow_redirects", True)
    if _proxied():
        return httpx.Client(event_hooks={"request": [_check_request]}, **kwargs)
    return httpx.Client(transport=_guarded(httpx.HTTPTransport(), _Backend()), **kwargs)


def async_client(**kwargs) -> httpx.AsyncClient:
    """The same as ``client`` for async code."""
    kwargs.setdefault("follow_redirects", True)
    if _proxied():
        return httpx.AsyncClient(event_hooks={"request": [_check_request_async]}, **kwargs)
    return httpx.AsyncClient(transport=_guarded(httpx.AsyncHTTPTransport(), _AsyncBackend()), **kwargs)


# ── Playwright ─────────────────────────────────────────────────────────


async def guard_browser(context) -> None:
    """Abort every request a Playwright context makes to a non-public address: the page's own and those of its
    frames, scripts and images. Each host is looked up once per context."""
    verdicts: dict[tuple[str, int], bool] = {}

    async def decide(route, request) -> None:
        parts = urlsplit(request.url)
        scheme = parts.scheme.lower()
        if scheme in ("data", "blob", "about"):
            await route.continue_()
            return
        key = (parts.hostname or "", parts.port or PORTS.get(scheme, 0))
        if key not in verdicts:
            try:
                await anyio.to_thread.run_sync(check_url, request.url)
                verdicts[key] = True
            except Blocked as exc:
                logger.warning(f"Browser request refused: {exc}")
                verdicts[key] = False
        if verdicts[key]:
            await route.continue_()
        else:
            await route.abort("blockedbyclient")

    await context.route("**/*", decide)


async def goto(page, url: str, **kwargs):
    """``page.goto`` for an address from outside. Refused before it loads when it is not public; and because the
    browser follows redirects by itself, the page is emptied and refused when what answered was not public."""
    await anyio.to_thread.run_sync(check_url, url)
    response = await page.goto(url, **kwargs)
    try:
        await anyio.to_thread.run_sync(check_url, page.url)
        # The address that really answered; through a proxy that is the proxy's, and an allowed name stays allowed
        named = _host(urlsplit(page.url).hostname or "") in _allow_list()[0]
        answered = await response.server_addr() if response is not None and not named and not _proxied() else None
        if answered and answered.get("ipAddress"):
            addresses(answered["ipAddress"], int(answered.get("port") or 0))
    except Blocked:
        await page.goto("about:blank")
        raise
    return response
