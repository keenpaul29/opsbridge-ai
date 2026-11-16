"""Typed GitHub Issues connector: backoff on 429/5xx, circuit breaker, schema validation."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.connectors.resilience import CircuitBreaker, backoff_delay

log = logging.getLogger("app.connector.github")

RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class ConnectorError(Exception):
    pass


class UpstreamSchemaError(ConnectorError):
    """Upstream returned a 2xx body that failed schema validation."""


class IssueContext(BaseModel):
    number: int
    title: str
    state: str
    body: str | None = None
    labels: list[dict[str, Any]] = []
    user: dict[str, Any] | None = None


class GitHubConnector:
    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._settings = settings
        headers = {"Accept": "application/vnd.github+json"}
        if settings.github_token:
            headers["Authorization"] = f"Bearer {settings.github_token}"
        self._client = client or httpx.AsyncClient(
            base_url=settings.github_api_url, headers=headers, timeout=10.0
        )
        self._breaker = CircuitBreaker(
            settings.connector_breaker_threshold, settings.connector_breaker_reset_s
        )
        self._sleep = sleep

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        self._breaker.before_call()
        max_retries = self._settings.connector_max_retries
        last_exc: Exception | None = None
        for attempt in range(max_retries + 1):
            start = time.perf_counter()
            try:
                resp = await self._client.request(method, path, **kwargs)
            except httpx.TransportError as exc:
                last_exc = exc
                status: int | str = "transport_error"
                retry_after = None
            else:
                status = resp.status_code
                latency_ms = int((time.perf_counter() - start) * 1000)
                log.info(
                    "connector call",
                    extra={
                        "step": f"github {method} {path}",
                        "status": status,
                        "latency_ms": latency_ms,
                    },
                )
                if resp.status_code not in RETRYABLE_STATUS:
                    self._breaker.record_success()
                    resp.raise_for_status()
                    return resp
                last_exc = httpx.HTTPStatusError(
                    f"upstream {resp.status_code}", request=resp.request, response=resp
                )
                ra = resp.headers.get("retry-after")
                retry_after = float(ra) if ra and ra.isdigit() else None

            if attempt < max_retries:
                await self._sleep(
                    backoff_delay(attempt, self._settings.connector_backoff_base_s, retry_after)
                )
        self._breaker.record_failure()
        raise ConnectorError(
            f"{method} {path} failed after {max_retries + 1} attempts"
        ) from last_exc

    # -- reads ---------------------------------------------------------------------------

    async def get_issue(self, repo: str, number: int) -> IssueContext:
        resp = await self._request("GET", f"/repos/{repo}/issues/{number}")
        try:
            return IssueContext.model_validate(resp.json())
        except (ValidationError, ValueError) as exc:
            raise UpstreamSchemaError(f"malformed issue payload for {repo}#{number}") from exc

    async def ping(self) -> bool:
        try:
            await self._request("GET", "/rate_limit")
            return True
        except Exception:
            return False

    # -- actions -------------------------------------------------------------------------

    async def add_labels(self, repo: str, number: int, labels: list[str]) -> None:
        await self._request(
            "POST", f"/repos/{repo}/issues/{number}/labels", json={"labels": labels}
        )

    async def post_comment(self, repo: str, number: int, body: str) -> None:
        await self._request("POST", f"/repos/{repo}/issues/{number}/comments", json={"body": body})
