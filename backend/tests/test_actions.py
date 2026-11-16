from typing import Any

import pytest

from app.agent.actions import UnsupportedAction, execute_action

EVENT = {"repository": {"full_name": "o/r"}, "issue": {"number": 7}}


class Recorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    async def add_labels(self, repo: str, number: int, labels: list[str]) -> None:
        self.calls.append(("labels", (repo, number, labels)))

    async def post_comment(self, repo: str, number: int, body: str) -> None:
        self.calls.append(("comment", (repo, number, body)))


async def test_label_calls_add_labels():
    c = Recorder()
    await execute_action(c, EVENT, "label", {"labels": ["bug"]})  # type: ignore[arg-type]
    assert c.calls == [("labels", ("o/r", 7, ["bug"]))]


async def test_refund_draft_posts_marked_comment():
    c = Recorder()
    await execute_action(c, EVENT, "refund_draft", {"body": "Refund $10"})  # type: ignore[arg-type]
    assert c.calls[0][0] == "comment"
    assert "Refund draft" in c.calls[0][1][2]


@pytest.mark.parametrize(
    ("action", "payload"),
    [("label", {}), ("reply_draft", {"body": " "}), ("delete_repo", {"x": 1})],
)
async def test_invalid_actions_raise(action: str, payload: dict[str, Any]):
    with pytest.raises(UnsupportedAction):
        await execute_action(Recorder(), EVENT, action, payload)  # type: ignore[arg-type]
