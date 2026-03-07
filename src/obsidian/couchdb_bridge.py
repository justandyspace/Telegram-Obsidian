"""CouchDB bridge for pushing rendered notes into LiveSync-compatible docs."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from urllib.parse import quote

import requests

LOGGER = logging.getLogger(__name__)


class CouchDBBridge:
    """Pushes note and chunk documents to CouchDB."""

    def __init__(self, url: str, user: str, password: str, db_name: str) -> None:
        self.url, self.db_name = url.rstrip("/"), db_name
        self.session = requests.Session()
        self.session.auth = (user, password)

    def push_note(self, file_name: str, content: str) -> bool:
        note_id = file_name
        now_ms = int(time.time() * 1000)
        chunk_id = "h:" + hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]

        chunk_doc = {"_id": chunk_id, "type": "leaf", "data": content}
        note_doc = {
            "_id": note_id,
            "type": "plain",
            "children": [chunk_id],
            "path": file_name,
            "ctime": now_ms,
            "mtime": now_ms,
            "size": len(content.encode("utf-8")),
            "eden": {},
        }
        try:
            chunk_url = f"{self.url}/{self.db_name}/{quote(chunk_id, safe='')}"
            note_url = f"{self.url}/{self.db_name}/{quote(note_id, safe='')}"

            r = self.session.get(chunk_url)
            if r.status_code == 200:
                chunk_doc["_rev"] = r.json()["_rev"]
            res_chunk = self.session.put(
                chunk_url,
                data=json.dumps(chunk_doc),
                headers={"Content-Type": "application/json"},
            )
            if res_chunk.status_code not in (201, 202):
                return False

            r = self.session.get(note_url)
            if r.status_code == 200:
                note_doc["_rev"] = r.json()["_rev"]
            res_note = self.session.put(
                note_url,
                data=json.dumps(note_doc),
                headers={"Content-Type": "application/json"},
            )
            return res_note.status_code in (201, 202)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("CouchDB push error for %s: %s", file_name, exc)
            return False
