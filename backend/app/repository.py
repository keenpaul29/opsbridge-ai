"""Persistence boundary. API routes depend on the protocol so tests can swap in a fake."""

import uuid
from typing import Any, Protocol

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import AgentTrace, EvalRun, TicketStatus, TriageTicket


class TicketRepository(Protocol):
    async def create_if_new(
        self, *, external_event_id: str, provider: str, raw_payload: dict[str, Any]
    ) -> TriageTicket | None: ...

    async def get(self, ticket_id: uuid.UUID) -> TriageTicket | None: ...

    async def list_tickets(self, status: TicketStatus | None, limit: int) -> list[TriageTicket]: ...

    async def set_status(
        self,
        ticket_id: uuid.UUID,
        status: TicketStatus,
        *,
        recommended_action: dict[str, Any] | None = None,
        confidence_score: float | None = None,
    ) -> TriageTicket: ...

    async def add_trace(
        self,
        ticket_id: uuid.UUID,
        step_name: str,
        *,
        input_data: dict[str, Any] | None = None,
        output_data: dict[str, Any] | None = None,
        citations: list[dict[str, Any]] | None = None,
        latency_ms: int = 0,
    ) -> AgentTrace: ...

    async def traces(self, ticket_id: uuid.UUID) -> list[AgentTrace]: ...

    async def latest_eval_run(self) -> EvalRun | None: ...


class SqlTicketRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_if_new(
        self, *, external_event_id: str, provider: str, raw_payload: dict[str, Any]
    ) -> TriageTicket | None:
        # ON CONFLICT DO NOTHING makes duplicate deliveries race-safe at the DB level.
        stmt = (
            pg_insert(TriageTicket)
            .values(
                id=uuid.uuid4(),
                external_event_id=external_event_id,
                provider=provider,
                raw_payload=raw_payload,
                status=TicketStatus.PENDING,
            )
            .on_conflict_do_nothing(index_elements=["external_event_id"])
            .returning(TriageTicket)
        )
        ticket = (await self.session.execute(stmt)).scalar_one_or_none()
        await self.session.commit()
        return ticket

    async def get(self, ticket_id: uuid.UUID) -> TriageTicket | None:
        return await self.session.get(TriageTicket, ticket_id)

    async def list_tickets(self, status: TicketStatus | None, limit: int) -> list[TriageTicket]:
        stmt = select(TriageTicket).order_by(TriageTicket.created_at.desc()).limit(limit)
        if status is not None:
            stmt = stmt.where(TriageTicket.status == status)
        return list((await self.session.execute(stmt)).scalars())

    async def set_status(
        self,
        ticket_id: uuid.UUID,
        status: TicketStatus,
        *,
        recommended_action: dict[str, Any] | None = None,
        confidence_score: float | None = None,
    ) -> TriageTicket:
        ticket = await self.session.get(TriageTicket, ticket_id)
        if ticket is None:
            raise LookupError(f"ticket {ticket_id} not found")
        ticket.status = status
        if recommended_action is not None:
            ticket.recommended_action = recommended_action
        if confidence_score is not None:
            ticket.confidence_score = confidence_score
        await self.session.commit()
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
            ticket_id=ticket_id,
            step_name=step_name,
            input_data=input_data,
            output_data=output_data,
            citations=citations,
            latency_ms=latency_ms,
        )
        self.session.add(trace)
        await self.session.commit()
        return trace

    async def traces(self, ticket_id: uuid.UUID) -> list[AgentTrace]:
        stmt = (
            select(AgentTrace)
            .where(AgentTrace.ticket_id == ticket_id)
            .order_by(AgentTrace.created_at)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def latest_eval_run(self) -> EvalRun | None:
        stmt = select(EvalRun).order_by(EvalRun.created_at.desc()).limit(1)
        return (await self.session.execute(stmt)).scalar_one_or_none()


def get_repository(session: AsyncSession = Depends(get_session)) -> TicketRepository:
    return SqlTicketRepository(session)
