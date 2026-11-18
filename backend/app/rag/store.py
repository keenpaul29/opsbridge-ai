"""Policy retrieval over pgvector (FR-2).

Embedding is injected (see rag/embeddings.py). Retrieval returns text, source doc and similarity so
every recommendation can cite the clause it used.
"""

import logging
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PolicyChunk
from app.rag.embeddings import Embedder
from app.schemas import PolicyCitation

log = logging.getLogger("app.rag")

POLICY_DIR = Path(__file__).resolve().parents[2] / "policies"


def chunk_markdown(text: str) -> list[str]:
    """Split on blank lines; each paragraph/clause becomes one chunk."""
    return [c.strip() for c in text.split("\n\n") if c.strip()]


async def ingest_document(
    session: AsyncSession, doc_name: str, text: str, embedder: Embedder
) -> int:
    chunks = chunk_markdown(text)
    # Embed before touching the table so an embedding failure never leaves a document half-replaced.
    vectors = await embedder.embed_documents([(doc_name, chunk) for chunk in chunks])
    # Replace-by-document keeps re-ingestion idempotent.
    await session.execute(delete(PolicyChunk).where(PolicyChunk.doc_name == doc_name))
    for i, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True)):
        session.add(
            PolicyChunk(
                doc_name=doc_name,
                content=chunk,
                embedding=vector,
                chunk_metadata={"index": i},
            )
        )
    await session.commit()
    return len(chunks)


async def ingest_directory(
    session: AsyncSession, embedder: Embedder, directory: Path = POLICY_DIR
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in sorted(directory.glob("*.md")):
        counts[path.name] = await ingest_document(
            session, path.name, path.read_text(encoding="utf-8"), embedder
        )
    return counts


async def retrieve(
    session: AsyncSession, query: str, embedder: Embedder, k: int = 4
) -> list[PolicyCitation]:
    distance = PolicyChunk.embedding.cosine_distance(await embedder.embed_query(query))
    stmt = select(PolicyChunk, distance.label("distance")).order_by(distance).limit(k)
    rows = (await session.execute(stmt)).all()
    return [
        PolicyCitation(
            doc_name=chunk.doc_name, chunk_id=chunk.id, text=chunk.content, score=1.0 - float(dist)
        )
        for chunk, dist in rows
    ]
