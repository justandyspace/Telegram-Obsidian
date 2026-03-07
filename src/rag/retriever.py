"""RAG service for indexing and retrieval."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from google import genai

from src.infra.ai_fallback import is_remote_ai_available, mark_remote_ai_failure, reset_remote_ai
from src.infra.logging import get_logger
from src.infra.resilience import RetryPolicy, with_retry
from src.infra.tenancy import tenant_index_dir, tenant_vault_path
from src.rag.chunker import chunk_text
from src.rag.embedder import BaseEmbedder, build_embedder
from src.rag.index_store import IndexStore, RetrievedChunk

LOGGER = get_logger(__name__)
_AI_SCOPE = "grounded_answer"
_MANAGED_BLOCK_RE = re.compile(r"<!--\s*BOT_[A-Z_]+:START\s*-->.*?<!--\s*BOT_[A-Z_]+:END\s*-->", re.DOTALL)
_INLINE_META_RE = re.compile(
    r"\b(note_id|source_chat_id|source_message_id|source_user_id|source_datetime|actions|tags)\s*:\s*[^\n]+",
    re.IGNORECASE,
)
_PROCESSED_RE = re.compile(r"\[\s*Processed in[^\]]*\]", re.IGNORECASE)
_RELATED_NOTES_RE = re.compile(r"#+\s*Related notes \(auto\).*", re.IGNORECASE | re.DOTALL)
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)


@dataclass
class QueryAnswer:
    answer: str
    sources: list[RetrievedChunk]
    mode: str


class RagService:
    def __init__(
        self,
        vault_path: Path,
        index_dir: Path,
        *,
        gemini_api_key: str = "",
        gemini_embed_model: str = "gemini-embedding-001",
        gemini_generation_model: str = "gemini-2.0-flash-lite",
    ) -> None:
        self.vault_path = vault_path
        self._embedder: BaseEmbedder = build_embedder(
            api_key=gemini_api_key,
            model=gemini_embed_model,
        )
        self._index_store = IndexStore(index_dir / "rag_index.sqlite3")
        self._index_store.initialize()
        self._generation_client = genai.Client(api_key=gemini_api_key) if gemini_api_key else None
        self._generation_model = gemini_generation_model or "gemini-2.5-flash"

    @property
    def provider_name(self) -> str:
        return self._embedder.provider_name

    def stats(self) -> dict[str, int | str]:
        base = self._index_store.stats()
        return {
            "documents": base["documents"],
            "chunks": base["chunks"],
            "provider": self.provider_name,
        }

    def index_note(self, note_path: Path) -> bool:
        if not note_path.exists() or note_path.suffix.lower() != ".md":
            return False
        text = note_path.read_text(encoding="utf-8")
        content_hash = _hash_text(text)
        note_path_str = str(note_path.resolve())
        if self._index_store.is_document_current(note_path_str, content_hash):
            return False

        chunks = chunk_text(text)
        if not chunks:
            return False

        embeddings = self._embedder.embed_texts(chunks)
        self._index_store.upsert_document_chunks(
            note_path=note_path_str,
            content_hash=content_hash,
            chunks=chunks,
            embeddings=embeddings,
        )
        LOGGER.info("Indexed note %s chunks=%s", note_path.name, len(chunks))
        return True

    def reindex_vault_incremental(self, limit: int = 25) -> int:
        indexed = 0
        for path in sorted(self.vault_path.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
            changed = self.index_note(path)
            if changed:
                indexed += 1
            if indexed >= limit:
                break
        return indexed

    def remove_note(self, note_path: Path) -> bool:
        return self._index_store.delete_document(str(note_path.resolve()))

    def find(self, query: str, top_k: int = 5) -> list[RetrievedChunk]:
        query = query.strip()
        if not query:
            return []
        # NOTE: reindex is intentionally NOT called here.
        # Indexing is handled by the worker after note creation.
        vector = self._embedder.embed_query(query)
        raw_hits = self._index_store.search(vector, top_k=top_k * 2)
        provider = self.provider_name
        hash_mode = provider == "hash-fallback" or provider.endswith("->hash-fallback")
        min_score = -1.0 if hash_mode else 0.35
        hits: list[RetrievedChunk] = []
        for item in raw_hits:
            if item.score < min_score:
                continue
            note_path = Path(item.note_path)
            if not note_path.exists():
                # Opportunistically prune stale index entries for deleted notes.
                self._index_store.delete_document(item.note_path)
                continue
            hits.append(item)
        return hits[:top_k]

    def answer(self, question: str, top_k: int = 4) -> QueryAnswer:
        hits = self.find(question, top_k=top_k)
        if not hits:
            return QueryAnswer(
                answer="No relevant indexed notes found.",
                sources=[],
                mode="empty",
            )

        if self._generation_client is not None:
            response = self._answer_with_gemini(question, hits)
            if response:
                return QueryAnswer(answer=response, sources=hits, mode="gemini-grounded")

        extractive = _build_extractive_answer(question, hits)
        return QueryAnswer(answer=extractive, sources=hits, mode="extractive")

    def _answer_with_gemini(self, question: str, hits: list[RetrievedChunk]) -> str:
        client = self._generation_client
        if client is None:
            return ""
        if not is_remote_ai_available(_AI_SCOPE):
            return ""
        try:
            context_lines = []
            for idx, hit in enumerate(hits, start=1):
                context_lines.append(f"[{idx}] {hit.file_name}\n{hit.chunk_text}")
            prompt = (
                "Answer the user's question using ONLY the provided context.\n"
                "Write in natural human language, not as raw notes or debug output.\n"
                "Do not paste markdown structure, metadata blocks, or filenames inline unless needed as sources.\n"
                "Be concise and factual. If context is insufficient, say so.\n\n"
                f"Question: {question}\n\n"
                "Context:\n"
                + "\n\n".join(context_lines)
            )

            def _call_gemini() -> Any:
                return client.models.generate_content(
                    model=self._generation_model,
                    contents=prompt,
                )

            policy = RetryPolicy(max_attempts=3, base_delay_seconds=1.5, max_delay_seconds=10.0)
            result = with_retry(policy, _call_gemini, exc_types=(Exception,))
            reset_remote_ai(_AI_SCOPE)

            text = str(cast(Any, result).text or "").strip()
            return text[:2500]
        except Exception as exc:  # noqa: BLE001
            mark_remote_ai_failure(_AI_SCOPE, exc)
            LOGGER.warning("Gemini grounded answer failed: %s", exc)
            return ""

    def close(self) -> None:
        self._index_store.close()


class RagManager:
    def __init__(
        self,
        *,
        base_vault_path: Path,
        base_index_dir: Path,
        multi_tenant: bool,
        gemini_api_key: str,
        gemini_embed_model: str,
        gemini_generation_model: str,
    ) -> None:
        self._base_vault_path = base_vault_path
        self._base_index_dir = base_index_dir
        self._multi_tenant = multi_tenant
        self._gemini_api_key = gemini_api_key
        self._gemini_embed_model = gemini_embed_model
        self._gemini_generation_model = gemini_generation_model
        self._cache: dict[str, RagService] = {}

    def for_tenant(self, tenant_id: str) -> RagService:
        key = tenant_id if self._multi_tenant else "single"
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        vault_path = tenant_vault_path(self._base_vault_path, tenant_id, multi_tenant=self._multi_tenant)
        index_dir = tenant_index_dir(self._base_index_dir, tenant_id, multi_tenant=self._multi_tenant)
        vault_path.mkdir(parents=True, exist_ok=True)
        index_dir.mkdir(parents=True, exist_ok=True)
        service = RagService(
            vault_path=vault_path,
            index_dir=index_dir,
            gemini_api_key=self._gemini_api_key,
            gemini_embed_model=self._gemini_embed_model,
            gemini_generation_model=self._gemini_generation_model,
        )
        self._cache[key] = service
        return service

    def close(self) -> None:
        for service in self._cache.values():
            service.close()
        self._cache.clear()


def _build_extractive_answer(question: str, hits: list[RetrievedChunk]) -> str:
    lines = ["Вот что удалось найти по запросу:", ""]
    for idx, hit in enumerate(hits, start=1):
        snippet = _humanize_chunk_text(hit.chunk_text)
        if not snippet:
            snippet = hit.file_name.rsplit(".", 1)[0]
        if len(snippet) > 220:
            snippet = snippet[:217].rstrip() + "..."
        lines.append(f"{idx}. {snippet}")
    return "\n".join(lines)


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _humanize_chunk_text(text: str) -> str:
    cleaned = str(text or "").replace("\r\n", "\n")
    cleaned = _MANAGED_BLOCK_RE.sub(" ", cleaned)
    cleaned = _RELATED_NOTES_RE.sub(" ", cleaned)
    cleaned = cleaned.replace("## 📝 User Content", " ")
    cleaned = cleaned.replace("User Content", " ")
    cleaned = cleaned.replace("##", " ")
    cleaned = _INLINE_META_RE.sub(" ", cleaned)
    cleaned = _PROCESSED_RE.sub(" ", cleaned)
    cleaned = cleaned.replace("[[", "").replace("]]", "")
    cleaned = _HEADING_RE.sub("", cleaned)
    cleaned = " ".join(cleaned.split())
    cleaned = cleaned.strip(" -:#>|")
    words = cleaned.split()
    if len(words) >= 8 and len(words) % 2 == 0:
        half = len(words) // 2
        if words[:half] == words[half:]:
            cleaned = " ".join(words[:half])
    return cleaned
