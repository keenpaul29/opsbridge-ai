"""Record the live model's answers for the golden cases so CI can replay them without a key.

    GROQ_API_KEY=... python -m scripts.record_eval_llm

Writes tests/evals/recorded_llm.json. Cases marked `needs_llm` only run once recorded. Re-record
after changing prompts or the model, review the diff, and commit it.
"""

import asyncio
import json
import sys

from app.agent.llm import OpenAICompatLLM
from app.config import get_settings
from tests.evals.harness import RECORDED_PATH, record_llm


async def main() -> int:
    settings = get_settings()
    if not settings.groq_api_key:
        print("GROQ_API_KEY is not set; nothing recorded.", file=sys.stderr)
        return 1
    recorded = await record_llm(OpenAICompatLLM(settings))
    RECORDED_PATH.write_text(
        json.dumps(recorded, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"recorded {len(recorded)} cases to {RECORDED_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
