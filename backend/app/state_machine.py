"""Ticket lifecycle + HITL guardrail routing (FR-3). Pure functions: no I/O, easy to eval."""

from app.models import TicketStatus
from app.schemas import TriageDecision

# Actions that may auto-execute when confidence is high enough.
LOW_RISK_ACTIONS = frozenset({"label", "route"})

_TRANSITIONS: dict[TicketStatus, frozenset[TicketStatus]] = {
    TicketStatus.PENDING: frozenset(
        {TicketStatus.AWAITING_APPROVAL, TicketStatus.EXECUTED, TicketStatus.FAILED}
    ),
    TicketStatus.AWAITING_APPROVAL: frozenset(
        {TicketStatus.EXECUTED, TicketStatus.REJECTED, TicketStatus.FAILED}
    ),
    TicketStatus.EXECUTED: frozenset(),
    TicketStatus.REJECTED: frozenset(),
    TicketStatus.FAILED: frozenset(),
}


class InvalidTransition(Exception):
    def __init__(self, current: TicketStatus, target: TicketStatus) -> None:
        super().__init__(f"cannot move ticket from {current.value} to {target.value}")
        self.current = current
        self.target = target


def assert_transition(current: TicketStatus, target: TicketStatus) -> None:
    if target not in _TRANSITIONS[current]:
        raise InvalidTransition(current, target)


def route_decision(decision: TriageDecision, threshold: float) -> TicketStatus:
    """Return the status a fresh decision should land in.

    Auto-approve only low-risk actions at/above the threshold; everything else waits for a human.
    """
    if decision.recommended_action in LOW_RISK_ACTIONS and decision.confidence_score >= threshold:
        return TicketStatus.EXECUTED
    return TicketStatus.AWAITING_APPROVAL
