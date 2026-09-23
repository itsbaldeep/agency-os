#!/usr/bin/env python3
"""Bounded public HTTP(S) fetching for untrusted research URLs.

The caller supplies a public URL and receives response bytes.  This module uses
direct ``http.client`` connections, so process proxy settings are ignored.  A
hostname is resolved once per redirect hop, every returned address must be
global, and the selected numeric address is pinned for the socket connection.
The original hostname remains on the connection for HTTP Host and TLS SNI.
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
from dataclasses import dataclass
from typing import Any
from urllib.parse import SplitResult, urljoin, urlsplit


MAX_BYTES = 300_000
MAX_TIMEOUT = 25.0
MAX_REDIRECTS = 3
_ALLOWED_SCHEMES = {"http", "https"}
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}


class PublicFetchError(Exception):
    """Internal safe error whose string never contains a URL or host."""


@dataclass(frozen=True)
class _Target:
    url: str
    parsed: SplitResult
    host: str
    host_header: str
    port: int
    family: int
    address: str

    @property
    def request_target(self) -> str:
        path = self.parsed.path or "/"
        return path + ("?" + self.parsed.query if self.parsed.query else "")


def _safe_failure(error: str) -> dict[str, Any]:
    return {"ok": False, "error": error}


def _public_ip(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise PublicFetchError("dns_invalid_address") from exc
    # IPv4-mapped IPv6 addresses inherit the security properties of the
    # embedded IPv4 address.
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None:
        address = mapped
    if not address.is_global or address.is_multicast or address.is_reserved:
        raise PublicFetchError("non_public_address")
    return address


def _resolve(host: str, port: int) -> tuple[int, str]:
    """Resolve once and return one validated numeric address.

    If a hostname has any non-global answer, reject the hop entirely.  Falling
    back from a public answer to an internal answer would make the fetcher
    vulnerable to split-horizon DNS and DNS rebinding assumptions.
    """
    try:
        answers = socket.getaddrinfo(
            host, port, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM,
        )
    except (OSError, socket.gaierror) as exc:
        raise PublicFetchError("dns_failed") from exc
    selected: tuple[int, str] | None = None
    seen: set[tuple[int, str]] = set()
    for family, _socktype, _proto, _canonname, sockaddr in answers:
        if family not in (socket.AF_INET, socket.AF_INET6) or not sockaddr:
            continue
        numeric = str(sockaddr[0])
        try:
            _public_ip(numeric)
        except PublicFetchError:
            raise
        key = (family, numeric)
        if key in seen:
            continue
        seen.add(key)
        if selected is None:
            selected = key
    if selected is None:
        raise PublicFetchError("dns_no_global_address")
    return selected


def _validate_target(url: str) -> _Target:
    if not isinstance(url, str) or not url or len(url) > 4096:
        raise PublicFetchError("invalid_url")
    try:
        parsed = urlsplit(url)
        scheme = parsed.scheme.lower()
        hostname = parsed.hostname
        port = parsed.port
    except (TypeError, ValueError):
        raise PublicFetchError("invalid_url")
    if scheme not in _ALLOWED_SCHEMES or not hostname:
        raise PublicFetchError("invalid_url")
    if parsed.username is not None or parsed.password is not None or parsed.fragment:
        raise PublicFetchError("invalid_url")
    if port is None:
        port = 443 if scheme == "https" else 80
    if port != (443 if scheme == "https" else 80):
        raise PublicFetchError("invalid_port")

    host = hostname.rstrip(".").lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise PublicFetchError("non_public_host")
    try:
        host_ascii = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise PublicFetchError("invalid_host") from exc
    if not host_ascii or ("." not in host_ascii and ":" not in host_ascii):
        raise PublicFetchError("non_public_host")

    try:
        literal = ipaddress.ip_address(host_ascii)
    except ValueError:
        literal = None
    if literal is not None:
        address = _public_ip(host_ascii)
        family = socket.AF_INET6 if address.version == 6 else socket.AF_INET
        numeric = str(address)
    else:
        family, numeric = _resolve(host_ascii, port)

    # Brackets belong only around a literal IPv6 Host value.  A DNS hostname
    # may resolve to IPv6 while its HTTP Host and TLS SNI remain the hostname.
    if ":" in host_ascii:
        host_header = "[" + host_ascii + "]"
    else:
        host_header = host_ascii
    # Canonicalize only the security-relevant URL components.  The response
    # contract deliberately does not return this URL, so it cannot leak it via
    # an error or result log.
    canonical = parsed._replace(scheme=scheme, netloc=host_header).geturl()
    return _Target(canonical, parsed._replace(scheme=scheme), host_ascii,
                   host_header, port, family, numeric)


def _connect_socket(family: int, address: str, port: int, timeout: float,
                    source_address: tuple[str, int] | None) -> socket.socket:
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        sock.settimeout(timeout)
        if source_address is not None:
            sock.bind(source_address)
        peer = (address, port, 0, 0) if family == socket.AF_INET6 else (address, port)
        sock.connect(peer)
        return sock
    except Exception:
        try:
            sock.close()
        except Exception:
            pass
        raise


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host: str, port: int, timeout: float, family: int,
                 address: str):
        self._pinned_family = family
        self._pinned_address = address
        super().__init__(host, port=port, timeout=timeout)
        # HTTPConnection stores socket.create_connection on the instance,
        # shadowing subclass methods. Replace that callback after init.
        self._create_connection = self._create_pinned_connection

    def _create_pinned_connection(self, _address, timeout, source_address=None):
        return _connect_socket(self._pinned_family, self._pinned_address,
                               self.port, timeout, source_address)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, port: int, timeout: float, family: int,
                 address: str):
        self._pinned_family = family
        self._pinned_address = address
        # HTTPSConnection retains ``host`` for certificate verification and SNI.
        # A default context keeps normal certificate and hostname checks active.
        super().__init__(host, port=port, timeout=timeout,
                         context=ssl.create_default_context())
        self._create_connection = self._create_pinned_connection

    def _create_pinned_connection(self, _address, timeout, source_address=None):
        return _connect_socket(self._pinned_family, self._pinned_address,
                               self.port, timeout, source_address)


def _request(target: _Target, timeout: float):
    connection_type = (_PinnedHTTPSConnection
                       if target.parsed.scheme == "https"
                       else _PinnedHTTPConnection)
    connection = connection_type(target.host, target.port, timeout,
                                 target.family, target.address)
    try:
        connection.request("GET", target.request_target, headers={
            "Accept": "text/html,*/*",
            "User-Agent": "AgencyOS Content Research; +deployden.tech",
            "Host": target.host_header,
        })
        return connection, connection.getresponse()
    except ssl.SSLError as exc:
        connection.close()
        raise PublicFetchError("tls_failed") from exc
    except (OSError, http.client.HTTPException) as exc:
        connection.close()
        raise PublicFetchError("connection_failed") from exc


def fetch(url: str, *, max_bytes: int = MAX_BYTES, timeout: float = MAX_TIMEOUT,
          max_redirects: int = MAX_REDIRECTS) -> dict[str, Any]:
    """Fetch bounded public response bytes without using environment proxies.

    Success: ``{"ok": True, "body": bytes, "status": int,
    "content_type": str, "redirects": int}``.
    Failure: ``{"ok": False, "error": <stable category>}``.
    """
    try:
        limit = min(MAX_BYTES, max(1, int(max_bytes)))
        wait = min(MAX_TIMEOUT, max(0.1, float(timeout)))
        redirects_allowed = min(MAX_REDIRECTS, max(0, int(max_redirects)))
    except (TypeError, ValueError, OverflowError):
        return _safe_failure("invalid_limits")

    current = url
    redirects = 0
    for _ in range(redirects_allowed + 1):
        try:
            target = _validate_target(current)
            connection, response = _request(target, wait)
        except PublicFetchError as exc:
            return _safe_failure(str(exc))
        try:
            status = int(response.status)
            if status in _REDIRECT_STATUSES:
                location = response.getheader("Location")
                response.close()
                connection.close()
                if not location or not isinstance(location, str):
                    return _safe_failure("redirect_missing_location")
                if redirects >= redirects_allowed:
                    return _safe_failure("redirect_limit")
                try:
                    current = urljoin(current, location)
                except Exception:
                    return _safe_failure("invalid_redirect")
                redirects += 1
                continue
            if status < 200 or status >= 300:
                response.close()
                connection.close()
                return _safe_failure("http_status_" + str(status))
            content_length = response.getheader("Content-Length")
            if content_length is not None:
                try:
                    if int(content_length) > limit:
                        response.close()
                        connection.close()
                        return _safe_failure("body_too_large")
                except (TypeError, ValueError, OverflowError):
                    response.close()
                    connection.close()
                    return _safe_failure("invalid_content_length")
            body = response.read(limit + 1)
            content_type = response.getheader("Content-Type", "")
            response.close()
            connection.close()
            if not isinstance(body, (bytes, bytearray)):
                return _safe_failure("read_failed")
            if len(body) > limit:
                return _safe_failure("body_too_large")
            return {
                "ok": True,
                "body": body,
                "status": status,
                "content_type": content_type,
                "redirects": redirects,
            }
        except (OSError, TypeError, ValueError, http.client.HTTPException):
            try:
                response.close()
                connection.close()
            except Exception:
                pass
            return _safe_failure("read_failed")
    return _safe_failure("redirect_limit")
