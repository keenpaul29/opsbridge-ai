import json

from fastapi.testclient import TestClient

from tests.conftest import FakeRepo, sign

VALID = {
    "action": "opened",
    "issue": {"number": 7, "title": "Refund please", "body": "order 123", "labels": []},
    "repository": {"full_name": "acme/shop"},
}


def post(client: TestClient, payload: object, delivery: str = "d-1", signature: str | None = None):
    body = json.dumps(payload).encode()
    headers = {
        "x-github-delivery": delivery,
        "x-hub-signature-256": signature if signature is not None else sign(body),
        "content-type": "application/json",
    }
    return client.post("/webhooks/github", content=body, headers=headers)


def test_valid_webhook_is_accepted_and_scheduled(client: TestClient, repo: FakeRepo, scheduled):
    resp = post(client, VALID)
    assert resp.status_code == 202
    assert resp.json()["status"] == "accepted"
    assert len(repo.tickets) == 1
    assert scheduled == [next(iter(repo.tickets))]


def test_invalid_signature_returns_401(client: TestClient, repo: FakeRepo):
    resp = post(client, VALID, signature="sha256=deadbeef")
    assert resp.status_code == 401
    assert not repo.tickets


def test_missing_signature_returns_401(client: TestClient):
    resp = client.post("/webhooks/github", json=VALID, headers={"x-github-delivery": "d-x"})
    assert resp.status_code == 401


def test_duplicate_delivery_does_not_trigger_second_run(
    client: TestClient, repo: FakeRepo, scheduled
):
    first = post(client, VALID, delivery="same")
    second = post(client, VALID, delivery="same")
    assert first.json()["status"] == "accepted"
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate"
    assert len(repo.tickets) == 1
    assert len(scheduled) == 1


def test_malformed_payload_is_dead_lettered_not_crashed(
    client: TestClient, repo: FakeRepo, scheduled
):
    resp = post(client, {"action": "opened", "issue": "not-an-object"})
    assert resp.status_code == 202
    assert resp.json()["status"] == "dead_lettered"
    assert not repo.tickets and not scheduled


def test_non_json_body_is_dead_lettered(client: TestClient):
    body = b"<<not json>>"
    resp = client.post(
        "/webhooks/github",
        content=body,
        headers={"x-github-delivery": "d-2", "x-hub-signature-256": sign(body)},
    )
    assert resp.json()["status"] == "dead_lettered"


def test_unknown_provider_404(client: TestClient):
    assert client.post("/webhooks/nope", json={}).status_code == 404
