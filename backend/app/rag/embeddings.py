"""Text embeddings for policy retrieval (FR-2).

`GeminiEmbedder` calls the Gemini API (`gemini-embedding-2` by default, which normalizes
truncated outputs itself and takes its task as a text prefix). `HashEmbedder` is a deterministic,
offline stand-in for tests and keyless dev: it has no semantics, so retrieval over it is noise.
"""

import asyncio
import hashlib
import logging
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

import httpx

from app.config import Settings
from app.connectors.resilience import backoff_delay

log = logging.getLogger("app.rag.embeddings")

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
BATCH_SIZE = 100  # batchEmbedContents accepts up to 100 requests per call


class Embedder(Protocol):
    async def embed_documents(self, items: list[tuple[str, str]]) -> list[list[float]]:
        """Embed (title, text) pairs for storage."""
        ...

    async def embed_query(self, text: str) -> list[float]: ...


class EmbeddingError(Exception):
    pass


class HashEmbedder:
    def __init__(self, dim: int) -> None:
        self.dim = dim

    def _embed(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode()).digest()
        return [digest[i % len(digest)] / 255.0 for i in range(self.dim)]

    async def embed_documents(self, items: list[tuple[str, str]]) -> list[list[float]]:
        return [self._embed(text) for _, text in items]

    async def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


def query_text(text: str) -> str:
    return f"task: search result | query: {text}"


def document_text(title: str, text: str) -> str:
    return f"title: {title or 'none'} | text: {text}"


class GeminiEmbedder:
    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._settings = settings
        self._model = settings.embedding_model
        self._client = client or httpx.AsyncClient(
            base_url=settings.embedding_api_url,
            headers={"x-goog-api-key": settings.gemini_api_key},
            timeout=30.0,
        )
        self._sleep = sleep

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        last: Exception | None = None
        for attempt in range(self._settings.embedding_max_retries + 1):
            retry_after: float | None = None
            try:
                resp = await self._client.post(path, json=body)
            except httpx.TransportError as exc:
                last = exc
            else:
                if resp.status_code not in RETRYABLE_STATUS:
                    resp.raise_for_status()
                    data: dict[str, Any] = resp.json()
                    return data
                last = httpx.HTTPStatusError(
                    f"embedding upstream {resp.status_code}", request=resp.request, response=resp
                )
                ra = resp.headers.get("retry-after")
                try:
                    retry_after = float(ra) if ra else None
                except ValueError:
                    retry_after = None
            if attempt < self._settings.embedding_max_retries:
                await self._sleep(
                    backoff_delay(attempt, self._settings.embedding_backoff_base_s, retry_after)
                )
        raise EmbeddingError("embedding request failed after retries") from last

    def _request(self, text: str) -> dict[str, Any]:
        return {
            "model": f"models/{self._model}",
            "content": {"parts": [{"text": text}]},
            "output_dimensionality": self._settings.embedding_dim,
        }

    async def _batch(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for start in range(0, len(texts), BATCH_SIZE):
            chunk = texts[start : start + BATCH_SIZE]
            data = await self._post(
                f"/models/{self._model}:batchEmbedContents",
                {"requests": [self._request(t) for t in chunk]},
            )
            vectors = [e["values"] for e in data["embeddings"]]
            if len(vectors) != len(chunk):
                raise EmbeddingError(f"asked for {len(chunk)} embeddings, got {len(vectors)}")
            out.extend(vectors)
        for vector in out:
            if len(vector) != self._settings.embedding_dim:
                raise EmbeddingError(
                    f"embedding has {len(vector)} dims, expected {self._settings.embedding_dim}"
                )
        return out

    async def embed_documents(self, items: list[tuple[str, str]]) -> list[list[float]]:
        return await self._batch([document_text(title, text) for title, text in items])

    async def embed_query(self, text: str) -> list[float]:
        return (await self._batch([query_text(text)]))[0]

    async def aclose(self) -> None:
        await self._client.aclose()


def make_embedder(settings: Settings) -> Embedder:
    if settings.gemini_api_key:
        return GeminiEmbedder(settings)
    log.warning("GEMINI_API_KEY not set: using the hash embedder, retrieval will be meaningless")
    return HashEmbedder(settings.embedding_dim)
