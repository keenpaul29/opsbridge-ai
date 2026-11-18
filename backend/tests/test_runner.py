"""run_triage wiring that the eval harness cannot see (it forces the similarity floor to 0)."""

import uuid
from typing import Any

import pytest

from app.agent.runner import run_triage
from app.config import Settings
from app.connectors.github import IssueContext
from app.models import TicketStatus
from app.schemas import PolicyCitation
from tests.conftest import FakeRepo

EVENT = {
    "action": "opened",
    "repository": {"full_name": "o/r"},
    "issue": {"number": 4, "title": "Bug: checkout fails", "body": "steps: tap pay"},
}


class Connector:
    def __init__(self) -> None:
        self.labels: list[list[str]] = []

    async def get_issue(self, repo: str, number: int) -> IssueContext:
        return IssueContext(number=number, title="Bug: checkout fails", state="open")

    async def add_labels(self, repo: str, number: int, labels: list[str]) -> None:
        self.labels.append(labels)


async def _retriever(_query: str) -> list[PolicyCitation]:
    return [PolicyCitation(doc_name="bugs.md", text="label bugs", score=0.3)]


async def _run(repo: FakeRepo, floor: float) -> uuid.UUID:
    ticket = await repo.create_if_new(
        external_event_id=uuid.uuid4().hex, provider="github", raw_payload=EVENT
    )
    assert ticket is not None
    await run_triage(
        ticket.id,
        repo,
        Connector(),  # type: ignore[arg-type]
        Settings(_env_file=None, min_policy_score=floor),
        retriever=_retriever,
    )
    return ticket.id


@pytest.mark.parametrize(
    ("floor", "status", "cited"),
    [
        (0.5, TicketStatus.AWAITING_APPROVAL, []),  # 0.3 is below the floor: no policy, human
        (0.2, TicketStatus.EXECUTED, ["bugs.md"]),  # 0.3 clears the floor: auto-label
    ],
)
async def test_runner_applies_the_configured_similarity_floor(
    repo: FakeRepo, floor: float, status: TicketStatus, cited: list[str]
):
    tid = await _run(repo, floor)
    ticket = await repo.get(tid)
    assert ticket is not None and ticket.status == status
    decision: dict[str, Any] = ticket.recommended_action or {}
    assert [c["doc_name"] for c in decision["policy_citations"]] == cited


class _BrokenRetrieval(Exception):
    pass


async def test_retrieval_failure_sends_the_ticket_to_a_human_instead_of_stranding_it(
    repo: FakeRepo,
):
    async def failing(_query: str) -> list[PolicyCitation]:
        raise _BrokenRetrieval("embedding API down")

    ticket = await repo.create_if_new(
        external_event_id=uuid.uuid4().hex, provider="github", raw_payload=EVENT
    )
    assert ticket is not None
    await run_triage(
        ticket.id,
        repo,
        Connector(),  # type: ignore[arg-type]
        Settings(_env_file=None, min_policy_score=0.5),
        retriever=failing,
    )
    done = await repo.get(ticket.id)
    assert done is not None and done.status == TicketStatus.AWAITING_APPROVAL  # not PENDING
    retrieve = next(t for t in await repo.traces(ticket.id) if t.step_name == "retrieve_policy")
    assert retrieve.output_data["retrieval_error"] == "_BrokenRetrieval"  # type: ignore[index]


async def test_an_unexpected_crash_marks_the_ticket_failed_never_pending(repo: FakeRepo):
    class CrashingLLM:
        async def classify(self, title: str, body: str) -> Any:
            raise RuntimeError("boom")

    ticket = await repo.create_if_new(
        external_event_id=uuid.uuid4().hex, provider="github", raw_payload=EVENT
    )
    assert ticket is not None
    await run_triage(
        ticket.id,
        repo,
        Connector(),  # type: ignore[arg-type]
        Settings(_env_file=None),
        retriever=_retriever,
        llm=CrashingLLM(),  # type: ignore[arg-type]
    )
    done = await repo.get(ticket.id)
    assert done is not None and done.status == TicketStatus.FAILED
