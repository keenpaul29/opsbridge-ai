"""Executes an approved triage action through the external connector."""

from typing import Any

from app.connectors.github import ConnectorError, GitHubConnector


class UnsupportedAction(ConnectorError):
    pass


def _target(event: dict[str, Any]) -> tuple[str, int]:
    return event["repository"]["full_name"], event["issue"]["number"]


async def execute_action(
    connector: GitHubConnector,
    event: dict[str, Any],
    action: str,
    payload: dict[str, Any],
) -> None:
    repo, number = _target(event)
    if action in ("label", "route"):
        labels = [str(x) for x in payload.get("labels", [])]
        if not labels:
            raise UnsupportedAction(f"{action} requires payload.labels")
        await connector.add_labels(repo, number, labels)
    elif action in ("reply_draft", "refund_draft"):
        body = str(payload.get("body", "")).strip()
        if not body:
            raise UnsupportedAction(f"{action} requires payload.body")
        prefix = "**[Refund draft]**\n\n" if action == "refund_draft" else ""
        await connector.post_comment(repo, number, prefix + body)
    else:
        raise UnsupportedAction(f"unknown action {action!r}")
