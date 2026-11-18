"""Behaviour of the decision module through its interface (fake repo + recording connector)."""

import asyncio
import uuid
from typing import Any

import pytest

from app.agent.decisions import (
    NotApprovable,
    TicketNotFound,
    approve_ticket,
    auto_execute,
    reject_ticket,
)
from app.connectors.github import ConnectorError
from app.models import TicketStatus
from app.schemas import TriageDecision
from tests.conftest import FakeRepo

EVENT = {"repository": {"full_name": "o/r"}, "issue": {"number": 3}}
REFUND = {"recommended_action": "refund_draft", "tool_payload": {"body": "hi"}}


class Connector:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.comments: list[str] = []
        self.labels: list[list[str]] = []

    async def post_comment(self, repo: str, number: int, body: str) -> None:
        if self.fail:
            raise ConnectorError("upstream down")
        self.comments.append(body)

    async def add_labels(self, repo: str, number: int, labels: list[str]) -> None:
        if self.fail:
            raise ConnectorError("upstream down")
        self.labels.append(labels)


async def seed(
    repo: FakeRepo, status: TicketStatus, recommended: dict[str, Any] | None = None
) -> uuid.UUID:
    ticket = await repo.create_if_new(
        external_event_id=uuid.uuid4().hex, provider="github", raw_payload=EVENT
    )
    assert ticket is not None
    await repo.set_status(ticket.id, status, recommended_action=recommended)
    return ticket.id


async def steps(repo: FakeRepo, tid: uuid.UUID) -> list[str]:
    return [t.step_name for t in await repo.traces(tid)]


async def test_approve_runs_action_then_settles_and_credits_operator(repo: FakeRepo):
    tid = await seed(repo, TicketStatus.AWAITING_APPROVAL, REFUND)
    conn = Connector()
    out = await approve_ticket(repo, conn, tid, operator="sam")  # type: ignore[arg-type]
    assert out.error is None
    assert out.ticket.status == TicketStatus.EXECUTED
    assert conn.comments == ["**[Refund draft]**\n\nhi"]
    assert await steps(repo, tid) == ["execute_action", "operator_approve"]
    assert (await repo.traces(tid))[1].input_data == {"operator": "sam", "edited": False}


async def test_approve_without_action_only_transitions(repo: FakeRepo):
    tid = await seed(repo, TicketStatus.AWAITING_APPROVAL)
    out = await approve_ticket(repo, Connector(), tid, operator="sam")  # type: ignore[arg-type]
    assert out.ticket.status == TicketStatus.EXECUTED
    assert await steps(repo, tid) == ["operator_approve"]


async def test_edited_payload_is_executed_and_persisted(repo: FakeRepo):
    tid = await seed(repo, TicketStatus.AWAITING_APPROVAL, REFUND)
    conn = Connector()
    out = await approve_ticket(
        repo,
        conn,  # type: ignore[arg-type]
        tid,
        operator="sam",
        edited_payload={"body": "edited"},
    )
    assert "edited" in conn.comments[0]
    assert out.ticket.recommended_action["tool_payload"] == {"body": "edited"}  # type: ignore[index]
    assert (await repo.traces(tid))[-1].input_data == {"operator": "sam", "edited": True}


async def test_connector_failure_marks_failed_and_is_not_credited(repo: FakeRepo):
    tid = await seed(repo, TicketStatus.AWAITING_APPROVAL, REFUND)
    out = await approve_ticket(repo, Connector(fail=True), tid, operator="sam")  # type: ignore[arg-type]
    assert out.error == "upstream down"
    assert out.ticket.status == TicketStatus.FAILED
    assert await steps(repo, tid) == ["execute_action"]
    assert (await repo.traces(tid))[0].output_data == {"error": "upstream down"}


async def test_unsupported_action_fails_instead_of_executing(repo: FakeRepo):
    tid = await seed(
        repo,
        TicketStatus.AWAITING_APPROVAL,
        {"recommended_action": "delete_repo", "tool_payload": {}},
    )
    out = await approve_ticket(repo, Connector(), tid, operator="sam")  # type: ignore[arg-type]
    assert out.ticket.status == TicketStatus.FAILED
    assert out.error is not None


@pytest.mark.parametrize(
    "status", [TicketStatus.PENDING, TicketStatus.EXECUTED, TicketStatus.FAILED]
)
async def test_operator_cannot_approve_outside_awaiting(repo: FakeRepo, status: TicketStatus):
    tid = await seed(repo, status, REFUND)
    conn = Connector()
    with pytest.raises(NotApprovable):
        await approve_ticket(repo, conn, tid, operator="sam")  # type: ignore[arg-type]
    assert conn.comments == []
    assert (await repo.get(tid)).status == status  # type: ignore[union-attr]


async def test_unknown_ticket_raises_not_found(repo: FakeRepo):
    with pytest.raises(TicketNotFound):
        await approve_ticket(repo, Connector(), uuid.uuid4(), operator="sam")  # type: ignore[arg-type]


def decision(action: str = "label", payload: dict[str, Any] | None = None) -> TriageDecision:
    return TriageDecision(
        recommended_action=action,
        tool_payload=payload if payload is not None else {"labels": ["bug"]},
        confidence_score=0.93,
        reasoning="clear bug report",
    )


async def test_auto_execute_runs_action_and_persists_decision(repo: FakeRepo):
    tid = await seed(repo, TicketStatus.PENDING)
    conn = Connector()
    out = await auto_execute(repo, conn, tid, decision())  # type: ignore[arg-type]
    assert out.ticket.status == TicketStatus.EXECUTED
    assert out.ticket.confidence_score == 0.93
    assert out.ticket.recommended_action["recommended_action"] == "label"  # type: ignore[index]
    assert conn.labels == [["bug"]]
    traces = await repo.traces(tid)
    assert [t.step_name for t in traces] == ["execute_action"]
    assert traces[0].input_data == {"action": "label", "operator": "agent"}


async def test_auto_execute_failure_keeps_decision_and_marks_failed(repo: FakeRepo):
    tid = await seed(repo, TicketStatus.PENDING)
    out = await auto_execute(repo, Connector(fail=True), tid, decision())  # type: ignore[arg-type]
    assert out.error == "upstream down"
    assert out.ticket.status == TicketStatus.FAILED
    assert out.ticket.recommended_action["recommended_action"] == "label"  # type: ignore[index]


async def test_agent_cannot_auto_execute_a_ticket_awaiting_review(repo: FakeRepo):
    tid = await seed(repo, TicketStatus.AWAITING_APPROVAL, REFUND)
    with pytest.raises(NotApprovable):
        await auto_execute(repo, Connector(), tid, decision())  # type: ignore[arg-type]


async def test_reject_is_audited_and_only_from_awaiting(repo: FakeRepo):
    tid = await seed(repo, TicketStatus.AWAITING_APPROVAL, REFUND)
    updated = await reject_ticket(repo, tid, operator="sam", reason="wrong order")
    assert updated.status == TicketStatus.REJECTED
    assert (await repo.traces(tid))[0].input_data == {"operator": "sam", "reason": "wrong order"}

    pending = await seed(repo, TicketStatus.PENDING)
    with pytest.raises(NotApprovable):
        await reject_ticket(repo, pending, operator="sam", reason="")


class SlowConnector(Connector):
    """Yields to the loop mid-action, the window a racing second request would slip through."""

    async def post_comment(self, repo: str, number: int, body: str) -> None:
        await asyncio.sleep(0.01)
        await super().post_comment(repo, number, body)


async def test_double_approve_runs_the_action_once(repo: FakeRepo):
    tid = await seed(repo, TicketStatus.AWAITING_APPROVAL, REFUND)
    conn = SlowConnector()
    results = await asyncio.gather(
        approve_ticket(repo, conn, tid, operator="a"),  # type: ignore[arg-type]
        approve_ticket(repo, conn, tid, operator="b"),  # type: ignore[arg-type]
        return_exceptions=True,
    )
    assert len(conn.comments) == 1
    assert sum(isinstance(r, NotApprovable) for r in results) == 1
    assert (await repo.get(tid)).status == TicketStatus.EXECUTED  # type: ignore[union-attr]


async def test_approve_racing_reject_leaves_one_consistent_outcome(repo: FakeRepo):
    tid = await seed(repo, TicketStatus.AWAITING_APPROVAL, REFUND)
    conn = SlowConnector()
    results = await asyncio.gather(
        approve_ticket(repo, conn, tid, operator="a"),  # type: ignore[arg-type]
        reject_ticket(repo, tid, operator="b", reason="no"),
        return_exceptions=True,
    )
    assert sum(isinstance(r, NotApprovable) for r in results) == 1
    final = (await repo.get(tid)).status  # type: ignore[union-attr]
    # The action ran iff the approval won; a rejected ticket never posts.
    assert (final == TicketStatus.EXECUTED) == (len(conn.comments) == 1)
    assert final in (TicketStatus.EXECUTED, TicketStatus.REJECTED)


async def test_a_malformed_ticket_payload_fails_the_ticket_instead_of_raising(repo: FakeRepo):
    ticket = await repo.create_if_new(
        external_event_id=uuid.uuid4().hex, provider="github", raw_payload={}
    )
    assert ticket is not None
    await repo.set_status(ticket.id, TicketStatus.AWAITING_APPROVAL, recommended_action=REFUND)
    out = await approve_ticket(repo, Connector(), ticket.id, operator="sam")  # type: ignore[arg-type]
    assert out.ticket.status == TicketStatus.FAILED
    assert out.error
