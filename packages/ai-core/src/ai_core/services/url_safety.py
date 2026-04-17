"""URL safety helpers — SSRF protection for outbound fetches.

Any code path that dereferences a user-provided URL (character audio clips,
voice clone samples, webhook callbacks, etc.) MUST go through
``fetch_public_url`` or at minimum call ``assert_public_http_url`` before
opening a connection.

Security guarantees:
  - Only http(s) scheme accepted
  - Hostname must resolve to globally-routable IP(s)
  - Rejects loopback / private / link-local / shared (CGNAT) / multicast /
    reserved / unspecified addresses
  - Strips URL credentials (user:pass@)
  - **Prevents DNS rebinding**: the resolved IP is reused for the actual
    connect, not re-resolved by httpx
  - Enforces per-hop redirect validation with the same rules
  - Caps total download size
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

_MAX_REDIRECTS = 5


@dataclass(frozen=True)
class FetchResult:
    url: str                # final URL after redirects (hostname form)
    content: bytes
    content_type: str


def _is_safe_ip(value: str) -> bool:
    """Return True iff ``value`` is a globally-routable unicast IP.

    Reject the usual SSRF targets (loopback, private, link-local, CGNAT,
    multicast, reserved, unspecified, documentation). ``is_global`` alone
    does not cover all of these consistently across Python versions, so
    we enumerate the deny-list explicitly.
    """
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    if (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        return False
    # IPv4 shared address space (CGNAT) — not covered by is_private
    if isinstance(ip, ipaddress.IPv4Address) and ip in ipaddress.IPv4Network("100.64.0.0/10"):
        return False
    # IPv4-mapped IPv6 (e.g. ::ffff:127.0.0.1) — check embedded v4
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return _is_safe_ip(str(ip.ipv4_mapped))
    return True


async def _resolve_host_ips(hostname: str, port: int) -> list[str]:
    loop = asyncio.get_running_loop()
    addrinfo = await loop.getaddrinfo(
        hostname,
        port,
        type=socket.SOCK_STREAM,
        proto=socket.IPPROTO_TCP,
    )
    # getaddrinfo returns duplicates; preserve first-seen order
    seen: list[str] = []
    for item in addrinfo:
        if item and item[4]:
            ip = item[4][0]
            if ip not in seen:
                seen.append(ip)
    return seen


async def _resolve_and_validate(
    url: str,
    *,
    resolver=_resolve_host_ips,
) -> tuple[str, int, list[str]]:
    """Parse URL, resolve hostname to IP list, validate every IP is public.

    Returns (hostname, port, resolved_ips). Raises RuntimeError on any
    safety violation.
    """
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise RuntimeError("url_safety: only http(s) URLs are allowed")
    if parsed.username or parsed.password:
        raise RuntimeError("url_safety: credentialed URLs are not allowed")

    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    # If host is a literal IP address, validate it directly — don't
    # attempt DNS. Anything else goes through the resolver.
    try:
        ipaddress.ip_address(host)
        is_literal_ip = True
    except ValueError:
        is_literal_ip = False

    if is_literal_ip:
        if not _is_safe_ip(host):
            raise RuntimeError("url_safety: URL resolves to a non-public IP")
        return host, port, [host]

    try:
        resolved = await resolver(host, port)
    except OSError as e:
        raise RuntimeError(f"url_safety: unable to resolve host: {e}") from e

    if not resolved:
        raise RuntimeError("url_safety: host did not resolve to any IP")
    for ip in resolved:
        if not _is_safe_ip(ip):
            raise RuntimeError(
                f"url_safety: host resolves to non-public IP ({ip})"
            )
    return host, port, resolved


def _rewrite_to_ip(url: str, ip: str) -> str:
    """Rewrite URL so httpx connects to ``ip`` directly (not via DNS)."""
    parsed = urlsplit(url)
    # IPv6 literals need brackets
    ip_host = f"[{ip}]" if ":" in ip else ip
    port = parsed.port
    netloc = f"{ip_host}:{port}" if port else ip_host
    return urlunsplit((parsed.scheme, netloc, parsed.path or "/", parsed.query, parsed.fragment))


async def assert_public_http_url(url: str) -> None:
    """Minimal check: resolve + validate all IPs. No connect."""
    await _resolve_and_validate(url)


async def fetch_public_url(
    url: str,
    *,
    max_bytes: int = 25 * 1024 * 1024,
    timeout_s: float = 30.0,
    allowed_content_types: tuple[str, ...] | None = None,
) -> FetchResult:
    """Download ``url`` safely. Pins resolved IP to defeat DNS rebinding,
    validates every redirect hop, and caps download size.

    Raises RuntimeError on any safety violation or network failure.
    """
    current_url = url
    async with httpx.AsyncClient(
        timeout=timeout_s,
        follow_redirects=False,
        trust_env=False,
    ) as client:
        for _ in range(_MAX_REDIRECTS + 1):
            host, _port, resolved = await _resolve_and_validate(current_url)
            # IP-pin: send the request to the resolved IP directly, but
            # preserve the Host header so TLS SNI / virtual hosting works.
            pinned_url = _rewrite_to_ip(current_url, resolved[0])
            try:
                async with client.stream(
                    "GET",
                    pinned_url,
                    headers={"Host": host},
                ) as resp:
                    if resp.status_code in (301, 302, 303, 307, 308):
                        location = resp.headers.get("location")
                        if not location:
                            raise RuntimeError("url_safety: redirect missing location")
                        # Next hop goes through full validation again
                        current_url = urljoin(current_url, location)
                        continue

                    if resp.status_code != 200:
                        raise RuntimeError(
                            f"url_safety: HTTP {resp.status_code} from {host}"
                        )

                    content_type = resp.headers.get("content-type", "").lower()
                    if allowed_content_types and not content_type.startswith(allowed_content_types):
                        raise RuntimeError(
                            f"url_safety: content-type {content_type!r} not allowed"
                        )

                    content_length = resp.headers.get("content-length")
                    if content_length:
                        try:
                            if int(content_length) > max_bytes:
                                raise RuntimeError(
                                    f"url_safety: content exceeds {max_bytes // (1024*1024)}MB limit"
                                )
                        except ValueError:
                            pass

                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in resp.aiter_bytes():
                        size += len(chunk)
                        if size > max_bytes:
                            raise RuntimeError(
                                f"url_safety: content exceeds {max_bytes // (1024*1024)}MB limit"
                            )
                        chunks.append(chunk)
                    return FetchResult(
                        url=current_url,
                        content=b"".join(chunks),
                        content_type=content_type,
                    )
            except httpx.HTTPError as e:
                raise RuntimeError(f"url_safety: fetch failed: {e}") from e

    raise RuntimeError("url_safety: too many redirects")
