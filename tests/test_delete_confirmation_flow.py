from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.infra.storage import StateStore


class DeleteAllConfirmationStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "state.sqlite3"
        self.store = StateStore(self.db_path)
        self.store.initialize()

    def tearDown(self) -> None:
        self.store.close()
        self._tmp.cleanup()

    def test_confirmation_is_scoped_by_tenant_and_user(self) -> None:
        first = self.store.create_delete_all_confirmation(
            tenant_id="tg_111",
            user_id=111,
            chat_id=10,
            ttl_seconds=120,
        )
        second = self.store.create_delete_all_confirmation(
            tenant_id="tg_222",
            user_id=111,
            chat_id=20,
            ttl_seconds=120,
        )

        wrong_tenant_ok, wrong_tenant_reason = self.store.consume_delete_all_confirmation(
            tenant_id="tg_999",
            user_id=111,
            token=str(first["token"]),
        )
        self.assertFalse(wrong_tenant_ok)
        self.assertEqual(wrong_tenant_reason, "not_found")

        tenant_two_pending = self.store.get_delete_all_confirmation(tenant_id="tg_222", user_id=111)
        self.assertIsNotNone(tenant_two_pending)
        self.assertEqual(tenant_two_pending["token"], second["token"])

        ok, reason = self.store.consume_delete_all_confirmation(
            tenant_id="tg_111",
            user_id=111,
            token=str(first["token"]),
        )
        self.assertTrue(ok)
        self.assertEqual(reason, "confirmed")
        self.assertIsNone(self.store.get_delete_all_confirmation(tenant_id="tg_111", user_id=111))
        self.assertIsNotNone(self.store.get_delete_all_confirmation(tenant_id="tg_222", user_id=111))

    def test_token_mismatch_does_not_consume_pending_state(self) -> None:
        created = self.store.create_delete_all_confirmation(
            tenant_id="tg_333",
            user_id=333,
            chat_id=30,
            ttl_seconds=120,
        )

        wrong_ok, wrong_reason = self.store.consume_delete_all_confirmation(
            tenant_id="tg_333",
            user_id=333,
            token="WRONGTOK",
        )
        self.assertFalse(wrong_ok)
        self.assertEqual(wrong_reason, "token_mismatch")

        still_pending = self.store.get_delete_all_confirmation(tenant_id="tg_333", user_id=333)
        self.assertIsNotNone(still_pending)
        self.assertEqual(still_pending["token"], created["token"])

        ok, reason = self.store.consume_delete_all_confirmation(
            tenant_id="tg_333",
            user_id=333,
            token=str(created["token"]),
        )
        self.assertTrue(ok)
        self.assertEqual(reason, "confirmed")

    def test_expired_confirmation_is_rejected_and_removed(self) -> None:
        created = self.store.create_delete_all_confirmation(
            tenant_id="tg_444",
            user_id=444,
            chat_id=40,
            ttl_seconds=120,
        )
        expired_at = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
        conn = sqlite3.connect(str(self.db_path))
        conn.execute(
            """
            UPDATE delete_all_confirmations_mt
            SET expires_at = ?
            WHERE tenant_id = ? AND user_id = ?
            """,
            (expired_at, "tg_444", 444),
        )
        conn.commit()
        conn.close()

        ok, reason = self.store.consume_delete_all_confirmation(
            tenant_id="tg_444",
            user_id=444,
            token=str(created["token"]),
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "expired")
        self.assertIsNone(self.store.get_delete_all_confirmation(tenant_id="tg_444", user_id=444))

    def test_cancel_removes_pending_confirmation(self) -> None:
        self.store.create_delete_all_confirmation(
            tenant_id="tg_555",
            user_id=555,
            chat_id=50,
            ttl_seconds=120,
        )
        canceled = self.store.cancel_delete_all_confirmation(tenant_id="tg_555", user_id=555)
        self.assertTrue(canceled)
        self.assertIsNone(self.store.get_delete_all_confirmation(tenant_id="tg_555", user_id=555))
        self.assertFalse(self.store.cancel_delete_all_confirmation(tenant_id="tg_555", user_id=555))


if __name__ == "__main__":
    unittest.main()
