"""Gemini embedder behaviour through its interface, with a mocked HTTP transport."""

import json

import httpx
import pytest

from app.config import Settings
from app.rag.embeddings import (
    EmbeddingError,
    GeminiEmbedder,
    HashEmbedder,
    make_embedder,
)

DIM = 4


def settings(**kw: object) -> Settings:
    return Settings(
        _env_file=None,
        gemini_api_key="k",
        embedding_dim=DIM,
        embedding_max_retries=2,
        embedding_backoff_base_s=0.0,
        **kw,  # type: ignore[arg-type]
    )


def embedder(handler: httpx.MockTransport, s: Settings | None = None) -> GeminiEmbedder:
    s = s or settings()
    client = httpx.AsyncClient(
        base_url=s.embedding_api_url,
        headers={"x-goog-api-key": s.gemini_api_key},
        transport=handler,
    )

    async def no_sleep(_: float) -> None:
        return None

    return GeminiEmbedder(s, client=client, sleep=no_sleep)


def ok(n: int) -> httpx.Response:
    return httpx.Response(200, json={"embeddings": [{"values": [0.1] * DIM} for _ in range(n)]})


async def test_documents_are_sent_as_one_titled_batch_with_dimension_and_key():
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return ok(2)

    vectors = await embedder(httpx.MockTransport(handler)).embed_documents(
        [("refunds.md", "30 day rule"), ("bugs.md", "label bug")]
    )
    assert len(vectors) == 2 and len(vectors[0]) == DIM
    assert len(seen) == 1
    req = seen[0]
    assert req.url.path.endswith("/models/gemini-embedding-2:batchEmbedContents")
    assert req.headers["x-goog-api-key"] == "k"
    items = json.loads(req.content)["requests"]
    assert items[0]["model"] == "models/gemini-embedding-2"
    assert items[0]["output_dimensionality"] == DIM
    assert items[0]["content"]["parts"][0]["text"] == "title: refunds.md | text: 30 day rule"


async def test_query_uses_the_search_prefix():
    bodies: list[dict[str, object]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(req.content))
        return ok(1)

    vector = await embedder(httpx.MockTransport(handler)).embed_query("refund old order")
    assert len(vector) == DIM
    text = bodies[0]["requests"][0]["content"]["parts"][0]["text"]  # type: ignore[index]
    assert text == "task: search result | query: refund old order"


async def test_retries_rate_limits_then_succeeds():
    calls = {"n": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429, headers={"retry-after": "0"}) if calls["n"] < 3 else ok(1)

    assert await embedder(httpx.MockTransport(handler)).embed_query("q")
    assert calls["n"] == 3


async def test_gives_up_after_configured_retries():
    calls = {"n": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503)

    with pytest.raises(EmbeddingError):
        await embedder(httpx.MockTransport(handler)).embed_query("q")
    assert calls["n"] == 3  # first attempt + 2 retries


async def test_client_errors_are_not_retried():
    calls = {"n": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(400, json={"error": "bad key"})

    with pytest.raises(httpx.HTTPStatusError):
        await embedder(httpx.MockTransport(handler)).embed_query("q")
    assert calls["n"] == 1


async def test_wrong_dimension_is_rejected_not_stored():
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"embeddings": [{"values": [0.1] * (DIM + 1)}]})

    with pytest.raises(EmbeddingError, match="dims"):
        await embedder(httpx.MockTransport(handler)).embed_query("q")


async def test_large_documents_split_into_batches_of_100():
    sizes: list[int] = []

    def handler(req: httpx.Request) -> httpx.Response:
        n = len(json.loads(req.content)["requests"])
        sizes.append(n)
        return ok(n)

    items = [("d.md", f"chunk {i}") for i in range(230)]
    vectors = await embedder(httpx.MockTransport(handler)).embed_documents(items)
    assert sizes == [100, 100, 30] and len(vectors) == 230


async def test_hash_embedder_is_deterministic_and_sized():
    e = HashEmbedder(DIM)
    assert await e.embed_query("x") == await e.embed_query("x")
    assert len((await e.embed_documents([("t", "x")]))[0]) == DIM


def test_make_embedder_picks_gemini_only_with_a_key():
    assert isinstance(make_embedder(settings()), GeminiEmbedder)
    assert isinstance(make_embedder(Settings(_env_file=None, gemini_api_key="")), HashEmbedder)
