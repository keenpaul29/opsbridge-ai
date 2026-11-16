"""Policy retrieval over pgvector (FR-2).

`embed` is a placeholder: swap in a real embedding model. Retrieval returns text, source doc and
similarity so every recommendation can cite the clause it used.
"""

import hashlib

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import PolicyChunk
from app.schemas import PolicyCitation


def embed(text: str) -> list[float]:
    """Deterministic hash-based stand-in so the pipeline runs without an embedding API."""
    dim = get_settings().embedding_dim
    digest = hashlib.sha256(text.encode()).digest()
    return [digest[i % len(digest)] / 255.0 for i in range(dim)]


def chunk_markdown(text: str) -> list[str]:
    """Split on blank lines; each paragraph/clause becomes one chunk."""
    return [c.strip() for c in text.split("\n\n") if c.strip()]


async def ingest_document(session: AsyncSession, doc_name: str, text: str) -> int:
    chunks = chunk_markdown(text)
    # Replace-by-document keeps re-ingestion idempotent.
    await session.execute(delete(PolicyChunk).where(PolicyChunk.doc_name == doc_name))
    for i, chunk in enumerate(chunks):
        session.add(
            PolicyChunk(
                doc_name=doc_name,
                content=chunk,
                embedding=embed(chunk),
                chunk_metadata={"index": i},
            )
        )
    await session.commit()
    return len(chunks)


async def retrieve(session: AsyncSession, query: str, k: int = 4) -> list[PolicyCitation]:
    distance = PolicyChunk.embedding.cosine_distance(embed(query))
    stmt = select(PolicyChunk, distance.label("distance")).order_by(distance).limit(k)
    rows = (await session.execute(stmt)).all()
    return [
        PolicyCitation(
            doc_name=chunk.doc_name, chunk_id=chunk.id, text=chunk.content, score=1.0 - float(dist)
        )
        for chunk, dist in rows
    ]
