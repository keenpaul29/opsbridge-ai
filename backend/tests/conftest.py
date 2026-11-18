import hashlib
import hmac
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_connector, get_triage_scheduler
from app.config import Settings, get_settings
from app.main import create_app
from app.models import AgentTrace, EvalRun, TicketStatus, TriageTicket
from app.repository import get_repository

SECRET = "test-secret"


class FakeRepo:
    """In-memory TicketRepository so API tests need no Postgres."""

    def __init__(self) -> None:
        self.tickets: dict[uuid.UUID, TriageTicket] = {}
        self.trace_log: list[AgentTrace] = []
        self.eval_runs: list[EvalRun] = []

    async def create_if_new(
        self, *, external_event_id: str, provider: str, raw_payload: dict[str, Any]
    ) -> TriageTicket | None:
        if any(t.external_event_id == external_event_id for t in self.tickets.values()):
            return None
        now = datetime.now(UTC)
        ticket = TriageTicket(
            id=uuid.uuid4(),
            external_event_id=external_event_id,
            provider=provider,
            raw_payload=raw_payload,
            status=TicketStatus.PENDING,
            recommended_action=None,
            confidence_score=None,
            created_at=now,
            updated_at=now,
        )
        self.tickets[ticket.id] = ticket
        return ticket

    async def get(self, ticket_id: uuid.UUID) -> TriageTicket | None:
        return self.tickets.get(ticket_id)

    async def list_tickets(self, status: TicketStatus | None, limit: int) -> list[TriageTicket]:
        rows = [t for t in self.tickets.values() if status is None or t.status == status]
        return rows[:limit]

    async def set_status(
        self,
        ticket_id: uuid.UUID,
        status: TicketStatus,
        *,
        recommended_action: dict[str, Any] | None = None,
        confidence_score: float | None = None,
    ) -> TriageTicket:
        ticket = self.tickets[ticket_id]
        ticket.status = status
        if recommended_action is not None:
            ticket.recommended_action = recommended_action
        if confidence_score is not None:
            ticket.confidence_score = confidence_score
        return ticket

    async def add_trace(
        self,
        ticket_id: uuid.UUID,
        step_name: str,
        *,
        input_data: dict[str, Any] | None = None,
        output_data: dict[str, Any] | None = None,
        citations: list[dict[str, Any]] | None = None,
        latency_ms: int = 0,
    ) -> AgentTrace:
        trace = AgentTrace(
            id=uuid.uuid4(),
            ticket_id=ticket_id,
            step_name=step_name,
            input_data=input_data,
            output_data=output_data,
            citations=citations,
            latency_ms=latency_ms,
            created_at=datetime.now(UTC),
        )
        self.trace_log.append(trace)
        return trace

    async def traces(self, ticket_id: uuid.UUID) -> list[AgentTrace]:
        return [t for t in self.trace_log if t.ticket_id == ticket_id]

    async def latest_eval_run(self) -> EvalRun | None:
        return self.eval_runs[-1] if self.eval_runs else None

    async def add_eval_run(
        self,
        *,
        git_sha: str,
        total_cases: int,
        pass_rate: float,
        tool_accuracy: float,
        groundedness_score: float,
        p95_latency_ms: int,
    ) -> EvalRun:
        run = EvalRun(
            id=uuid.uuid4(),
            git_sha=git_sha,
            total_cases=total_cases,
            pass_rate=pass_rate,
            tool_accuracy=tool_accuracy,
            groundedness_score=groundedness_score,
            p95_latency_ms=p95_latency_ms,
            created_at=datetime.now(UTC),
        )
        self.eval_runs.append(run)
        return run


class FakeConnector:
    async def ping(self) -> bool:
        return True


@pytest.fixture
def repo() -> FakeRepo:
    return FakeRepo()


@pytest.fixture
def scheduled() -> list[uuid.UUID]:
    return []


@pytest.fixture
def app(repo: FakeRepo, scheduled: list[uuid.UUID]) -> Iterator[FastAPI]:
    application = create_app()
    application.dependency_overrides[get_repository] = lambda: repo
    application.dependency_overrides[get_settings] = lambda: Settings(webhook_secret=SECRET)
    application.dependency_overrides[get_connector] = lambda: FakeConnector()

    async def _record(ticket_id: uuid.UUID) -> None:
        scheduled.append(ticket_id)

    application.dependency_overrides[get_triage_scheduler] = lambda: _record
    yield application


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    # No `with` block: skips lifespan, so no DB/connector startup is required.
    return TestClient(app)


def sign(body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
