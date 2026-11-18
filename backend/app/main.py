from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import evals, health, tickets, webhooks
from app.api.errors import register_error_handlers
from app.config import get_settings
from app.connectors.github import GitHubConnector
from app.db import init_db
from app.logging import configure_logging, request_context_middleware


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    settings = get_settings()
    app.state.connector = GitHubConnector(settings)
    await init_db()
    yield
    await app.state.connector.aclose()


def create_app() -> FastAPI:
    app = FastAPI(title="OpsBridge AI", version="0.1.0", lifespan=lifespan)
    app.middleware("http")(request_context_middleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
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
