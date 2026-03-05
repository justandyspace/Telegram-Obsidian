from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path

import src.bot.commands as commands_module
from src.bot.commands import _status_label
from src.infra.storage import StateStore


class CommandsSmokeTests(unittest.TestCase):
    def test_start_message_uses_assistant_style(self) -> None:
        source = inspect.getsource(commands_module.build_command_router)
        self.assertIn("🤖 <b>Привет. Я готов помогать с твоим Obsidian.</b>", source)
        self.assertIn("🧭 <b>Команды:</b>", source)
        self.assertIn("<code>/delete cancel</code>", source)

    def test_delete_flow_uses_confirmation_methods(self) -> None:
        source = inspect.getsource(commands_module.build_command_router)
        self.assertIn("create_delete_all_confirmation", source)
        self.assertIn("consume_delete_all_confirmation", source)
        self.assertIn("resolve_note_ref", source)

    def test_status_label_mapping(self) -> None:
        self.assertEqual(_status_label("pending"), "В очереди")
        self.assertEqual(_status_label("processing"), "В обработке")
        self.assertEqual(_status_label("retry"), "Повтор")
        self.assertEqual(_status_label("done"), "Готово")
        self.assertEqual(_status_label("failed"), "Ошибка")

    def test_status_contains_monitoring_fields(self) -> None:
        source = inspect.getsource(commands_module.build_command_router)
        self.assertIn("🩺 <b>Мониторинг процесса</b>", source)
        self.assertIn("Аптайм", source)
        self.assertIn("Последняя ошибка", source)


class StorageMethodSurfaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = StateStore(Path(self._tmp.name) / "state.sqlite3")
        self.store.initialize()

    def tearDown(self) -> None:
        self.store.close()
        self._tmp.cleanup()

    def test_storage_exposes_delete_flow_methods(self) -> None:
        required = [
            "create_delete_all_confirmation",
            "consume_delete_all_confirmation",
            "cancel_delete_all_confirmation",
            "resolve_note_ref",
            "delete_note_record",
            "list_notes",
            "delete_all_note_records",
        ]
        for method in required:
            self.assertTrue(hasattr(self.store, method), method)


if __name__ == "__main__":
    unittest.main()
