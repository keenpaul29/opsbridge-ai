"""Triage queue, trace inspector and approval endpoints (FR-3/FR-4)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query

from app.agent.decisions import approve_ticket, reject_ticket
from app.api.deps import get_connector
from app.connectors.github import GitHubConnector
from app.models import TicketStatus, TriageTicket
from app.repository import TicketRepository, get_repository
from app.schemas import (
    ApproveRequest,
    RejectRequest,
    TicketDetail,
    TicketOut,
    TraceOut,
)

router = APIRouter(prefix="/tickets", tags=["tickets"])


async def _get_or_404(repo: TicketRepository, ticket_id: uuid.UUID) -> TriageTicket:
    ticket = await repo.get(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="ticket not found")
    return ticket


@router.get("", response_model=list[TicketOut])
async def list_tickets(
    status: TicketStatus | None = None,
    limit: int = Query(50, ge=1, le=200),
    repo: TicketRepository = Depends(get_repository),
) -> list[TriageTicket]:
    return await repo.list_tickets(status, limit)


@router.get("/{ticket_id}", response_model=TicketDetail)
async def get_ticket(
    ticket_id: uuid.UUID, repo: TicketRepository = Depends(get_repository)
) -> TriageTicket:
    return await _get_or_404(repo, ticket_id)


@router.get("/{ticket_id}/traces", response_model=list[TraceOut])
async def get_traces(
    ticket_id: uuid.UUID, repo: TicketRepository = Depends(get_repository)
) -> list:  # type: ignore[type-arg]
    await _get_or_404(repo, ticket_id)
    return await repo.traces(ticket_id)


@router.post("/{ticket_id}/approve", response_model=TicketOut)
async def approve(
    ticket_id: uuid.UUID,
    body: ApproveRequest,
    repo: TicketRepository = Depends(get_repository),
    connector: GitHubConnector = Depends(get_connector),
) -> TriageTicket:
    outcome = await approve_ticket(
        repo, connector, ticket_id, operator=body.operator, edited_payload=body.edited_payload
    )
    if outcome.error is not None:
        raise HTTPException(status_code=502, detail=f"action failed: {outcome.error}")
    return outcome.ticket


@router.post("/{ticket_id}/reject", response_model=TicketOut)
async def reject(
    ticket_id: uuid.UUID,
    body: RejectRequest,
    repo: TicketRepository = Depends(get_repository),
) -> TriageTicket:
    return await reject_ticket(repo, ticket_id, operator=body.operator, reason=body.reason)
