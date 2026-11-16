# OpsBridge AI

Autonomous support/order-triage agent: GitHub Issues webhooks → FastAPI + LangGraph agent →
Postgres/pgvector policy retrieval → human-in-the-loop approvals in a Next.js operator console.
Full requirements: [opsbridge_ai_prd.md](opsbridge_ai_prd.md).

```
backend/    FastAPI, LangGraph agent, GitHub connector, pytest + golden evals
frontend/   Next.js (App Router) operator console, types generated from the OpenAPI schema
docker-compose.yml   db (pgvector/pg16) + backend + frontend
.github/workflows/ci.yml   lint, types, tests, eval gate
```

## Run locally

```bash
docker compose up db            # Postgres 16 + pgvector

cd backend
python -m venv .venv && .venv/Scripts/activate    # source .venv/bin/activate on macOS/Linux
pip install -e ".[dev]"
cp .env.example .env
uvicorn app.main:app --reload   # http://localhost:8000/docs

cd frontend
npm install
npm run dev                     # http://localhost:3000
```

Point a GitHub repo webhook (content type `application/json`, "Issues" events, secret =
`WEBHOOK_SECRET`) at `POST /webhooks/github`.

## LLM

The agent's `classify` and `propose` steps call an OpenAI-compatible chat API, Groq's free tier by
default (`openai/gpt-oss-120b`, strict JSON-schema output). Set `GROQ_API_KEY` in `backend/.env`
to enable it; with no key the offline `HeuristicLLM` runs, which is what tests and CI use.
`LLM_BASE_URL` and `LLM_MODEL` point it at another OpenAI-compatible provider or model.

Groq's free tier is about 30 requests and 8,000 tokens per minute, so prompts are truncated and
429s are retried with backoff. If the model output is invalid or the call keeps failing, the
decision degrades to confidence 0 and the ticket goes to a human.

## Tests

```bash
cd backend
pytest -m "not eval"   # unit/API tests (no database needed)
pytest -m eval         # golden-case gate (fails below EVAL_PASS_THRESHOLD)
```

## Regenerating frontend types

After changing backend schemas:

```bash
cd backend && python -m scripts.export_openapi > ../frontend/openapi.json
cd ../frontend && npm run gen:types
```

## What is scaffolded vs. still to build

Working: HMAC-verified idempotent webhook ingestion with dead-lettering, retry/backoff/circuit
breaker connector, ticket state machine + guardrail routing, approve/reject with audit traces,
console pages, CI.

Stubbed (marked `TODO` in code): LLM-backed `classify`/`propose` nodes, real embeddings and policy
ingestion wiring in `agent/runner.py`, executing the approved action through the connector,
Alembic migrations (tables are created at startup), writing `eval_runs` rows from the eval suite,
and the remaining ~20 golden cases (6 seeded of the 25–30 target).
