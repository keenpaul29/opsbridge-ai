import uuid

import pytest
from fastapi.testclient import TestClient

from app.models import TicketStatus
from tests.conftest import FakeRepo


async def seed(repo: FakeRepo, status: TicketStatus) -> uuid.UUID:
    ticket = await repo.create_if_new(
        external_event_id=uuid.uuid4().hex, provider="github", raw_payload={}
    )
    assert ticket is not None
    await repo.set_status(ticket.id, status)
    return ticket.id


async def test_approve_moves_awaiting_ticket_to_executed(client: TestClient, repo: FakeRepo):
    tid = await seed(repo, TicketStatus.AWAITING_APPROVAL)
    resp = client.post(f"/tickets/{tid}/approve", json={})
    assert resp.status_code == 200
    assert resp.json()["status"] == "EXECUTED"
    assert [t.step_name for t in await repo.traces(tid)] == ["operator_approve"]


async def test_reject_is_audited(client: TestClient, repo: FakeRepo):
    tid = await seed(repo, TicketStatus.AWAITING_APPROVAL)
    resp = client.post(f"/tickets/{tid}/reject", json={"reason": "wrong order"})
    assert resp.json()["status"] == "REJECTED"
    traces = await repo.traces(tid)
    assert traces[0].input_data == {"operator": "operator", "reason": "wrong order"}


@pytest.mark.parametrize(
    "status", [TicketStatus.PENDING, TicketStatus.EXECUTED, TicketStatus.FAILED]
)
async def test_approve_from_wrong_state_conflicts(
    client: TestClient, repo: FakeRepo, status: TicketStatus
):
    tid = await seed(repo, status)
    assert client.post(f"/tickets/{tid}/approve", json={}).status_code == 409


async def test_reject_from_pending_conflicts(client: TestClient, repo: FakeRepo):
    tid = await seed(repo, TicketStatus.PENDING)
    assert client.post(f"/tickets/{tid}/reject", json={}).status_code == 409


def test_unknown_ticket_404(client: TestClient):
    assert client.get(f"/tickets/{uuid.uuid4()}").status_code == 404


async def test_list_filters_by_status(client: TestClient, repo: FakeRepo):
    await seed(repo, TicketStatus.AWAITING_APPROVAL)
    await seed(repo, TicketStatus.EXECUTED)
    resp = client.get("/tickets", params={"status": "AWAITING_APPROVAL"})
    assert [t["status"] for t in resp.json()] == ["AWAITING_APPROVAL"]


def test_health_reports_connector(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    async def fake_db() -> bool:
        return True

    monkeypatch.setattr("app.api.health.db_ready", fake_db)
    assert client.get("/health").json() == {"status": "ok", "database": True, "connector": True}


class RecordingConnector:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.comments: list[str] = []

    async def post_comment(self, repo: str, number: int, body: str) -> None:
        from app.connectors.github import ConnectorError

        if self.fail:
            raise ConnectorError("upstream down")
        self.comments.append(body)


async def _seed_refund(repo: FakeRepo) -> uuid.UUID:
    ticket = await repo.create_if_new(
        external_event_id=uuid.uuid4().hex,
        provider="github",
        raw_payload={"repository": {"full_name": "o/r"}, "issue": {"number": 3}},
    )
    assert ticket is not None
    await repo.set_status(
        ticket.id,
        TicketStatus.AWAITING_APPROVAL,
        recommended_action={"recommended_action": "refund_draft", "tool_payload": {"body": "hi"}},
    )
    return ticket.id


async def test_approve_executes_action_via_connector(app, client: TestClient, repo: FakeRepo):
    from app.api.deps import get_connector

    conn = RecordingConnector()
    app.dependency_overrides[get_connector] = lambda: conn
    tid = await _seed_refund(repo)
    resp = client.post(f"/tickets/{tid}/approve", json={"edited_payload": {"body": "edited"}})
    assert resp.status_code == 200
    assert resp.json()["status"] == "EXECUTED"
    assert "edited" in conn.comments[0]


async def test_approve_marks_failed_when_connector_errors(app, client: TestClient, repo: FakeRepo):
    from app.api.deps import get_connector

    app.dependency_overrides[get_connector] = lambda: RecordingConnector(fail=True)
    tid = await _seed_refund(repo)
    resp = client.post(f"/tickets/{tid}/approve", json={})
    assert resp.status_code == 502
    assert (await repo.get(tid)).status == TicketStatus.FAILED  # type: ignore[union-attr]


def _with_token(app, token: str = "s3cret"):  # type: ignore[no-untyped-def]
    from app.config import Settings, get_settings

    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, webhook_secret="test-secret", operator_token=token
    )


@pytest.mark.parametrize("action", ["approve", "reject"])
@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer wrong"},
        {"Authorization": "Basic s3cret"},
        {"Authorization": "s3cret"},
    ],
)
async def test_writes_need_the_operator_token(app, client, repo, action, headers):  # type: ignore[no-untyped-def]
    _with_token(app)
    tid = await seed(repo, TicketStatus.AWAITING_APPROVAL)
    resp = client.post(f"/tickets/{tid}/{action}", json={}, headers=headers)
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == "Bearer"
    assert (await repo.get(tid)).status == TicketStatus.AWAITING_APPROVAL  # type: ignore[union-attr]


async def test_writes_succeed_with_the_operator_token(app, client, repo):  # type: ignore[no-untyped-def]
    _with_token(app)
    tid = await seed(repo, TicketStatus.AWAITING_APPROVAL)
    resp = client.post(
        f"/tickets/{tid}/approve", json={}, headers={"Authorization": "Bearer s3cret"}
    )
    assert resp.status_code == 200


async def test_reads_stay_public_when_a_token_is_configured(app, client, repo):  # type: ignore[no-untyped-def]
    _with_token(app)
    tid = await seed(repo, TicketStatus.AWAITING_APPROVAL)
    assert client.get("/tickets").status_code == 200
    assert client.get(f"/tickets/{tid}").status_code == 200
    assert client.get(f"/tickets/{tid}/traces").status_code == 200


@pytest.mark.parametrize("action", ["approve", "reject"])
def test_unknown_ticket_on_a_write_is_404_not_500(client: TestClient, action: str):
    assert client.post(f"/tickets/{uuid.uuid4()}/{action}", json={}).status_code == 404
