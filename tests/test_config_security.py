from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from src.config import load_config


class ConfigSecurityTests(unittest.TestCase):
    def _base_env(self) -> dict[str, str]:
        return {
            "APP_ROLE": "bot",
            "TELEGRAM_TOKEN": "token",
            "TELEGRAM_ALLOWED_USER_ID": "123",
            "TELEGRAM_MODE": "polling",
            "WEBHOOK_BASE_URL": "",
            "WEBHOOK_SECRET_TOKEN": "",
        }

    def test_webhook_mode_requires_secret(self) -> None:
        env = self._base_env()
        env["TELEGRAM_MODE"] = "webhook"
        env["WEBHOOK_BASE_URL"] = "https://example.com"
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(RuntimeError):
                load_config()

    def test_webhook_mode_requires_strong_secret(self) -> None:
        env = self._base_env()
        env["TELEGRAM_MODE"] = "webhook"
        env["WEBHOOK_BASE_URL"] = "https://example.com"
        env["WEBHOOK_SECRET_TOKEN"] = "short"
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(RuntimeError):
                load_config()

    def test_auto_with_webhook_url_requires_secret(self) -> None:
        env = self._base_env()
        env["TELEGRAM_MODE"] = "auto"
        env["WEBHOOK_BASE_URL"] = "https://example.com"
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(RuntimeError):
                load_config()

    def test_polling_mode_allows_empty_webhook_secret(self) -> None:
        env = self._base_env()
        with patch.dict(os.environ, env, clear=True):
            cfg = load_config()
        self.assertEqual(cfg.telegram_mode, "polling")

    def test_watcher_role_is_valid(self) -> None:
        env = self._base_env()
        env["APP_ROLE"] = "watcher"
        env["TELEGRAM_TOKEN"] = ""
        env["TELEGRAM_ALLOWED_USER_ID"] = ""
        with patch.dict(os.environ, env, clear=True):
            cfg = load_config()
        self.assertEqual(cfg.role, "watcher")


if __name__ == "__main__":
    unittest.main()

