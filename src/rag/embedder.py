"""Embedding providers for semantic retrieval."""

from __future__ import annotations

import hashlib
import math
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import TypeVar

from google import genai
from google.genai import types

T = TypeVar("T")


class EmbedderError(RuntimeError):
    """Raised when embedding generation fails."""


class BaseEmbedder:
    provider_name = "base"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    def embed_query(self, text: str) -> list[float]:
        raise NotImplementedError


@dataclass
class GeminiEmbedder(BaseEmbedder):
    api_key: str
    model: str = "gemini-embedding-001"
    task_type_document: str = "RETRIEVAL_DOCUMENT"
    task_type_query: str = "RETRIEVAL_QUERY"
    fallback_models: tuple[str, ...] = ("gemini-embedding-001", "text-embedding-004")

    provider_name = "gemini"

    def __post_init__(self) -> None:
        self._client = genai.Client(api_key=self.api_key)
        self._model_candidates = _unique_models([self.model, *self.fallback_models])
        self._active_model = self._model_candidates[0] if self._model_candidates else "gemini-embedding-001"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            vectors.append(_normalize_vector(self._embed_single(text, self.task_type_document)))
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return _normalize_vector(self._embed_single(text, self.task_type_query))

    def _embed_single(self, text: str, task_type: str) -> list[float]:
        errors: list[str] = []
        for candidate in self._model_candidates:
            try:
                response = self._client.models.embed_content(
                    model=candidate,
                    contents=text,
                    config=types.EmbedContentConfig(task_type=task_type),
                )
                if not response.embeddings:
                    raise EmbedderError("Gemini embed response is missing embedding data.")
                values = response.embeddings[0].values
                if not values:
                    raise EmbedderError("Gemini embed response has empty vector.")
                self._active_model = candidate
                return [float(value) for value in values]
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{candidate}: {exc}")
                if not _is_model_not_supported_error(exc):
                    raise EmbedderError(f"Gemini embedding failed on model '{candidate}': {exc}") from exc
        raise EmbedderError(
            "Gemini embedding failed for all model candidates: " + " | ".join(errors)
        )


@dataclass
class HashEmbedder(BaseEmbedder):
    dim: int = 256

    provider_name = "hash-fallback"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [_normalize_vector(_hash_to_vector(text, self.dim)) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return _normalize_vector(_hash_to_vector(text, self.dim))


class ResilientEmbedder(BaseEmbedder):
    def __init__(
        self,
        primary: BaseEmbedder,
        fallback: BaseEmbedder,
        *,
        cooldown_seconds: float = 120.0,
        time_fn: Callable[[], float] | None = None,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._fallback_active = False
        self._cooldown_seconds = max(1.0, float(cooldown_seconds))
        self._fallback_until = 0.0
        self._time_fn = time_fn or time.monotonic

    @property
    def fallback_active(self) -> bool:
        return self._fallback_active

    @property
    def provider_name(self) -> str:  # type: ignore[override]
        if self._fallback_active:
            return f"{self._primary.provider_name}->{self._fallback.provider_name}"
        return self._primary.provider_name

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return self._execute_with_failover(
            primary_call=lambda: self._primary.embed_texts(texts),
            fallback_call=lambda: self._fallback.embed_texts(texts),
        )

    def embed_query(self, text: str) -> list[float]:
        return self._execute_with_failover(
            primary_call=lambda: self._primary.embed_query(text),
            fallback_call=lambda: self._fallback.embed_query(text),
        )

    def _execute_with_failover(
        self,
        *,
        primary_call: Callable[[], T],
        fallback_call: Callable[[], T],
    ) -> T:
        now = self._time_fn()
        if self._fallback_active and now < self._fallback_until:
            return fallback_call()

        try:
            result = primary_call()
            self._fallback_active = False
            self._fallback_until = 0.0
            return result
        except Exception:
            self._fallback_active = True
            self._fallback_until = self._time_fn() + self._cooldown_seconds
            return fallback_call()


def build_embedder(api_key: str = "", model: str = "gemini-embedding-001") -> BaseEmbedder:
    api_key = (api_key or "").strip()
    model = (model or "gemini-embedding-001").strip()
    if api_key:
        return ResilientEmbedder(
            primary=GeminiEmbedder(api_key=api_key, model=model),
            fallback=HashEmbedder(),
        )
    return HashEmbedder()


def _hash_to_vector(text: str, dim: int) -> list[float]:
    if not text.strip():
        return [0.0] * dim
    payload = text.encode("utf-8")
    values = [0.0] * dim
    for i in range(dim):
        digest = hashlib.sha256(payload + f":{i}".encode("ascii")).digest()
        as_int = int.from_bytes(digest[:4], "big", signed=False)
        values[i] = (as_int / 0xFFFFFFFF) * 2.0 - 1.0
    return values


def _normalize_vector(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0:
        return vector
    return [v / norm for v in vector]


def _is_model_not_supported_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return "not found" in text or "not supported for embedcontent" in text


def _unique_models(models: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in models:
        model = (item or "").strip()
        if not model or model in seen:
            continue
        seen.add(model)
        ordered.append(model)
    return ordered
