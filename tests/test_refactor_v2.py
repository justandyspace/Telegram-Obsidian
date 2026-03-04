"""Tests for refactoring round 2 changes."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from src.parsers.url_safety import UnsafeUrlError, validate_public_http_url
from src.pipeline.normalize import extract_hashtags, strip_hashtags
from src.rag.embedder import EmbedderError, HashEmbedder, ResilientEmbedder


class UrlSafetyTests(unittest.TestCase):
    """Test SSRF protection in url_safety module."""

    def test_blocks_localhost(self) -> None:
        with self.assertRaises(UnsafeUrlError):
            validate_public_http_url("http://localhost/secret")

    def test_blocks_private_ip(self) -> None:
        with self.assertRaises(UnsafeUrlError):
            validate_public_http_url("http://192.168.1.1/admin")

    def test_blocks_loopback(self) -> None:
        with self.assertRaises(UnsafeUrlError):
            validate_public_http_url("http://127.0.0.1/admin")

    def test_blocks_local_domain(self) -> None:
        with self.assertRaises(UnsafeUrlError):
            validate_public_http_url("http://myhost.local/secret")

    def test_blocks_non_http_scheme(self) -> None:
        with self.assertRaises(UnsafeUrlError):
            validate_public_http_url("ftp://evil.com/data")

    def test_accepts_public_url(self) -> None:
        # Should not raise
        validate_public_http_url("https://www.google.com")


class CyrillicHashtagTests(unittest.TestCase):
    """Test Cyrillic hashtag support (F19 fix)."""

    def test_extract_cyrillic_hashtags(self) -> None:
        text = "Отличная статья #заметка #save"
        tags = extract_hashtags(text)
        self.assertIn("заметка", tags)
        self.assertIn("save", tags)

    def test_extract_mixed_unicode_hashtags(self) -> None:
        text = "#задача перевести #translate"
        tags = extract_hashtags(text)
        self.assertIn("задача", tags)
        self.assertIn("translate", tags)

    def test_strip_cyrillic_hashtags(self) -> None:
        text = "Привет #заметка мир"
        result = strip_hashtags(text)
        self.assertNotIn("#заметка", result)
        self.assertIn("Привет", result)
        self.assertIn("мир", result)


class ResilientEmbedderRecoveryTests(unittest.TestCase):
    """Test that ResilientEmbedder recovers after cooldown (F05 fix)."""

    def test_recovers_after_cooldown(self) -> None:
        primary = MagicMock()
        fallback = HashEmbedder(dim=4)

        # Simulate time progression
        fake_time = [0.0]

        def time_fn():
            return fake_time[0]

        embedder = ResilientEmbedder(
            primary=primary,
            fallback=fallback,
            cooldown_seconds=10.0,
            time_fn=time_fn,
        )

        # First call: primary fails -> fallback
        primary.embed_query.side_effect = EmbedderError("API down")
        result1 = embedder.embed_query("hello")
        self.assertTrue(embedder.fallback_active)
        self.assertEqual(len(result1), 4)

        # Second call within cooldown: still uses fallback
        fake_time[0] = 5.0
        primary.embed_query.side_effect = None
        primary.embed_query.return_value = [1.0, 0.0, 0.0, 0.0]
        embedder.embed_query("hello")
        self.assertTrue(embedder.fallback_active)

        # Third call after cooldown: retries primary, succeeds
        fake_time[0] = 15.0
        result3 = embedder.embed_query("hello")
        self.assertFalse(embedder.fallback_active)
        self.assertEqual(result3, [1.0, 0.0, 0.0, 0.0])

    def test_permanent_failure_stays_on_fallback(self) -> None:
        primary = MagicMock()
        fallback = HashEmbedder(dim=4)

        fake_time = [0.0]
        embedder = ResilientEmbedder(
            primary=primary,
            fallback=fallback,
            cooldown_seconds=10.0,
            time_fn=lambda: fake_time[0],
        )

        primary.embed_query.side_effect = EmbedderError("API permanently down")

        # Fail initially
        embedder.embed_query("hello")
        self.assertTrue(embedder.fallback_active)

        # After cooldown, still fails -> stays on fallback
        fake_time[0] = 15.0
        embedder.embed_query("hello")
        self.assertTrue(embedder.fallback_active)


class CrossTenantIsolationTests(unittest.TestCase):
    """Test that /find and /summary don't leak across tenants."""

    def test_no_fallback_to_base_vault_in_find(self) -> None:
        """Verify find_handler doesn't search base vault when tenant vault is empty."""
        # This is a structural test: check that commands.py does NOT
        # call find_notes with vault_path (the base path)
        import inspect

        from src.bot.commands import build_command_router

        source = inspect.getsource(build_command_router)
        # find_notes should only be called with rag.vault_path, not vault_path directly
        find_calls = [
            line.strip()
            for line in source.splitlines()
            if "find_notes(" in line and "rag.vault_path" not in line and "def " not in line
        ]
        # Filter out function definition lines
        find_calls = [c for c in find_calls if "vault_path" in c and "rag." not in c]
        self.assertEqual(
            find_calls,
            [],
            f"Found cross-tenant fallback in /find: {find_calls}",
        )

    def test_no_fallback_to_base_vault_in_summary(self) -> None:
        """Verify summary_handler doesn't search base vault when tenant vault is empty."""
        import inspect

        from src.bot.commands import build_command_router

        source = inspect.getsource(build_command_router)
        latest_calls = [
            line.strip()
            for line in source.splitlines()
            if "latest_notes(" in line and "rag.vault_path" not in line and "def " not in line
        ]
        latest_calls = [c for c in latest_calls if "vault_path" in c and "rag." not in c]
        self.assertEqual(
            latest_calls,
            [],
            f"Found cross-tenant fallback in /summary: {latest_calls}",
        )


if __name__ == "__main__":
    unittest.main()
