from __future__ import annotations

import io
import ipaddress
import unittest
from unittest.mock import patch

import requests
from requests.structures import CaseInsensitiveDict

from src.infra.resilience import CircuitBreakerRegistry, RetryPolicy
from src.parsers.url_safety import HttpFetchError, UnsafeUrlError, safe_http_get, validate_public_http_url


def _response(*, url: str, status: int, body: bytes = b"ok", headers: dict[str, str] | None = None) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response.url = url
    response._content = body
    response._content_consumed = True
    response.raw = io.BytesIO(body)
    response.headers = CaseInsensitiveDict(headers or {})
    return response


class UrlResilienceTests(unittest.TestCase):
    def test_validate_blocks_credentials(self) -> None:
        with self.assertRaises(UnsafeUrlError):
            validate_public_http_url("https://user:pass@example.com/secret")

    def test_retries_on_retryable_status_then_succeeds(self) -> None:
        first = _response(url="https://example.com", status=503)
        second = _response(url="https://example.com", status=200, body=b"hello")
        retry_policy = RetryPolicy(
            max_attempts=2,
            base_delay_seconds=0.0,
            max_delay_seconds=0.0,
            jitter_ratio=0.0,
        )
        breaker = CircuitBreakerRegistry(failure_threshold=5, cooldown_seconds=1.0)
        with (
            patch("src.parsers.url_safety._resolve_host_ips", return_value={ipaddress.ip_address("93.184.216.34")}),
            patch.object(requests.Session, "get", side_effect=[first, second]) as mocked_get,
        ):
            response = safe_http_get(
                "https://example.com",
                timeout_seconds=2,
                retry_policy=retry_policy,
                breaker=breaker,
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mocked_get.call_count, 2)

    def test_circuit_breaker_blocks_after_consecutive_failures(self) -> None:
        retry_policy = RetryPolicy(
            max_attempts=1,
            base_delay_seconds=0.0,
            max_delay_seconds=0.0,
            jitter_ratio=0.0,
        )
        breaker = CircuitBreakerRegistry(
            failure_threshold=1,
            cooldown_seconds=60.0,
            time_fn=lambda: 0.0,
        )
        with (
            patch("src.parsers.url_safety._resolve_host_ips", return_value={ipaddress.ip_address("93.184.216.34")}),
            patch.object(requests.Session, "get", side_effect=requests.ConnectionError("dial failed")) as mocked_get,
        ):
            with self.assertRaises(HttpFetchError):
                safe_http_get(
                    "https://example.com",
                    timeout_seconds=2,
                    retry_policy=retry_policy,
                    breaker=breaker,
                )

            with self.assertRaises(HttpFetchError) as ctx:
                safe_http_get(
                    "https://example.com",
                    timeout_seconds=2,
                    retry_policy=retry_policy,
                    breaker=breaker,
                )
        self.assertIn("Circuit is open", str(ctx.exception))
        self.assertEqual(mocked_get.call_count, 1)


if __name__ == "__main__":
    unittest.main()
