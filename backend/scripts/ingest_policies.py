"""Ingest backend/policies/*.md into policy_chunks. Run: python -m scripts.ingest_policies

Needs GEMINI_API_KEY; the offline hash embedder would store meaningless vectors, so it is refused.
"""

import asyncio
import sys

from app.config import get_settings
from app.db import SessionLocal, init_db
from app.rag.embeddings import GeminiEmbedder
from app.rag.store import ingest_directory


async def main() -> int:
    settings = get_settings()
    if not settings.gemini_api_key:
        print("GEMINI_API_KEY is not set; refusing to ingest hash vectors.", file=sys.stderr)
        return 1
    embedder = GeminiEmbedder(settings)
    try:
        await init_db()
        async with SessionLocal() as session:
            for name, n in (await ingest_directory(session, embedder)).items():
                print(f"{name}: {n} chunks")
    finally:
        await embedder.aclose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
