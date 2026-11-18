import hmac
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Depends, Header, HTTPException, Request

from app.agent.runner import run_triage
from app.config import Settings, get_settings
from app.connectors.github import GitHubConnector
from app.db import SessionLocal
from app.rag.embeddings import Embedder
from app.rag.store import retrieve
from app.repository import SqlTicketRepository
from app.schemas import PolicyCitation

TriageScheduler = Callable[[uuid.UUID], Awaitable[None]]


def get_connector(request: Request) -> GitHubConnector:
    connector: GitHubConnector = request.app.state.connector
    return connector


def get_triage_scheduler(request: Request) -> TriageScheduler:
    """Returns a coroutine function run as a background task.

    It opens its own DB session: the request-scoped session is closed by the time background
    tasks run. Tests override this dependency with a no-op.
    """
    connector: GitHubConnector = request.app.state.connector
    embedder: Embedder = request.app.state.embedder
    settings: Settings = get_settings()

    async def _run(ticket_id: uuid.UUID) -> None:
        async with SessionLocal() as session:

            async def retriever(query: str) -> list[PolicyCitation]:
                return await retrieve(session, query, embedder)

            await run_triage(
                ticket_id,
                SqlTicketRepository(session),
                connector,
                settings,
                retriever=retriever,
            )

    return _run


def require_operator(
    settings: Settings = Depends(get_settings),
    authorization: str | None = Header(default=None),
) -> None:
    """Gate for state-changing console endpoints; a no-op when no operator token is configured."""
    if not settings.operator_token:
        return
    scheme, _, supplied = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(
        supplied.encode(), settings.operator_token.encode()
    ):
        raise HTTPException(
            status_code=401,
            detail="operator token required",
            headers={"WWW-Authenticate": "Bearer"},
        )
