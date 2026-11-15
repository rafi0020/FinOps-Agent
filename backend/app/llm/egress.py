"""Where the server may connect when it calls a model provider.

A base URL is checked when it is saved and again whenever a connection is opened. The connection is made to the
address that was checked, never to the hostname, so a second DNS answer (DNS rebinding) cannot redirect it.
"""

import asyncio
import ipaddress
import socket
from collections.abc import Iterable
from urllib.parse import urlparse

import httpcore
import httpx
from httpcore._backends.auto import AutoBackend

from app.config import get_settings

# Loopback, RFC 1918 and unique-local addresses: allowed only when ALLOW_PRIVATE_LLM_URLS is true.
PRIVATE_NETWORKS = tuple(
    ipaddress.ip_network(n) for n in ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "::1/128", "fc00::/7")
)  # fmt: skip

REFUSED = "Base URL points to an address that is not allowed."
PRIVATE_REFUSED = "Base URLs on private networks are disabled on this deployment."
UNRESOLVED = "Base URL host cannot be resolved."


class UnsafeDestination(ValueError):
    """The server must not call this address. Raised before any connection is made."""


def address_problem(address: str, allow_private: bool) -> str | None:
    """Why the server may not connect to `address`, or None when it may."""
    ip = ipaddress.ip_address(address.split("%")[0])
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:  # ::ffff:10.0.0.1 is 10.0.0.1 for the purpose of this check
        ip = mapped
    if ip.is_multicast or ip.is_unspecified or ip.is_link_local:  # includes cloud metadata 169.254.169.254
        return REFUSED
    if any(ip in network for network in PRIVATE_NETWORKS):
        return None if allow_private else PRIVATE_REFUSED
    if not ip.is_global:  # carrier-grade NAT 100.64/10, reserved 240/4, benchmarking 198.18/15, documentation ranges
        return REFUSED
    return None


def resolve(host: str, port: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeDestination(UNRESOLVED) from exc
    return list(dict.fromkeys(info[4][0] for info in infos))


def check_addresses(host: str, port: int) -> list[str]:
    """Resolve once and check every answer. Returns the addresses the connection may be made to."""
    addresses = resolve(host, port)
    if not addresses:
        raise UnsafeDestination(UNRESOLVED)
    allow_private = get_settings().allow_private_llm_urls
    for address in addresses:
        problem = address_problem(address, allow_private)
        if problem:
            raise UnsafeDestination(problem)
    return addresses


def validate_base_url(url: str) -> None:
    """Refuse URLs the server should not be made to call. Raises ValueError with the reason."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Base URL must start with http:// or https:// and include a host.")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    check_addresses(parsed.hostname, port)


class GuardedBackend(httpcore.AsyncNetworkBackend):
    """Connects only to checked addresses, trying them in the order they were resolved."""

    def __init__(self, inner: httpcore.AsyncNetworkBackend | None = None):
        self._inner = inner or AutoBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,  # noqa: ASYNC109 - httpcore's interface
        local_address: str | None = None,
        socket_options: Iterable | None = None,
    ):
        addresses = await asyncio.to_thread(check_addresses, host, port)
        last: Exception | None = None
        for address in addresses:
            try:
                return await self._inner.connect_tcp(
                    address, port, timeout=timeout, local_address=local_address, socket_options=socket_options
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last = exc
        assert last is not None
        raise last

    async def connect_unix_socket(self, path: str, timeout: float | None = None, socket_options=None):  # noqa: ASYNC109
        raise UnsafeDestination(REFUSED)

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


class PinnedTransport(httpx.AsyncHTTPTransport):
    """The default transport for provider calls: every new connection passes through GuardedBackend."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._pool._network_backend = GuardedBackend(self._pool._network_backend)
