"""Runs the triage graph for a ticket, persists traces, applies guardrail routing."""

import logging
import uuid
from typing import Any

from app.agent.decisions import auto_execute
from app.agent.graph import Retriever, build_graph
from app.agent.llm import LLMClient, make_llm
from app.config import Settings
from app.connectors.github import ConnectorError, GitHubConnector
from app.models import TicketStatus
from app.repository import TicketRepository
from app.schemas import PolicyCitation
from app.state_machine import route_decision

log = logging.getLogger("app.agent")


async def _no_policies(_query: str) -> list[PolicyCitation]:
    return []


async def run_triage(
    ticket_id: uuid.UUID,
    repo: TicketRepository,
    connector: GitHubConnector,
    settings: Settings,
    retriever: Retriever | None = None,
    llm: LLMClient | None = None,
) -> None:
    ticket = await repo.get(ticket_id)
    if ticket is None:
        return

    async def fetch_context(event: dict[str, Any]) -> dict[str, Any]:
        issue = event.get("issue", {})
        full_name = event.get("repository", {}).get("full_name", "")
        live = await connector.get_issue(full_name, issue["number"])
        return live.model_dump()

    graph = build_graph(
        retriever or _no_policies,
        fetch_context,
        llm or make_llm(settings),
        min_policy_score=settings.min_policy_score,
    )
    try:
        result = await graph.ainvoke({"event": ticket.raw_payload, "trace": []})
    except ConnectorError:
        log.exception("triage failed", extra={"ticket_id": str(ticket_id), "status": "FAILED"})
        await repo.set_status(ticket_id, TicketStatus.FAILED)
        return
    except Exception:  # noqa: BLE001 - a ticket must never be left PENDING with no trace
        log.exception("triage crashed", extra={"ticket_id": str(ticket_id), "status": "FAILED"})
        await repo.set_status(ticket_id, TicketStatus.FAILED)
        return

    citations = [c.model_dump(mode="json") for c in result.get("policies", [])]
    for entry in result["trace"]:
        await repo.add_trace(
            ticket_id,
            entry["step"],
            output_data={k: v for k, v in entry.items() if k not in ("step", "latency_ms")},
            citations=citations if entry["step"] == "retrieve_policy" else None,
            latency_ms=entry["latency_ms"],
        )

    decision = result["decision"]
    status = route_decision(decision, settings.confidence_threshold)
    if status == TicketStatus.EXECUTED:
        # Auto-approved: auto_execute persists the decision and a FAILED status if the action
        # fails, so a failed call never reads as success.
        outcome = await auto_execute(repo, connector, ticket_id, decision)
        status = outcome.ticket.status
    else:
        await repo.set_status(
            ticket_id,
            status,
            recommended_action=decision.model_dump(mode="json"),
            confidence_score=decision.confidence_score,
        )
    log.info("triage complete", extra={"ticket_id": str(ticket_id), "status": status.value})
