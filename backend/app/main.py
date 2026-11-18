import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import evals, health, tickets, webhooks
from app.api.errors import register_error_handlers
from app.config import get_settings
from app.connectors.github import GitHubConnector
from app.db import SessionLocal, init_db
from app.logging import configure_logging, request_context_middleware
from app.rag.embeddings import GeminiEmbedder, make_embedder
from app.rag.store import ingest_directory

log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    settings = get_settings()
    if not settings.operator_token:
        log.warning("OPERATOR_TOKEN not set: approve/reject are unauthenticated (dev only)")
    app.state.connector = GitHubConnector(settings)
    app.state.embedder = embedder = make_embedder(settings)
    await init_db()
    if isinstance(embedder, GeminiEmbedder):
        # Never ingest with the hash stand-in: it would overwrite real vectors with noise.
        try:
            async with SessionLocal() as session:
                counts = await ingest_directory(session, embedder)
            log.info("policies ingested", extra={"status": str(counts)})
        except Exception:  # noqa: BLE001 - serve with the existing index rather than not start
            log.exception("policy ingestion failed; serving with the existing index")
    yield
    await app.state.connector.aclose()
    if isinstance(embedder, GeminiEmbedder):
        await embedder.aclose()


def create_app() -> FastAPI:
    app = FastAPI(title="OpsBridge AI", version="0.1.0", lifespan=lifespan)
    app.middleware("http")(request_context_middleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in get_settings().cors_origins.split(",") if o.strip()],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_error_handlers(app)
    app.include_router(health.router)
    app.include_router(webhooks.router)
    app.include_router(tickets.router)
    app.include_router(evals.router)
    return app


app = create_app()
