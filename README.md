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

To try it end to end without a database, run `python -m scripts.groq_smoke` from `backend/`. It
sends four signed sample webhooks through the real app and model, with the database, GitHub and
policy retrieval stubbed, and prints how each ticket was routed. It spends free-tier quota.

Groq's free tier is about 30 requests and 8,000 tokens per minute, so prompts are truncated and
429s are retried with backoff. If the model output is invalid or the call keeps failing, the
decision degrades to confidence 0 and the ticket goes to a human.

## Tests

```bash
cd backend
pytest -m "not eval"   # unit/API tests (no database needed)
pytest -m eval         # golden-case gate (fails below EVAL_PASS_THRESHOLD)
python -m scripts.record_eval_run --dry-run   # score the suite; drop --dry-run to write an
                                              # `eval_runs` row to DATABASE_URL (console eval page)
```

The eval suite (`tests/evals/`) runs the real triage pipeline over 20 end-to-end cases
(`agent_cases.json`: happy path, ambiguous, policy violation, prompt injection, upstream failure)
plus 6 guardrail boundary cases, and scores pass rate, tool-selection accuracy, policy
groundedness and p95 latency. Guardrail compliance (a case a human must review is never
auto-executed) is a hard zero-violation gate. Caveats: retrieval is a lexical stand-in for
pgvector, and cases without a recorded model answer run on the offline `HeuristicLLM`, so they
test the pipeline and guardrails, not model judgement. `needs_llm` cases are skipped until
`GROQ_API_KEY=... python -m scripts.record_eval_llm` records the model's answers into
`tests/evals/recorded_llm.json`, which CI then replays without a key.

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

Policy retrieval embeds with Gemini (`gemini-embedding-2`, 768 dims) and ingests `policies/*.md`
at startup when `GEMINI_API_KEY` is set (get one at https://aistudio.google.com/apikey); without a
key it falls back to an offline hash embedder whose retrieval is meaningless. Changing
`EMBEDDING_DIM` needs a table migration; for an existing local database drop the `policy_chunks`
table (or the `pgdata` volume) once, since tables are only created, never altered; the app now refuses to start on a mismatched
column width and says so.

Still to build: Alembic migrations (tables are created at startup), a public deployment, recording live model answers for the `needs_llm` eval cases, and the
case study.

Retrieved policies scoring below `MIN_POLICY_SCORE` (default 0.5) count as absent: they are not
cited and cannot lift confidence, so a weak match cannot trigger an auto-approval. The default is
a placeholder until it is calibrated against real embeddings.

Approve and reject require `Authorization: Bearer <OPERATOR_TOKEN>`; reads (queue, traces, evals)
stay public so the console can be shown read-only. Set `OPERATOR_TOKEN` on any deployed instance
(empty disables auth, for local development only; with `ENVIRONMENT=production` an empty token
refuses to start and writes fail closed) and `CORS_ORIGINS` to the console's origin. The
console asks for the token and keeps it in `sessionStorage` for the tab only.
