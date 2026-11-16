from fastapi import APIRouter, Depends

from app.api.deps import get_connector
from app.connectors.github import GitHubConnector
from app.db import db_ready
from app.schemas import HealthOut

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthOut)
async def health(connector: GitHubConnector = Depends(get_connector)) -> HealthOut:
    database = await db_ready()
    connector_ok = await connector.ping()
    return HealthOut(
        status="ok" if database and connector_ok else "degraded",
        database=database,
        connector=connector_ok,
    )
