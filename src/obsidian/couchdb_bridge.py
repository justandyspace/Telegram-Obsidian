import json, time, logging, requests, hashlib
from urllib.parse import quote

LOGGER = logging.getLogger(__name__)


class CouchDBBridge:
    def __init__(self, url, user, password, db_name):
        self.url, self.db_name = url.rstrip("/"), db_name
        self.session = requests.Session()
        self.session.auth = (user, password)

    def push_note(self, file_name, content):
        note_id = file_name
        now_ms = int(time.time() * 1000)
        chunk_id = "h:" + hashlib.sha1(content.encode("utf-8")).hexdigest()[:12]

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
        except Exception as e:
            LOGGER.error(f"CouchDB push error: {e}")
            return False
