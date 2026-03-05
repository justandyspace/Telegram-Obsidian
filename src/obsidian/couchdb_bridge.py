"""Bridge to sync notes directly to CouchDB for Obsidian LiveSync."""

from __future__ import annotations

import base64
import json
import time
import logging
import requests
from typing import Any

LOGGER = logging.getLogger(__name__)

class CouchDBBridge:
    def __init__(self, url: str, user: str, password: str, db_name: str):
        self.url = url.rstrip('/')
        self.user = user
        self.password = password
        self.db_name = db_name
        self.session = requests.Session()
        self.session.auth = (user, password)

    def ensure_db(self) -> bool:
        """Ensures the target database exists."""
        try:
            resp = self.session.get(f"{self.url}/{self.db_name}")
            if resp.status_code == 200:
                return True
            if resp.status_code == 404:
                resp = self.session.put(f"{self.url}/{self.db_name}")
                return resp.status_code in (201, 202)
            return False
        except Exception as exc:
            LOGGER.error("Failed to connect to CouchDB: %s", exc)
            return False

    def push_note(self, file_name: str, content: str) -> bool:
        """Pushes a markdown note to CouchDB in a format compatible with LiveSync."""
        if not self.ensure_db():
            return False

        # LiveSync uses the filename as the document ID (often plain text or URL encoded)
        doc_id = file_name
        
        # Prepare the document in LiveSync format (non-encrypted)
        # Note: LiveSync stores the content in 'data' field as plain text if not encrypted
        doc = {
            "_id": doc_id,
            "type": "plain",
            "data": content,
            "mtime": int(time.time() * 1000),
            "ctime": int(time.time() * 1000),
            "size": len(content.encode('utf-8')),
            "leaf": True
        }

        try:
            # Check if document exists to get _rev
            resp = self.session.get(f"{self.url}/{self.db_name}/{doc_id}")
            if resp.status_code == 200:
                doc["_rev"] = resp.json()["_rev"]

            resp = self.session.put(
                f"{self.url}/{self.db_name}/{doc_id}",
                data=json.dumps(doc),
                headers={"Content-Type": "application/json"}
            )
            
            if resp.status_code in (201, 202):
                LOGGER.info("Successfully pushed note to CouchDB: %s", file_name)
                return True
            else:
                LOGGER.error("Failed to push to CouchDB: %s %s", resp.status_code, resp.text)
                return False
        except Exception as exc:
            LOGGER.error("CouchDB sync error: %s", exc)
            return False
