"""Vault watcher daemon for RAG index maintenance."""

from __future__ import annotations

import asyncio
from pathlib import Path

from src.config import AppConfig
from src.infra.logging import get_logger
from src.rag.retriever import RagManager

LOGGER = get_logger(__name__)


class NoteEventProcessor:
    def __init__(self, *, base_vault_path: Path, rag_manager: RagManager, multi_tenant: bool) -> None:
        self._base_vault_path = base_vault_path.resolve()
        self._rag_manager = rag_manager
        self._multi_tenant = multi_tenant

    def handle_upsert(self, raw_path: Path) -> bool:
        resolved = self._resolve_markdown_path(raw_path)
        if resolved is None:
            return False
        tenant_id, note_path = resolved
        if not note_path.exists():
            return False
        changed = self._rag_manager.for_tenant(tenant_id).index_note(note_path)
        if changed:
            LOGGER.info("Indexed note tenant=%s path=%s", tenant_id, note_path)
        return changed

    def handle_delete(self, raw_path: Path) -> bool:
        resolved = self._resolve_markdown_path(raw_path)
        if resolved is None:
            return False
        tenant_id, note_path = resolved
        deleted = self._rag_manager.for_tenant(tenant_id).remove_note(note_path)
        if deleted:
            LOGGER.info("Removed note from index tenant=%s path=%s", tenant_id, note_path)
        return deleted

    def _resolve_markdown_path(self, raw_path: Path) -> tuple[str, Path] | None:
        try:
            resolved = raw_path.resolve()
        except OSError:
            return None
        if resolved.suffix.lower() != ".md":
            return None
        try:
            relative = resolved.relative_to(self._base_vault_path)
        except ValueError:
            return None
        if self._multi_tenant:
            if len(relative.parts) < 2:
                return None
            tenant_id = relative.parts[0]
        else:
            tenant_id = "single"
        return tenant_id, resolved


def _scan_markdown_files(base_vault_path: Path) -> dict[Path, float]:
    snapshots: dict[Path, float] = {}
    for note in base_vault_path.rglob("*.md"):
        try:
            snapshots[note.resolve()] = note.stat().st_mtime
        except OSError:
            continue
    return snapshots


async def _run_polling_loop(config: AppConfig, processor: NoteEventProcessor) -> None:
    LOGGER.info("Watcher running in polling mode interval=%s sec", config.watcher_poll_seconds)
    known = _scan_markdown_files(config.vault_path)
    while True:
        await asyncio.sleep(config.watcher_poll_seconds)
        current = _scan_markdown_files(config.vault_path)

        for deleted_path in known.keys() - current.keys():
            processor.handle_delete(deleted_path)

        for path, mtime in current.items():
            if path not in known or mtime > known[path]:
                processor.handle_upsert(path)

        known = current


async def _run_watchdog_loop(config: AppConfig, processor: NoteEventProcessor) -> None:
    from watchdog.events import FileSystemEvent, FileSystemEventHandler
    from watchdog.observers import Observer

    class _VaultEventHandler(FileSystemEventHandler):
        def on_created(self, event: FileSystemEvent) -> None:
            if not event.is_directory:
                processor.handle_upsert(Path(event.src_path))

        def on_modified(self, event: FileSystemEvent) -> None:
            if not event.is_directory:
                processor.handle_upsert(Path(event.src_path))

        def on_deleted(self, event: FileSystemEvent) -> None:
            if not event.is_directory:
                processor.handle_delete(Path(event.src_path))

        def on_moved(self, event: FileSystemEvent) -> None:
            if event.is_directory:
                return
            processor.handle_delete(Path(event.src_path))
            dest_path = getattr(event, "dest_path", "")
            if dest_path:
                processor.handle_upsert(Path(dest_path))

    observer = Observer()
    handler = _VaultEventHandler()
    observer.schedule(handler, str(config.vault_path), recursive=True)
    observer.start()
    LOGGER.info("Watcher running in watchdog mode path=%s", config.vault_path)
    try:
        while True:
            await asyncio.sleep(1)
    finally:
        observer.stop()
        observer.join(timeout=5)


async def run_watcher(config: AppConfig, rag_manager: RagManager) -> None:
    processor = NoteEventProcessor(
        base_vault_path=config.vault_path,
        rag_manager=rag_manager,
        multi_tenant=config.multi_tenant_mode,
    )
    try:
        await _run_watchdog_loop(config, processor)
    except ImportError:
        LOGGER.warning("watchdog package is unavailable; switching to polling fallback")
        await _run_polling_loop(config, processor)
    except Exception as exc:  # noqa: BLE001
        LOGGER.exception("watchdog loop failed (%s); switching to polling fallback", exc)
        await _run_polling_loop(config, processor)
