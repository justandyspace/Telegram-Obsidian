"""Safe HTTP helpers for parser fetches."""

from __future__ import annotations

import ipaddress
import socket
import time
from urllib.parse import urljoin, urlparse

import requests

from src.infra.resilience import (
    CircuitBreakerOpenError,
    CircuitBreakerRegistry,
    RetryPolicy,
)


class UnsafeUrlError(ValueError):
    """Raised when URL is unsafe for outbound fetching."""


class HttpFetchError(RuntimeError):
    """Raised for guarded fetch failures."""


BLOCKED_HOST_SUFFIXES = (
    ".local",
    ".internal",
    ".lan",
    ".home",
    ".corp",
)
RETRYABLE_HTTP_STATUSES = {408, 425, 429, 500, 502, 503, 504}
DEFAULT_RETRY_POLICY = RetryPolicy(max_attempts=3, base_delay_seconds=0.5, max_delay_seconds=4.0)
DEFAULT_CIRCUIT_BREAKER = CircuitBreakerRegistry(failure_threshold=3, cooldown_seconds=30.0)


def validate_public_http_url(url: str) -> None:
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in {"http", "https"}:
        raise UnsafeUrlError("Only http/https URLs are allowed.")
    if parsed.username or parsed.password:
        raise UnsafeUrlError("URL credentials are not allowed.")

    if parsed.port is not None and (parsed.port <= 0 or parsed.port > 65535):
        raise UnsafeUrlError("URL port is invalid.")  # pragma: no cover

    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise UnsafeUrlError("URL hostname is missing.")
    if host == "localhost" or any(host.endswith(suffix) for suffix in BLOCKED_HOST_SUFFIXES):
        raise UnsafeUrlError("Local/internal domains are blocked.")

    try:
        ip_literal = ipaddress.ip_address(host)
        _ensure_public_ip(ip_literal)
        return
    except ValueError:
        pass

    resolved_ips = _resolve_host_ips(host)
    if not resolved_ips:
        raise UnsafeUrlError("Could not resolve URL host.")
    for item in resolved_ips:
        _ensure_public_ip(item)


def safe_http_get(
    url: str,
    *,
    timeout_seconds: int,
    headers: dict[str, str] | None = None,
    max_redirects: int = 3,
    stream: bool = False,
    max_body_bytes: int | None = None,
    retry_policy: RetryPolicy = DEFAULT_RETRY_POLICY,
    breaker: CircuitBreakerRegistry = DEFAULT_CIRCUIT_BREAKER,
) -> requests.Response:
    current = url
    redirects = 0
    with requests.Session() as session:
        while True:
            validate_public_http_url(current)
            host = (urlparse(current).hostname or "").strip().lower()
            if not host:
                raise UnsafeUrlError("URL hostname is missing.")  # pragma: no cover

            response = _request_with_resilience(
                session,
                current,
                timeout_seconds=timeout_seconds,
                headers=headers,
                stream=stream,
                retry_policy=retry_policy,
                breaker=breaker,
                breaker_key=host,
            )

            if 300 <= response.status_code < 400:
                location = response.headers.get("Location", "").strip()
                if not location:
                    return response
                next_url = urljoin(current, location)
                response.close()
                redirects += 1
                if redirects > max_redirects:
                    raise HttpFetchError("Too many redirects.")
                current = next_url
                continue

            validate_public_http_url(response.url)
            if max_body_bytes is not None:
                _enforce_max_body_size(response, max_body_bytes=max_body_bytes, stream=stream)
            return response


def _request_with_resilience(
    session: requests.Session,
    url: str,
    *,
    timeout_seconds: int,
    headers: dict[str, str] | None,
    stream: bool,
    retry_policy: RetryPolicy,
    breaker: CircuitBreakerRegistry,
    breaker_key: str,
) -> requests.Response:
    attempts = retry_policy.clamp_attempts()
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            breaker.before_call(breaker_key)
            response = session.get(
                url,
                timeout=timeout_seconds,
                headers=headers,
                allow_redirects=False,
                stream=stream,
            )
            if response.status_code in RETRYABLE_HTTP_STATUSES and attempt < attempts:
                breaker.record_failure(breaker_key)
                response.close()
                time.sleep(retry_policy.backoff_delay(attempt))
                continue
            if response.status_code in RETRYABLE_HTTP_STATUSES:
                breaker.record_failure(breaker_key)
            else:
                breaker.record_success(breaker_key)
            return response
        except (requests.Timeout, requests.ConnectionError, CircuitBreakerOpenError) as exc:
            breaker.record_failure(breaker_key)
            last_error = exc
            if attempt >= attempts:
                break
            time.sleep(retry_policy.backoff_delay(attempt))
    if last_error is not None:
        raise HttpFetchError(f"HTTP request failed after retries: {last_error}") from last_error
    raise HttpFetchError("HTTP request failed after retries.")  # pragma: no cover


def _resolve_host_ips(host: str) -> set[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"Host resolution failed: {exc}") from exc

    resolved: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = set()
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue  # pragma: no cover
        ip_raw = sockaddr[0]
        try:
            resolved.add(ipaddress.ip_address(ip_raw))
        except ValueError:
            continue  # pragma: no cover
    return resolved


def _ensure_public_ip(ip_value: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    if (
        ip_value.is_private
        or ip_value.is_loopback
        or ip_value.is_link_local
        or ip_value.is_reserved
        or ip_value.is_multicast
        or ip_value.is_unspecified
    ):
        raise UnsafeUrlError(f"Blocked non-public IP: {ip_value}")


def _enforce_max_body_size(response: requests.Response, *, max_body_bytes: int, stream: bool) -> None:
    content_length_raw = (response.headers.get("Content-Length") or "").strip()
    if content_length_raw.isdigit() and int(content_length_raw) > max_body_bytes:
        response.close()
        raise HttpFetchError(
            f"Response too large by Content-Length: {content_length_raw} > {max_body_bytes}"
        )

    if stream:
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_content(chunk_size=65536):
            if not chunk:
                continue
            total += len(chunk)
            if total > max_body_bytes:
                response.close()
                raise HttpFetchError(f"Response too large while streaming: {total} > {max_body_bytes}")
            chunks.append(chunk)
        response._content = b"".join(chunks)
        response.__dict__["_content_consumed"] = True
        return

    if len(response.content) > max_body_bytes:
        response.close()
        raise HttpFetchError(
            f"Response too large by payload: {len(response.content)} > {max_body_bytes}"
        )
