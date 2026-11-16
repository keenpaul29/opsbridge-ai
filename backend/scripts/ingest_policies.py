"""Ingest backend/policies/*.md into policy_chunks. Run: python -m scripts.ingest_policies"""

import asyncio
from pathlib import Path

from app.db import SessionLocal, init_db
from app.rag.store import ingest_document

POLICY_DIR = Path(__file__).resolve().parent.parent / "policies"


async def main() -> None:
    await init_db()
    async with SessionLocal() as session:
        for path in sorted(POLICY_DIR.glob("*.md")):
            n = await ingest_document(session, path.name, path.read_text(encoding="utf-8"))
            print(f"{path.name}: {n} chunks")


if __name__ == "__main__":
    asyncio.run(main())
