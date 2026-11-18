"""Run the agent eval suite and record the result as an `eval_runs` row (shown in the console).

python -m scripts.record_eval_run            # write to DATABASE_URL
python -m scripts.record_eval_run --dry-run  # score and print only
"""

import asyncio
import os
import subprocess
import sys

from app.db import SessionLocal, init_db
from app.repository import SqlTicketRepository
from tests.evals.harness import run_suite, save_report


def git_sha() -> str:
    if sha := os.environ.get("GITHUB_SHA"):
        return sha[:12]
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"], capture_output=True, text=True, check=True
        )
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


async def main(dry_run: bool) -> None:
    report = await run_suite()
    print(report.summary())
    if dry_run:
        return
    await init_db()
    async with SessionLocal() as session:
        run = await save_report(SqlTicketRepository(session), report, git_sha())
    print(f"recorded eval run {run.id} @ {run.git_sha}")


if __name__ == "__main__":
    asyncio.run(main("--dry-run" in sys.argv))
