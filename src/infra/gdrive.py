"""Google Drive client and background mirror helpers."""

from __future__ import annotations

import asyncio
import json
import mimetypes
import sqlite3
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import parse_qsl, urlparse

import requests

from src.config import AppConfig
from src.infra.logging import get_logger
from src.infra.telemetry import track_event
from src.parsers.url_safety import safe_http_get

LOGGER = get_logger(__name__)
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"
_DRIVE_UPLOAD_BASE = "https://www.googleapis.com/upload/drive/v3"
_FOLDER_MIME = "application/vnd.google-apps.folder"
_UPLOAD_LIMIT_BYTES = 64 * 1024 * 1024
_MANIFEST_NAME = "gdrive_vault_manifest.json"


@dataclass(frozen=True)
class DriveFile:
    file_id: str
    name: str
    web_view_link: str
    web_content_link: str
    md5_checksum: str = ""


class GoogleDriveClient:
    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        root_folder_id: str,
        share_public_links: bool = False,
        session: requests.Session | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._root_folder_id = root_folder_id
        self._share_public_links = share_public_links
        self._session = session or requests.Session()
        self._access_token = ""
        self._access_token_expiry = 0.0
        self._folder_cache: dict[tuple[str, ...], str] = {}

    def upload_bytes(
        self,
        *,
        content: bytes,
        name: str,
        mime_type: str,
        folder_path: tuple[str, ...],
        app_properties: dict[str, str] | None = None,
        existing_key: tuple[str, str] | None = None,
    ) -> DriveFile:
        folder_id = self.ensure_folder_path(folder_path)
        existing = None
        if existing_key is not None:
            existing = self._find_file_by_app_property(
                folder_id=folder_id,
                key=existing_key[0],
                value=existing_key[1],
            )

        metadata = {
            "name": name,
            "parents": [folder_id],
            "appProperties": app_properties or {},
        }

        if existing is None:
            file_id = self._create_empty_file(metadata)
        else:
            file_id = str(existing["id"])
            self._patch_metadata(
                file_id=file_id,
                metadata={"name": name, "appProperties": metadata["appProperties"]},
            )

        result = self._upload_media(file_id=file_id, content=content, mime_type=mime_type)
        if self._share_public_links:
            self._ensure_public_permission(file_id)
            result = self._get_file(file_id)
        return result

    def upload_text(
        self,
        *,
        text: str,
        name: str,
        folder_path: tuple[str, ...],
        app_properties: dict[str, str] | None = None,
        existing_key: tuple[str, str] | None = None,
    ) -> DriveFile:
        return self.upload_bytes(
            content=text.encode("utf-8"),
            name=name,
            mime_type="text/markdown",
            folder_path=folder_path,
            app_properties=app_properties,
            existing_key=existing_key,
        )

    def upload_file(
        self,
        *,
        file_path: Path,
        folder_path: tuple[str, ...],
        app_properties: dict[str, str] | None = None,
        existing_key: tuple[str, str] | None = None,
    ) -> DriveFile:
        mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        return self.upload_bytes(
            content=file_path.read_bytes(),
            name=file_path.name,
            mime_type=mime_type,
            folder_path=folder_path,
            app_properties=app_properties,
            existing_key=existing_key,
        )

    def ensure_folder_path(self, folder_path: tuple[str, ...]) -> str:
        if not folder_path:
            return self._root_folder_id
        if folder_path in self._folder_cache:
            return self._folder_cache[folder_path]

        parent_id = self._root_folder_id
        built: list[str] = []
        for part in folder_path:
            built.append(part)
            cache_key = tuple(built)
            cached = self._folder_cache.get(cache_key)
            if cached:
                parent_id = cached
                continue

            existing = self._find_named_folder(parent_id=parent_id, name=part)
            if existing is None:
                folder_id = self._create_empty_file(
                    {
                        "name": part,
                        "mimeType": _FOLDER_MIME,
                        "parents": [parent_id],
                        "appProperties": {},
                    }
                )
            else:
                folder_id = str(existing["id"])
            self._folder_cache[cache_key] = folder_id
            parent_id = folder_id
        return parent_id

    def _refresh_access_token(self) -> None:
        now = time.time()
        if self._access_token and now < self._access_token_expiry:
            return

        response = self._session.post(
            _TOKEN_URL,
            data={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "refresh_token": self._refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        self._access_token = str(payload["access_token"])
        expires_in = int(payload.get("expires_in", 3600))
        self._access_token_expiry = now + max(60, expires_in - 120)

    def _request(
        self,
        method: str,
        url: str,
        *,
        expected_status: int | tuple[int, ...] = (200,),
        retry_on_unauthorized: bool = True,
        **kwargs: Any,
    ) -> requests.Response:
        self._refresh_access_token()
        headers = dict(kwargs.pop("headers", {}))
        headers["Authorization"] = f"Bearer {self._access_token}"
        response = self._session.request(method, url, headers=headers, timeout=60, **kwargs)
        if response.status_code == 401 and retry_on_unauthorized:
            self._access_token = ""
            response.close()
            return self._request(
                method,
                url,
                expected_status=expected_status,
                retry_on_unauthorized=False,
                headers=headers,
                **kwargs,
            )
        statuses = expected_status if isinstance(expected_status, tuple) else (expected_status,)
        if response.status_code not in statuses:
            response.raise_for_status()
        return response

    def _find_named_folder(self, *, parent_id: str, name: str) -> dict[str, Any] | None:
        query = (
            f"name = '{_escape_drive_query(name)}' and "
            f"mimeType = '{_FOLDER_MIME}' and "
            f"'{_escape_drive_query(parent_id)}' in parents and trashed = false"
        )
        response = self._request(
            "GET",
            f"{_DRIVE_API_BASE}/files",
            params={"q": query, "fields": "files(id,name)", "pageSize": 1},
        )
        files = response.json().get("files", [])
        return files[0] if files else None

    def _find_file_by_app_property(self, *, folder_id: str, key: str, value: str) -> dict[str, Any] | None:
        query = (
            f"'{_escape_drive_query(folder_id)}' in parents and "
            "trashed = false and "
            f"appProperties has {{ key='{_escape_drive_query(key)}' and value='{_escape_drive_query(value)}' }}"
        )
        response = self._request(
            "GET",
            f"{_DRIVE_API_BASE}/files",
            params={"q": query, "fields": "files(id,name,webViewLink,webContentLink,md5Checksum)", "pageSize": 1},
        )
        files = response.json().get("files", [])
        return files[0] if files else None

    def _create_empty_file(self, metadata: dict[str, Any]) -> str:
        response = self._request(
            "POST",
            f"{_DRIVE_API_BASE}/files",
            expected_status=(200, 201),
            json=metadata,
            params={"fields": "id"},
            headers={"Content-Type": "application/json"},
        )
        payload = response.json()
        return str(payload["id"])

    def _patch_metadata(self, *, file_id: str, metadata: dict[str, Any]) -> None:
        self._request(
            "PATCH",
            f"{_DRIVE_API_BASE}/files/{file_id}",
            expected_status=200,
            json=metadata,
            params={"fields": "id"},
            headers={"Content-Type": "application/json"},
        ).close()

    def _upload_media(self, *, file_id: str, content: bytes, mime_type: str) -> DriveFile:
        response = self._request(
            "PATCH",
            f"{_DRIVE_UPLOAD_BASE}/files/{file_id}",
            expected_status=200,
            params={
                "uploadType": "media",
                "fields": "id,name,webViewLink,webContentLink,md5Checksum",
            },
            data=content,
            headers={"Content-Type": mime_type},
        )
        payload = response.json()
        return _drive_file_from_payload(payload)

    def _get_file(self, file_id: str) -> DriveFile:
        response = self._request(
            "GET",
            f"{_DRIVE_API_BASE}/files/{file_id}",
            params={"fields": "id,name,webViewLink,webContentLink,md5Checksum"},
        )
        return _drive_file_from_payload(response.json())

    def _ensure_public_permission(self, file_id: str) -> None:
        self._request(
            "POST",
            f"{_DRIVE_API_BASE}/files/{file_id}/permissions",
            expected_status=(200, 201),
            json={"role": "reader", "type": "anyone"},
            headers={"Content-Type": "application/json"},
        ).close()


def build_gdrive_client(config: AppConfig) -> GoogleDriveClient | None:
    if not config.gdrive_enabled:
        return None
    required = {
        "GDRIVE_CLIENT_ID": config.gdrive_client_id,
        "GDRIVE_CLIENT_SECRET": config.gdrive_client_secret,
        "GDRIVE_REFRESH_TOKEN": config.gdrive_refresh_token,
        "GDRIVE_ROOT_FOLDER_ID": config.gdrive_root_folder_id,
    }
    missing = [name for name, value in required.items() if not value.strip()]
    if missing:
        raise RuntimeError(f"Google Drive integration is enabled but missing: {', '.join(missing)}")
    return GoogleDriveClient(
        client_id=config.gdrive_client_id,
        client_secret=config.gdrive_client_secret,
        refresh_token=config.gdrive_refresh_token,
        root_folder_id=config.gdrive_root_folder_id,
        share_public_links=config.gdrive_share_public_links,
    )


def enrich_payload_with_drive_attachments(
    payload: dict[str, Any],
    drive: GoogleDriveClient | None,
) -> dict[str, Any]:
    merged = dict(payload)
    if drive is None:
        return _sanitize_payload_links(merged, replacements={})

    tenant_id = str(merged.get("tenant_id") or "legacy")
    source = merged.get("source") or {}
    chat_id = int(source.get("chat_id") or 0)
    message_id = int(source.get("message_id") or 0)
    cloud_attachments: list[dict[str, str]] = []
    replacements: dict[str, str] = {}

    parsed_items = [dict(item) for item in merged.get("parsed_items", [])]
    for item in parsed_items:
        source_url = str(item.get("source_url") or "").strip()
        if not _is_telegram_file_url(source_url):
            continue

        attachment = _upload_attachment_from_url(
            drive=drive,
            source_url=source_url,
            tenant_id=tenant_id,
            chat_id=chat_id,
            message_id=message_id,
        )
        cloud_attachments.append(attachment)
        replacements[source_url] = attachment["web_view_link"]
        item["cloud_attachment"] = attachment
        item["source_url"] = redact_telegram_file_url(source_url)
        item["links"] = _merge_unique_links(
            [attachment["web_view_link"]]
            + [redact_telegram_file_url(str(link)) for link in item.get("links", [])]
        )

    merged["parsed_items"] = parsed_items
    if cloud_attachments:
        merged["cloud_attachments"] = cloud_attachments
    return _sanitize_payload_links(merged, replacements=replacements)


def mirror_note_to_drive(
    config: AppConfig,
    drive: GoogleDriveClient | None,
    note_path: Path,
) -> dict[str, str] | None:
    if drive is None:
        return None
    note_path = note_path.resolve()
    vault_root = config.vault_path.resolve()
    relative_path = note_path.relative_to(vault_root).as_posix()
    folder_parts = ("vault_mirror",) + tuple(PurePosixPath(relative_path).parts[:-1])
    drive_file = drive.upload_file(
        file_path=note_path,
        folder_path=folder_parts,
        app_properties={"kind": "vault_note", "local_path": relative_path},
        existing_key=("local_path", relative_path),
    )
    _update_manifest(
        config.state_dir / _MANIFEST_NAME,
        relative_path=relative_path,
        signature=_path_signature(note_path),
        drive_file=drive_file,
    )
    return {"file_id": drive_file.file_id, "web_view_link": drive_file.web_view_link}


def mirror_vault_once(config: AppConfig, drive: GoogleDriveClient | None) -> dict[str, int]:
    if drive is None:
        return {"uploaded": 0, "skipped": 0}

    manifest_path = config.state_dir / _MANIFEST_NAME
    manifest = _load_manifest(manifest_path)
    uploaded = 0
    skipped = 0
    vault_root = config.vault_path.resolve()

    for note_path in vault_root.rglob("*.md"):
        if not note_path.is_file():
            continue
        relative_path = note_path.resolve().relative_to(vault_root).as_posix()
        signature = _path_signature(note_path)
        manifest_row = manifest.get(relative_path, {})
        if manifest_row.get("signature") == signature:
            skipped += 1
            continue
        result = mirror_note_to_drive(config, drive, note_path)
        if result is not None:
            uploaded += 1
            manifest[relative_path] = {
                "signature": signature,
                "file_id": result["file_id"],
                "web_view_link": result["web_view_link"],
                "synced_at": datetime.now(UTC).isoformat(),
            }

    _write_manifest(manifest_path, manifest)
    track_event("gdrive_vault_mirror", uploaded=uploaded, skipped=skipped)
    return {"uploaded": uploaded, "skipped": skipped}


def snapshot_state_db_once(config: AppConfig, drive: GoogleDriveClient | None) -> dict[str, str] | None:
    if drive is None:
        return None

    stamp = datetime.now(UTC)
    snapshot_day = stamp.strftime("%Y%m%d")
    config.cache_dir.mkdir(parents=True, exist_ok=True)
    temp_path = Path(
        tempfile.NamedTemporaryFile(
            delete=False,
            suffix=".sqlite3",
            dir=str(config.cache_dir),
            prefix="gdrive-state-",
        ).name
    )
    try:
        _sqlite_backup(config.state_db_path, temp_path)
        drive_file = drive.upload_file(
            file_path=temp_path,
            folder_path=("db_snapshots", stamp.strftime("%Y"), stamp.strftime("%m")),
            app_properties={"kind": "db_snapshot", "snapshot_day": snapshot_day},
            existing_key=("snapshot_day", snapshot_day),
        )
        track_event("gdrive_db_snapshot", snapshot_day=snapshot_day, file_id=drive_file.file_id)
        return {"file_id": drive_file.file_id, "web_view_link": drive_file.web_view_link}
    finally:
        temp_path.unlink(missing_ok=True)


async def run_gdrive_maintenance_forever(config: AppConfig, drive: GoogleDriveClient | None) -> None:
    if drive is None:
        return

    vault_interval = max(60, int(config.gdrive_vault_mirror_interval_seconds))
    snapshot_interval = max(3600, int(config.gdrive_db_snapshot_interval_seconds))
    next_vault_at = 0.0
    next_snapshot_at = 0.0

    while True:
        now = time.monotonic()
        if now >= next_vault_at:
            try:
                await asyncio.to_thread(mirror_vault_once, config, drive)
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("Google Drive vault mirror failed: %s", exc)
            next_vault_at = now + vault_interval

        if now >= next_snapshot_at:
            try:
                await asyncio.to_thread(snapshot_state_db_once, config, drive)
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("Google Drive state snapshot failed: %s", exc)
            next_snapshot_at = now + snapshot_interval

        await asyncio.sleep(min(60.0, float(vault_interval), float(snapshot_interval)))


def redact_telegram_file_url(url: str) -> str:
    if not _is_telegram_file_url(url):
        return url
    parsed = urlparse(url)
    file_name = Path(parsed.path).name or "telegram-media"
    mime_hint = ""
    for key, value in parse_qsl(parsed.fragment, keep_blank_values=True):
        if key.strip().lower() == "tgmime" and value.strip():
            mime_hint = value.strip()
            break
    if mime_hint:
        return f"telegram://redacted/{file_name}#{mime_hint}"
    return f"telegram://redacted/{file_name}"


def _sanitize_payload_links(payload: dict[str, Any], *, replacements: dict[str, str]) -> dict[str, Any]:
    merged = dict(payload)
    for field in ("content", "enriched_text", "translation"):
        value = str(merged.get(field) or "")
        if not value:
            continue
        for source_url, target_url in replacements.items():
            value = value.replace(source_url, target_url)
        merged[field] = _redact_all_telegram_urls(value)
    return merged


def _redact_all_telegram_urls(text: str) -> str:
    for token in [part for part in text.split() if "api.telegram.org/file/bot" in part]:
        cleaned = token.rstrip(".,;:!?)]}")
        text = text.replace(cleaned, redact_telegram_file_url(cleaned))
    return text


def _upload_attachment_from_url(
    *,
    drive: GoogleDriveClient,
    source_url: str,
    tenant_id: str,
    chat_id: int,
    message_id: int,
) -> dict[str, str]:
    response = safe_http_get(
        source_url,
        timeout_seconds=60,
        max_body_bytes=_UPLOAD_LIMIT_BYTES,
    )
    try:
        content = bytes(response.content)
        mime_type = _guess_mime_type(source_url, response.headers.get("Content-Type", ""))
        file_name = _guess_file_name(source_url, mime_type)
        stable_key = f"{tenant_id}:{chat_id}:{message_id}:{file_name}"
        drive_file = drive.upload_bytes(
            content=content,
            name=file_name,
            mime_type=mime_type,
            folder_path=("telegram_media", tenant_id),
            app_properties={
                "kind": "telegram_media",
                "tenant_id": tenant_id,
                "chat_id": str(chat_id),
                "message_id": str(message_id),
                "file_name": file_name,
            },
            existing_key=("telegram_media_key", stable_key),
        )
        track_event("gdrive_attachment_uploaded", tenant_id=tenant_id, file_id=drive_file.file_id)
        return {
            "name": drive_file.name,
            "file_id": drive_file.file_id,
            "web_view_link": drive_file.web_view_link,
            "web_content_link": drive_file.web_content_link,
            "mime_type": mime_type,
            "source": "telegram",
        }
    finally:
        response.close()


def _sqlite_backup(source_db: Path, dest_db: Path) -> None:
    src = sqlite3.connect(str(source_db))
    try:
        dst = sqlite3.connect(str(dest_db))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def _load_manifest(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        LOGGER.warning("Failed to read Google Drive manifest: %s", path)
        return {}
    return raw if isinstance(raw, dict) else {}


def _write_manifest(path: Path, manifest: dict[str, dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")


def _update_manifest(path: Path, *, relative_path: str, signature: str, drive_file: DriveFile) -> None:
    manifest = _load_manifest(path)
    manifest[relative_path] = {
        "signature": signature,
        "file_id": drive_file.file_id,
        "web_view_link": drive_file.web_view_link,
        "synced_at": datetime.now(UTC).isoformat(),
    }
    _write_manifest(path, manifest)


def _path_signature(path: Path) -> str:
    stat = path.stat()
    return f"{stat.st_mtime_ns}:{stat.st_size}"


def _drive_file_from_payload(payload: dict[str, Any]) -> DriveFile:
    file_id = str(payload["id"])
    return DriveFile(
        file_id=file_id,
        name=str(payload.get("name") or file_id),
        web_view_link=str(payload.get("webViewLink") or f"https://drive.google.com/file/d/{file_id}/view"),
        web_content_link=str(payload.get("webContentLink") or f"https://drive.google.com/uc?id={file_id}"),
        md5_checksum=str(payload.get("md5Checksum") or ""),
    )


def _guess_file_name(source_url: str, mime_type: str) -> str:
    parsed = urlparse(source_url)
    candidate = Path(parsed.path).name
    if candidate:
        return candidate
    extension = mimetypes.guess_extension(mime_type) or ".bin"
    return f"telegram-media{extension}"


def _guess_mime_type(source_url: str, content_type: str) -> str:
    header_value = content_type.split(";")[0].strip().lower()
    if header_value:
        return header_value
    parsed = urlparse(source_url)
    for key, value in parse_qsl(parsed.fragment, keep_blank_values=True):
        if key.strip().lower() == "tgmime" and value.strip():
            return value.strip().lower()
    guessed = mimetypes.guess_type(parsed.path)[0]
    return guessed or "application/octet-stream"


def _escape_drive_query(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _is_telegram_file_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").strip().lower()
    return host == "api.telegram.org" and "/file/bot" in parsed.path


def _merge_unique_links(links: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for link in links:
        value = str(link).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique
