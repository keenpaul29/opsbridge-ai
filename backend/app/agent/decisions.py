"""Carry out a triage decision: the one place that runs an action and settles the ticket.

Two triggers share this logic: the agent auto-approving a low-risk, high-confidence decision
(`auto_execute`) and an operator approving from the console (`approve_ticket`). Callers never
touch the connector, the state machine or the trace schema.

Interface contract
- Bad state raises `NotApprovable`, a missing ticket raises `TicketNotFound`; the API maps them
  to 409/404 (see `app.api.errors`).
- A connector failure is NOT raised. The ticket is moved to FAILED, the error is traced, and the
  returned `Outcome.error` is set. A failed action never reads as success.
- Order: validate state -> run action -> `execute_action` trace -> status write -> operator trace.
  On failure the status is written before the trace, and no operator trace is written.
"""

import asyncio
import logging
import time
import uuid
import weakref
from dataclasses import dataclass
from typing import Any

from app.agent.actions import execute_action
from app.connectors.github import GitHubConnector
from app.models import TicketStatus, TriageTicket
from app.repository import TicketRepository
from app.schemas import TriageDecision
from app.state_machine import InvalidTransition, assert_transition

log = logging.getLogger("app.decisions")

AGENT = "agent"

# Serialises decisions per ticket within this process, so a double-click or an approve racing a
# reject cannot both pass the state check and run the action twice. It does NOT protect across
# replicas: that needs an atomic claim in the repository (UPDATE ... WHERE status = ...).
_locks: "weakref.WeakValueDictionary[uuid.UUID, asyncio.Lock]" = weakref.WeakValueDictionary()


def _lock_for(ticket_id: uuid.UUID) -> asyncio.Lock:
    lock = _locks.get(ticket_id)
    if lock is None:
        lock = _locks[ticket_id] = asyncio.Lock()
    return lock


class DecisionError(Exception):
    pass


class NotApprovable(DecisionError):
    """The ticket is not in a state this actor may move it out of."""


class TicketNotFound(DecisionError):
    pass


@dataclass(frozen=True)
class Outcome:
    ticket: TriageTicket
    error: str | None = None  # set iff the connector failed; the ticket is then FAILED


async def approve_ticket(
    repo: TicketRepository,
    connector: GitHubConnector,
    ticket_id: uuid.UUID,
    *,
    operator: str,
    edited_payload: dict[str, Any] | None = None,
) -> Outcome:
    """Operator approval of a ticket the agent paused for review (AWAITING_APPROVAL)."""
    async with _lock_for(ticket_id):
        ticket = await _load(repo, ticket_id)
        _require(ticket, TicketStatus.AWAITING_APPROVAL, TicketStatus.EXECUTED)

        recommended = ticket.recommended_action or {}
        if edited_payload is not None:
            recommended = {**recommended, "tool_payload": edited_payload}
        return await _execute(
            repo,
            connector,
            ticket,
            recommended,
            operator=operator,
            persist=recommended if edited_payload is not None else None,
            edited=edited_payload is not None,
        )


async def auto_execute(
    repo: TicketRepository,
    connector: GitHubConnector,
    ticket_id: uuid.UUID,
    decision: TriageDecision,
) -> Outcome:
    """Agent auto-approval of a fresh decision on a PENDING ticket; persists the decision."""
    async with _lock_for(ticket_id):
        ticket = await _load(repo, ticket_id)
        _require(ticket, TicketStatus.PENDING, TicketStatus.EXECUTED)
        return await _execute(
            repo,
            connector,
            ticket,
            decision.model_dump(mode="json"),
            operator=None,
            persist=decision.model_dump(mode="json"),
            confidence=decision.confidence_score,
        )


async def reject_ticket(
    repo: TicketRepository, ticket_id: uuid.UUID, *, operator: str, reason: str
) -> TriageTicket:
    async with _lock_for(ticket_id):
        ticket = await _load(repo, ticket_id)
        _require(ticket, TicketStatus.AWAITING_APPROVAL, TicketStatus.REJECTED)
        updated = await repo.set_status(ticket_id, TicketStatus.REJECTED)
        await repo.add_trace(
            ticket_id, "operator_reject", input_data={"operator": operator, "reason": reason}
        )
        log.info("ticket rejected", extra={"ticket_id": str(ticket_id), "status": "REJECTED"})
        return updated


async def _load(repo: TicketRepository, ticket_id: uuid.UUID) -> TriageTicket:
    ticket = await repo.get(ticket_id)
    if ticket is None:
        raise TicketNotFound("ticket not found")
    return ticket


def _require(ticket: TriageTicket, required: TicketStatus, target: TicketStatus) -> None:
    # Stricter than the state machine: it also allows PENDING -> EXECUTED, which an operator
    # must not trigger before triage has run, and AWAITING_APPROVAL -> EXECUTED, which the agent
    # must not trigger on its own.
    if ticket.status != required:
        raise NotApprovable(
            f"ticket is {ticket.status.value}; only {required.value} can be {target.value}"
        )
    try:
        assert_transition(ticket.status, target)
    except InvalidTransition as exc:
        raise NotApprovable(str(exc)) from exc


async def _execute(
    repo: TicketRepository,
    connector: GitHubConnector,
    ticket: TriageTicket,
    recommended: dict[str, Any],
    *,
    operator: str | None,
    persist: dict[str, Any] | None,
    confidence: float | None = None,
    edited: bool = False,
) -> Outcome:
    action = recommended.get("recommended_action")
    actor = operator or AGENT
    error: str | None = None
    started = time.perf_counter()
    if action:
        try:
            await execute_action(
                connector, ticket.raw_payload, action, recommended.get("tool_payload") or {}
            )
        except Exception as exc:  # a connector error or a malformed payload: either way FAILED
            error = str(exc) or type(exc).__name__
            log.exception("action failed", extra={"ticket_id": str(ticket.id), "status": "FAILED"})
    latency_ms = int((time.perf_counter() - started) * 1000)
    trace_input = {"action": action, "operator": actor}

    if error is not None:
        updated = await repo.set_status(
            ticket.id, TicketStatus.FAILED, recommended_action=persist, confidence_score=confidence
        )
        await repo.add_trace(
            ticket.id,
            "execute_action",
            input_data=trace_input,
            output_data={"error": error},
            latency_ms=latency_ms,
        )
        return Outcome(updated, error)

    if action:
        await repo.add_trace(
            ticket.id,
            "execute_action",
            input_data=trace_input,
            output_data={"ok": True},
            latency_ms=latency_ms,
        )
    updated = await repo.set_status(
        ticket.id, TicketStatus.EXECUTED, recommended_action=persist, confidence_score=confidence
    )
    if operator is not None:
        await repo.add_trace(
            ticket.id,
            "operator_approve",
            input_data={"operator": operator, "edited": edited},
        )
    log.info("ticket executed", extra={"ticket_id": str(ticket.id), "status": "EXECUTED"})
    return Outcome(updated)
