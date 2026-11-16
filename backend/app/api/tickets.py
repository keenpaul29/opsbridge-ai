"""Triage queue, trace inspector and approval endpoints (FR-3/FR-4)."""

import logging
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query

from app.agent.actions import execute_action
from app.api.deps import get_connector
from app.connectors.github import ConnectorError, GitHubConnector
from app.models import TicketStatus, TriageTicket
from app.repository import TicketRepository, get_repository
from app.schemas import (
    ApproveRequest,
    RejectRequest,
    TicketDetail,
    TicketOut,
    TraceOut,
)
from app.state_machine import InvalidTransition, assert_transition

router = APIRouter(prefix="/tickets", tags=["tickets"])
log = logging.getLogger("app.tickets")


async def _get_or_404(repo: TicketRepository, ticket_id: uuid.UUID) -> TriageTicket:
    ticket = await repo.get(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="ticket not found")
    return ticket


def _require_awaiting(ticket: TriageTicket, target: TicketStatus) -> None:
    """Operators may only act on tickets the agent paused for review.

    The state machine also permits PENDING -> EXECUTED (agent auto-approval), which a human
    must not be able to trigger before triage has run.
    """
    if ticket.status != TicketStatus.AWAITING_APPROVAL:
        raise HTTPException(
            status_code=409,
            detail=f"ticket is {ticket.status.value}; only AWAITING_APPROVAL can be {target.value}",
        )
    try:
        assert_transition(ticket.status, target)
    except InvalidTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


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
    ticket = await _get_or_404(repo, ticket_id)
    _require_awaiting(ticket, TicketStatus.EXECUTED)

    recommended = ticket.recommended_action or {}
    if body.edited_payload is not None:
        recommended = {**recommended, "tool_payload": body.edited_payload}

    action = recommended.get("recommended_action")
    if action:
        started = time.perf_counter()
        try:
            await execute_action(
                connector, ticket.raw_payload, action, recommended.get("tool_payload") or {}
            )
        except ConnectorError as exc:
            await repo.set_status(ticket_id, TicketStatus.FAILED)
            await repo.add_trace(
                ticket_id,
                "execute_action",
                input_data={"action": action, "operator": body.operator},
                output_data={"error": str(exc)},
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
            log.exception("action failed", extra={"ticket_id": str(ticket_id), "status": "FAILED"})
            raise HTTPException(status_code=502, detail=f"action failed: {exc}") from exc
        await repo.add_trace(
            ticket_id,
            "execute_action",
            input_data={"action": action},
            output_data={"ok": True},
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

    updated = await repo.set_status(
        ticket_id,
        TicketStatus.EXECUTED,
        recommended_action=recommended if body.edited_payload is not None else None,
    )
    await repo.add_trace(
        ticket_id,
        "operator_approve",
        input_data={"operator": body.operator, "edited": body.edited_payload is not None},
    )
    log.info("ticket approved", extra={"ticket_id": str(ticket_id), "status": "EXECUTED"})
    return updated


@router.post("/{ticket_id}/reject", response_model=TicketOut)
async def reject(
    ticket_id: uuid.UUID,
    body: RejectRequest,
    repo: TicketRepository = Depends(get_repository),
) -> TriageTicket:
    ticket = await _get_or_404(repo, ticket_id)
    _require_awaiting(ticket, TicketStatus.REJECTED)

    updated = await repo.set_status(ticket_id, TicketStatus.REJECTED)
    await repo.add_trace(
        ticket_id,
        "operator_reject",
        input_data={"operator": body.operator, "reason": body.reason},
    )
    log.info("ticket rejected", extra={"ticket_id": str(ticket_id), "status": "REJECTED"})
    return updated
