import httpx
import pytest

from app.config import Settings
from app.connectors.github import ConnectorError, GitHubConnector, UpstreamSchemaError
from app.connectors.resilience import CircuitBreaker, CircuitOpenError

ISSUE = {"number": 1, "title": "t", "state": "open"}


def make(handler, **overrides) -> tuple[GitHubConnector, list[float]]:
    sleeps: list[float] = []

    async def fake_sleep(s: float) -> None:
        sleeps.append(s)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.github.com"
    )
    settings = Settings(connector_max_retries=3, connector_backoff_base_s=0.01, **overrides)
    return GitHubConnector(settings, client=client, sleep=fake_sleep), sleeps


async def test_retries_429_then_succeeds():
    calls = {"n": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, headers={"retry-after": "2"})
        return httpx.Response(200, json=ISSUE)

    connector, sleeps = make(handler)
    issue = await connector.get_issue("a/b", 1)
    assert issue.number == 1
    assert calls["n"] == 3
    assert all(s >= 2 for s in sleeps)  # Retry-After honoured


async def test_gives_up_after_max_retries_on_5xx():
    calls = {"n": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503)

    connector, _ = make(handler)
    with pytest.raises(ConnectorError):
        await connector.get_issue("a/b", 1)
    assert calls["n"] == 4  # 1 try + 3 retries


async def test_4xx_is_not_retried():
    calls = {"n": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(404)

    connector, _ = make(handler)
    with pytest.raises(httpx.HTTPStatusError):
        await connector.get_issue("a/b", 1)
    assert calls["n"] == 1


async def test_malformed_upstream_body_raises_schema_error():
    connector, _ = make(lambda _: httpx.Response(200, json={"unexpected": True}))
    with pytest.raises(UpstreamSchemaError):
        await connector.get_issue("a/b", 1)


def test_circuit_breaker_opens_then_half_opens():
    now = [0.0]
    breaker = CircuitBreaker(threshold=2, reset_s=10, clock=lambda: now[0])
    breaker.record_failure()
    breaker.before_call()  # still closed
    breaker.record_failure()
    with pytest.raises(CircuitOpenError):
        breaker.before_call()
    now[0] = 11.0
    breaker.before_call()  # half-open probe allowed
    breaker.record_success()
    assert not breaker.is_open
