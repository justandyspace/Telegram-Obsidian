from __future__ import annotations

import unittest

from src.parsers.router import classify_url, parse_url
from src.parsers.url_safety import UnsafeUrlError, validate_public_http_url


class ParserSecurityTests(unittest.TestCase):
    def test_validate_public_http_url_blocks_localhost_and_private_ips(self) -> None:
        with self.assertRaises(UnsafeUrlError):
            validate_public_http_url("http://127.0.0.1:8080/private")
        with self.assertRaises(UnsafeUrlError):
            validate_public_http_url("http://localhost/admin")
        with self.assertRaises(UnsafeUrlError):
            validate_public_http_url("ftp://example.com/file")

    def test_validate_public_http_url_allows_public_ip_literal(self) -> None:
        validate_public_http_url("https://8.8.8.8")

    def test_parse_url_returns_error_for_blocked_ssrf_target(self) -> None:
        result = parse_url("http://127.0.0.1/secret")
        self.assertEqual(result.parser, "article")
        self.assertEqual(result.status, "error")
        self.assertIn("blocked", (result.error or "").lower())

    def test_classification_does_not_match_suffix_confusion(self) -> None:
        self.assertEqual(classify_url("https://youtube.com.evil/test"), "article")
        self.assertEqual(classify_url("https://x.com.evil/post/1"), "article")


if __name__ == "__main__":
    unittest.main()
