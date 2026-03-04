from __future__ import annotations

import unittest

from src.rag.embedder import BaseEmbedder, ResilientEmbedder, build_embedder


class _AlwaysFailEmbedder(BaseEmbedder):
    provider_name = "always-fail"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("upstream unavailable")

    def embed_query(self, text: str) -> list[float]:
        raise RuntimeError("upstream unavailable")


class _ConstantEmbedder(BaseEmbedder):
    provider_name = "constant"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0] for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return [1.0, 0.0]


class _FailThenOkEmbedder(BaseEmbedder):
    provider_name = "flaky"

    def __init__(self, fail_count: int = 1) -> None:
        self._remaining_failures = fail_count
        self.calls = 0

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        if self._remaining_failures > 0:
            self._remaining_failures -= 1
            raise RuntimeError("temporary upstream failure")
        return [[0.5, 0.5] for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        self.calls += 1
        if self._remaining_failures > 0:
            self._remaining_failures -= 1
            raise RuntimeError("temporary upstream failure")
        return [0.5, 0.5]


class EmbedderResilienceTests(unittest.TestCase):
    def test_build_embedder_without_api_key_uses_hash(self) -> None:
        embedder = build_embedder(api_key="", model="gemini-embedding-001")
        self.assertEqual(embedder.provider_name, "hash-fallback")

    def test_resilient_embedder_switches_to_fallback(self) -> None:
        embedder = ResilientEmbedder(
            primary=_AlwaysFailEmbedder(),
            fallback=_ConstantEmbedder(),
        )
        vectors = embedder.embed_texts(["a", "b"])
        query = embedder.embed_query("q")

        self.assertEqual(len(vectors), 2)
        self.assertEqual(vectors[0], [1.0, 0.0])
        self.assertEqual(query, [1.0, 0.0])
        self.assertEqual(embedder.provider_name, "always-fail->constant")

    def test_resilient_embedder_recovers_after_cooldown(self) -> None:
        primary = _FailThenOkEmbedder(fail_count=1)
        clock = [0.0]
        embedder = ResilientEmbedder(
            primary=primary,
            fallback=_ConstantEmbedder(),
            cooldown_seconds=10.0,
            time_fn=lambda: clock[0],
        )

        first = embedder.embed_query("q1")
        self.assertEqual(first, [1.0, 0.0])
        self.assertEqual(primary.calls, 1)

        clock[0] = 5.0
        second = embedder.embed_query("q2")
        self.assertEqual(second, [1.0, 0.0])
        self.assertEqual(primary.calls, 1)

        clock[0] = 11.0
        third = embedder.embed_query("q3")
        self.assertEqual(third, [0.5, 0.5])
        self.assertEqual(primary.calls, 2)
        self.assertEqual(embedder.provider_name, "flaky")


if __name__ == "__main__":
    unittest.main()
