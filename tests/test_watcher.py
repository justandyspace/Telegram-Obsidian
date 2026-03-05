from __future__ import annotations

from pathlib import Path

from src.watcher import NoteEventProcessor


class _FakeRagService:
    def __init__(self) -> None:
        self.indexed: list[Path] = []
        self.removed: list[Path] = []

    def index_note(self, note_path: Path) -> bool:
        self.indexed.append(note_path.resolve())
        return True

    def remove_note(self, note_path: Path) -> bool:
        self.removed.append(note_path.resolve())
        return True


class _FakeRagManager:
    def __init__(self) -> None:
        self.services: dict[str, _FakeRagService] = {}

    def for_tenant(self, tenant_id: str) -> _FakeRagService:
        if tenant_id not in self.services:
            self.services[tenant_id] = _FakeRagService()
        return self.services[tenant_id]


def test_single_tenant_upsert_and_delete(tmp_path: Path) -> None:
    manager = _FakeRagManager()
    processor = NoteEventProcessor(
        base_vault_path=tmp_path,
        rag_manager=manager,  # type: ignore[arg-type]
        multi_tenant=False,
    )
    note = tmp_path / "a.md"
    note.write_text("# hello", encoding="utf-8")

    assert processor.handle_upsert(note) is True
    assert processor.handle_delete(note) is True

    service = manager.for_tenant("single")
    assert service.indexed == [note.resolve()]
    assert service.removed == [note.resolve()]


def test_ignores_non_markdown_and_outside_vault(tmp_path: Path) -> None:
    manager = _FakeRagManager()
    processor = NoteEventProcessor(
        base_vault_path=tmp_path,
        rag_manager=manager,  # type: ignore[arg-type]
        multi_tenant=False,
    )
    txt = tmp_path / "a.txt"
    txt.write_text("x", encoding="utf-8")
    outside = tmp_path.parent / "outside.md"
    outside.write_text("x", encoding="utf-8")

    assert processor.handle_upsert(txt) is False
    assert processor.handle_upsert(outside) is False
    assert manager.services == {}


def test_multi_tenant_routes_to_tenant_dir(tmp_path: Path) -> None:
    manager = _FakeRagManager()
    processor = NoteEventProcessor(
        base_vault_path=tmp_path,
        rag_manager=manager,  # type: ignore[arg-type]
        multi_tenant=True,
    )
    tenant_note = tmp_path / "tg_123" / "note.md"
    tenant_note.parent.mkdir(parents=True, exist_ok=True)
    tenant_note.write_text("x", encoding="utf-8")
    root_note = tmp_path / "root.md"
    root_note.write_text("x", encoding="utf-8")

    assert processor.handle_upsert(tenant_note) is True
    assert processor.handle_upsert(root_note) is False

    tenant_service = manager.for_tenant("tg_123")
    assert tenant_service.indexed == [tenant_note.resolve()]
