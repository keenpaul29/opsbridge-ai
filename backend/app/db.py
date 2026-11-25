from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models import Base

engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    """Create extension + tables. Replace with Alembic migrations before production."""
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)


def embedding_dim_error(actual: int | None, expected: int) -> str | None:
    """Message when the stored vector column width differs from EMBEDDING_DIM, else None."""
    if actual is None or actual == expected:
        return None
    return (
        f"policy_chunks.embedding is vector({actual}) but EMBEDDING_DIM={expected}: "
        "drop the table (or the pgdata volume) and restart, or migrate it"
    )


async def check_embedding_dim(expected: int) -> None:
    """Fail loudly at startup: create_all never alters an existing column, so a changed
    EMBEDDING_DIM would otherwise break every retrieval and ingestion at runtime."""
    async with engine.connect() as conn:
        actual = (
            await conn.execute(
                text(
                    "SELECT atttypmod FROM pg_attribute "
                    "WHERE attrelid = 'policy_chunks'::regclass AND attname = 'embedding'"
                )
            )
        ).scalar()
    if message := embedding_dim_error(actual, expected):
        raise RuntimeError(message)


async def db_ready() -> bool:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
