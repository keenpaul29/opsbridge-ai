# Product Requirements Document (PRD): OpsBridge AI

**Author:** Puspal Paul  
**Target Roles:** Forward Deployed Engineer (FDE) / Applied AI Engineer  
**Timeline:** 2 Weeks (14 Days)  
**Primary Stack:** Python (FastAPI, LangGraph, pytest), TypeScript (Next.js, Tailwind CSS), PostgreSQL (`pgvector`), Docker, GitHub Actions, GCP (Cloud Run + Cloud SQL) or AWS (ECS/EC2 + RDS); Groq (OpenAI-compatible chat API) for the agent's LLM calls and Gemini (`gemini-embedding-2`) for policy embeddings
**Status (2026-11-18):** Phases 1-3 are built and open as a pull request; Phase 4 (cloud deployment, real user, case study) is not started. See section 8 for what differs from this plan and the known gaps.

---

## 1. Executive Summary & Goal

**OpsBridge AI** is an autonomous support and order-triage agent that connects a messy third-party API (e.g., Shopify, Stripe test mode, or GitHub Issues) to a **FastAPI** agentic backend, a **TypeScript/Next.js** operator console, and an automated **CI evaluation harness**.

Unlike a generic LLM wrapper, this project is engineered to demonstrate core Forward Deployed Engineer competencies:
1. **Third-party integration resilience:** Idempotent webhook ingestion, signature verification, rate-limit backoff, and malformed-payload handling.
2. **Controlled agentic workflows:** Multi-step tool-calling with `pgvector` policy retrieval and mandatory human-in-the-loop (HITL) pauses for low-confidence or high-risk actions.
3. **Measurable reliability:** A `pytest` evaluation harness (25–30 golden cases) wired into GitHub Actions as a merge gate.
4. **Live cloud deployment & real-user validation:** Hosted on AWS or GCP and tested with one real user to produce a documented case study.

---

## 2. System Architecture

| Layer | Technology | Responsibility |
| :--- | :--- | :--- |
| **Operator Console** | Next.js (App Router), TypeScript, Tailwind CSS | Displays incoming triage queue, live agent traces, tool-call payloads, confidence scores, and Approve/Reject controls. |
| **Agentic Backend** | FastAPI (Python 3.11+), Pydantic v2, LangGraph; LLM via Groq's OpenAI-compatible API with strict JSON-schema output (an offline heuristic stands in when no key is set) | Exposes OpenAPI-typed REST endpoints, ingests webhooks, orchestrates RAG + tool calls, enforces confidence/policy guardrails, and carries out approved or auto-approved actions through one module. |
| **External Connector** | Typed Python HTTP client (`httpx`) | Connects to a real external API (GitHub Issues, Stripe, or Shopify) with exponential backoff, circuit breaking, and schema validation. |
| **Data & Vector Store** | PostgreSQL 16 + `pgvector`; embeddings from Gemini (`gemini-embedding-2`, 768 dimensions) | Stores policy/runbook embeddings, idempotency keys, ticket state, audit logs, and evaluation run history. |
| **Eval & CI/CD** | `pytest`, GitHub Actions, Docker | Runs unit tests + 25–30 golden eval cases on every PR; blocks merges if accuracy drops below threshold. |
| **Cloud Infrastructure** | GCP (Cloud Run + Cloud SQL) or AWS (ECS/EC2 + RDS) + Vercel | Hosts production backend, managed Postgres, and public frontend demo with structured JSON logging. |

---

## 3. Functional Requirements

### FR-1: Resilient Third-Party Integration Layer
* **Webhook Ingestion (`POST /webhooks/{provider}`):**
  * Verify webhook signatures (HMAC-SHA256) and reject invalid requests with `401 Unauthorized`.
  * Enforce idempotency using an `event_id` unique constraint in PostgreSQL so duplicate deliveries do not trigger duplicate agent runs.
  * Validate incoming payloads with strict Pydantic schemas; dead-letter malformed payloads with structured error logs rather than crashing.
* **Outbound API Connector:**
  * Implement typed methods for reading context (e.g., order status, customer history, issue metadata) and drafting/executing actions (e.g., refund draft, ticket label/routing, reply draft).
  * Handle `429 Too Many Requests` and `5xx` upstream errors with exponential backoff + jitter and configurable max retries.

### FR-2: Policy & Runbook RAG Store (`pgvector`)
* Ingest Markdown/PDF operational policies (e.g., refund eligibility rules, SLA escalation tiers, shipping exception policies) into `policy_chunks` with vector embeddings.
* Support hybrid/top-k retrieval returning chunk text, source filename, and similarity score so every agent recommendation cites the exact policy clause used.
* Embed with `gemini-embedding-2` (768 dimensions) and ingest `policies/*.md` at startup when a Gemini key is set. Without a key an offline hash embedder keeps tests running; its retrieval is meaningless and the app logs a warning.
* **Similarity floor:** retrieved policies scoring below `MIN_POLICY_SCORE` (default 0.5, a placeholder until calibrated against real embeddings) count as absent: they are not cited and cannot raise confidence.
* On startup the stored vector column width is compared with `EMBEDDING_DIM`; a mismatch stops the app with a message instead of failing every retrieval.

### FR-3: Multi-Step Agentic Triage & Human-in-the-Loop (HITL)
* **Workflow Steps:**
  1. **Classify & Extract:** Parse the incoming ticket/event into structured intent, urgency, and entity IDs.
  2. **Retrieve Policy:** Query `pgvector` for relevant operational rules.
  3. **Fetch Live Context:** Call the external API connector to inspect real-time order/account/issue state.
  4. **Propose Action & Score Confidence:** Output a structured `TriageDecision` (`recommended_action`, `tool_payload`, `policy_citations`, `confidence_score`, `reasoning`).
* **Guardrail Routing:**
  * **Auto-approve eligible:** Low-risk actions (e.g., tagging/routing) above confidence threshold (`>= 0.85`).
  * **Pause for Human Approval:** High-risk actions (e.g., refunds, account changes) or low confidence (`< 0.85`) transition ticket status to `AWAITING_APPROVAL` until an operator acts in the console.
* **One path for carrying out a decision:** auto-approval and operator approval share one module (`app/agent/decisions.py`). Bad state is a 409, a missing ticket a 404, and a failed action marks the ticket `FAILED` with the error traced (never reported as success). Decisions are serialised per ticket within a process, so a double-click or an approve racing a reject cannot run the action twice.
* **Retrieval failure degrades, it does not strand:** if policy retrieval fails (embedding API down, vector size mismatch), the agent proceeds with no policy, confidence is capped, and a human reviews the ticket; any other crash marks the ticket `FAILED`.

### FR-4: TypeScript + Next.js Operator Console
* Generate or maintain strict TypeScript types matching FastAPI's OpenAPI schema.
* **Views:**
  * **Triage Queue:** Filterable list of tickets by status (`PENDING`, `AWAITING_APPROVAL`, `EXECUTED`, `FAILED`).
  * **Trace Inspector:** Step-by-step timeline of agent reasoning, retrieved policy citations, external API tool calls, latency per step, and raw JSON payloads.
  * **Approval Controls:** One-click **Approve & Execute**, **Edit Payload**, or **Reject** buttons (`POST /tickets/{id}/approve`, `POST /tickets/{id}/reject`) with audit logging. Both require the operator token (see FR-6); reads stay public.
  * **Eval Dashboard:** Summary view of the latest CI/eval run (pass rate, tool-selection accuracy, P95 latency).

### FR-5: Observability & Error Handling
* Emit structured JSON logs (`request_id`, `ticket_id`, `step`, `latency_ms`, `status`) across all FastAPI routes and connector calls.
* Expose `GET /health` checking database and external connector readiness.

### FR-6: Console Access Control
* `approve` and `reject` require `Authorization: Bearer <OPERATOR_TOKEN>` (constant-time comparison; `401` with `WWW-Authenticate` otherwise). Queue, ticket detail, traces, evals and health are public so the console can be shown read-only.
* `ENVIRONMENT=production` refuses to start without an operator token, and the endpoints fail closed if it is missing. An empty token means no auth and is for local development only.
* `CORS_ORIGINS` sets the allowed console origins. The console keeps the token in `sessionStorage` for the tab only.
* Known limitation: one shared token, and the operator name in the audit trail is supplied by the caller, so it can be spoofed. Per-operator identity is out of scope for now (section 9).

---

## 4. Core Data Model (PostgreSQL)

* **`triage_tickets`:** `id` (UUID), `external_event_id` (TEXT UNIQUE), `provider` (TEXT), `raw_payload` (JSONB), `status` (ENUM), `recommended_action` (JSONB), `confidence_score` (FLOAT), `created_at`, `updated_at`.
* **`agent_traces`:** `id` (UUID), `ticket_id` (FK), `step_name` (TEXT), `input_data` (JSONB), `output_data` (JSONB), `citations` (JSONB), `latency_ms` (INT), `created_at`.
* **`policy_chunks`:** `id` (UUID), `doc_name` (TEXT), `content` (TEXT), `embedding` (VECTOR(768)), `metadata` (JSONB). Tables are created at startup; Alembic migrations are not built yet.
* **`eval_runs`:** `id` (UUID), `git_sha` (TEXT), `total_cases` (INT), `pass_rate` (FLOAT), `tool_accuracy` (FLOAT), `groundedness_score` (FLOAT), `p95_latency_ms` (INT), `created_at`.

---

## 5. Automated Evaluation Harness & CI/CD Gates

* **Golden Dataset (`tests/evals/golden_cases.json`):** 25–30 curated test cases covering:
  * Standard policy-compliant requests (happy path).
  * Ambiguous or under-specified user messages (must trigger `AWAITING_APPROVAL` or clarification).
  * Policy violations / out-of-window refund requests (must refuse or escalate).
  * Simulated third-party API `429` / `500` / malformed payload failures (must retry or fail gracefully).
* **Tracked Metrics:**
  * **Tool-Selection Accuracy:** Does the agent call the right external tool with valid arguments?
  * **Policy Groundedness:** Does the decision cite the correct retrieved policy chunk without hallucinating rules?
  * **Guardrail Compliance:** Do low-confidence / high-risk cases reliably pause for human approval?
  * **P95 Latency:** End-to-end triage latency measured across the suite.
* **GitHub Actions Pipeline (`.github/workflows/ci.yml`):**
  * Runs `ruff`/`mypy` (or `pyright`), `pytest` unit/integration tests, and the eval suite on every push/PR.
  * Fails the build if eval pass rate drops below the configured threshold (e.g., `< 85%`).

---

### 5.1 What the eval harness measures today
* **Golden set (26 cases):** 20 end-to-end cases in `tests/evals/agent_cases.json` (happy path, refund-policy violations, ambiguous issues, prompt injection, upstream failure) plus 6 guardrail boundary cases in `golden_cases.json`. Each end-to-end case runs the real triage pipeline against an in-memory repository and a scripted connector.
* **Metrics:** pass rate, tool-selection accuracy, policy groundedness (the cited documents equal the expected set) and p95 pipeline latency, gated by `EVAL_PASS_THRESHOLD` and `EVAL_P95_MS`. Guardrail compliance is a hard gate: a case a human must review is never auto-executed.
* **`eval_runs` is written** by `python -m scripts.record_eval_run` and served at `/evals/latest` for the console's eval page.
* **Caveats:** retrieval in the harness is a lexical stand-in for pgvector; cases without a recorded model answer run on the offline heuristic, so they test the pipeline and guardrails, not model judgement; the 3 cases that need real judgement are skipped until `scripts/record_eval_llm.py` records Groq's answers into `tests/evals/recorded_llm.json` (needs a Groq key). Latency excludes real LLM time.

---

## 6. 2-Week Implementation Plan

| Phase | Days | Key Deliverables & Acceptance Criteria |
| :--- | :--- | :--- |
| **Phase 1: Integration & RAG** | Days 1–3 | FastAPI app scaffold, PostgreSQL + `pgvector` Docker Compose setup, typed third-party connector with backoff, HMAC + idempotent webhook endpoint, structured JSON logging, and `pytest` unit tests for malformed/duplicate payloads. |
| **Phase 2: Agent & Console** | Days 4–7 | Multi-step LangGraph/tool-calling agent, `pgvector` policy retrieval, HITL approval state machine, OpenAPI-typed Next.js + TypeScript console with Trace Inspector and Approve/Reject actions. |
| **Phase 3: Evals & CI/CD** | Days 8–10 | 25–30 golden eval cases in `pytest` measuring tool accuracy, groundedness, and P95 latency; multi-stage Dockerfiles; GitHub Actions workflow blocking merges on unit or eval regressions. |
| **Phase 4: Cloud & Case Study** | Days 11–14 | Live deployment on GCP (Cloud Run + Cloud SQL) or AWS (ECS/EC2 + RDS) + public frontend URL; onboard 1 real user (small business, campus group, or OSS maintainer), fix and document 2 real-world edge cases, and publish a 1-page case study in the README. |

| Phase | Status (2026-11-18) |
| :--- | :--- |
| **Phase 1: Integration & RAG** | Built: signed, idempotent webhooks with dead-lettering; connector with backoff and circuit breaker; structured logging. Gemini embeddings and startup ingestion added. |
| **Phase 2: Agent & Console** | Built: four-step LangGraph agent, HITL state machine, console (queue, trace inspector, approve/edit/reject, eval page), operator token. |
| **Phase 3: Evals & CI/CD** | Built: 26-case golden set, four metrics, `eval_runs` writer, CI gate. Open: record live model answers for the 3 skipped cases; calibrate the similarity floor against real embeddings. |
| **Phase 4: Cloud & Case Study** | Not started: deployment, public URL, onboarding one real user, documenting two real edge cases, README case study. |

---

## 7. Resume & Portfolio Packaging

Once deployed and validated, place **OpsBridge AI** at the top of the **Projects** section (above EuphonicAI) with links to the live demo, GitHub repo, and case study:
1. **Cloud & Integration Resilience:** Deployed a FastAPI + PostgreSQL (`pgvector`) triage service on AWS/GCP with idempotent webhook ingestion, exponential backoff, and strict schema validation against a live third-party API.
2. **Human-in-the-Loop Agent Architecture:** Built a multi-step tool-calling agent with a TypeScript/Next.js operator console for trace inspection, policy citation review, and approval gating on low-confidence actions.
3. **Automated Evals & CI Gates:** Authored a 25–30 case `pytest` evaluation harness integrated into GitHub Actions, tracking exact tool-selection accuracy, groundedness, and P95 latency across every release.

---

## 8. Differences From This Plan and Known Gaps

**Differs from the original plan:** the LLM is Groq (free tier) rather than an unspecified provider; embeddings are Gemini; FR-6 (access control) and the similarity floor were added after review; the eval set is 26 cases (20 end to end plus 6 guardrail boundaries) rather than a single 25-30 case file.

**Known gaps (none block a local demo; several block a public one):**
* No deployment, public URL or real user yet (Phase 4).
* Alembic migrations are not built; tables are created at startup and `create_all` never alters a column.
* One shared operator token; the audit trail's operator name is caller-supplied.
* Per-ticket serialisation is in-process only. Two replicas, or a database write failing after a successful GitHub action, can still repeat an action; closing it needs an atomic claim in the repository.
* A database error inside policy retrieval can leave the shared session aborted; embedding-API failures are handled.
* Startup ingestion re-embeds every policy on each start, blocks readiness while it runs, and two replicas starting together can insert duplicate chunks.
* `MIN_POLICY_SCORE` is uncalibrated.
* No exploratory test against a real Postgres with pgvector has been run.

---

## 9. Agreed Features (2026-11-20)

The author chose four features and settled their details. Build order is the order below; each makes a PRD claim visible in a short demo.

### 9.1 Trace tape with citations (grounded decisions)
* The ticket page's step list keeps its layout (step number, latency in the right gutter). Citations become footnote superscripts that expand inline to the document name, similarity score and the exact policy text, in place of the raw JSON shown today.
* The tape also shows what the guardrails did, from data already stored on the `retrieve_policy` trace: how many policies were dropped below the similarity floor (`dropped_below_floor`) and whether retrieval failed (`retrieval_error`). No backend change is needed.

### 9.2 Reject saves as a golden case (measurable reliability)
* After a reject, the operator can save the ticket as a proposed eval case. The form is prefilled with the issue text and the agent's decision; the operator supplies only the **expected action** (dropdown) and the **expected final status**. Expected policy citations default to "unchanged" and can be refined when the case is reviewed.
* Cases are stored in the database as **proposed cases**, not written to the repository. A script exports proposals into `tests/evals/agent_cases.json` for the author to review and commit, so a person always stands between an operator's click and the CI merge gate.

### 9.3 Keyboard queue (human-in-the-loop)
* `j` / `k` move a highlight through the queue and `Enter` opens the ticket. Approve and reject stay on the ticket page, where the policy evidence is on screen; the existing `A` / `E` / `R` keys there are unchanged. Nothing is approved from the list.
* The queue sorts `AWAITING_APPROVAL` first, lowest confidence first (the tickets that need the most attention), then the rest as before.

### 9.4 What-if replay (engineering judgement; tunes the similarity floor)
* Re-run a stored ticket with a different **model**, **similarity floor** or **confidence threshold** (the prompt lives in code and is not varied) and show the replayed decision next to the original.
* A replay works from the stored issue payload, never calls GitHub, never executes an action, never changes the ticket's status or traces, and is not saved.

### 9.5 Access control for the new features
* Saving a proposed case and running a replay require the operator token (FR-6): a replay spends Groq quota and saving writes to the database. The public view stays read-only.

### 9.6 Not selected, deferred or out of scope
* **Not selected:** eval history page.
* **Deferred:** live sandbox repository ("open an issue and watch it triage"; needs rate limits and abuse handling), a second provider (Stripe or Shopify test mode), Slack or GitHub-comment notifications.
* **Out of scope for now:** per-operator identity (GitHub sign-in), multi-tenant workspaces, a policy editor UI.

### 9.7 Chosen interfaces and decisions (2026-11-20)

**What-if replay (9.4).** A `Replayer` that is given only read-only access: a ticket reader, the retriever and an LLM factory, with no repository, connector or settings object, so it cannot write or call GitHub. `POST /tickets/{id}/replay` (operator token) takes optional `model`, `min_policy_score` and `confidence_threshold` and returns `original`, `replayed`, `changed`, `applied` (the settings actually used and whether the LLM was Groq or the offline heuristic), `cost` (declared: 2 LLM calls, 1 embedding) and `context: stored_payload_only`.
* Models are limited to a `REPLAY_MODELS` allowlist that defaults to the configured model; other names are a 422.
* With no Groq key the replay runs on the offline heuristic and says so, ignoring the model override.
* If the LLM call fails the replay returns a 502, never a low-confidence decision that looks real (a `strict` mode on the LLM client).
* When only the confidence threshold changes, the stored decision is re-routed with no LLM call (`reran: false`).
* Replay uses the stored issue payload only. The original run used live GitHub context, so small differences are possible and the result says so.
* One replay at a time per process (429 when busy), at most one retry per LLM call, and a hard timeout.
* The decide-then-route step is extracted from `run_triage` into a shared `decide()` that both triage and replay call, so they cannot drift apart.

**Save as golden case (9.2).** A module with two entry points: `propose_case(repo, ticket_id, body)` (operator token; only for a rejected ticket, otherwise 409) and a pure `export_proposals(rows, path)` run by `python -m scripts.export_eval_proposals [--dry-run]`.
* Table `eval_proposals`. Case id is `rejected-<title slug, 40 chars>-<8 hex of sha256(ticket id)>`, so saving the same ticket twice updates one row and exporting twice changes nothing.
* The operator supplies the expected action and expected status. Citations default to the documents the agent cited, shown to the operator and editable, because a rejection often means the wrong policy was cited.
* Issue text is redacted once at save (emails, tokens, long hex strings) and truncated to 2,000 characters; only redacted text is stored. Redaction is best-effort, and the author's review of the git diff is the real gate.
* The export validates every case with one `validate_case` shared with the eval harness's `load_cases`, appends only ids not already in `agent_cases.json`, leaves existing cases untouched, and writes atomically. `needs_llm` is left false for the author to set at review.
* Deferred: a console page and API to list, edit or discard proposals.

**Build order:** trace tape, save-as-golden-case, keyboard queue, what-if replay.

### 9.8 Still open
* Whether the issue text can contain customer data or is only public GitHub issues. The light redaction above assumes public issues and is unconfirmed; customer data would need stricter redaction or no stored body.
* Whether the first public link is a read-only console over seeded tickets (recommended) or a live sandbox.
* Who the one real user is, and whether they have agreed to be described in the case study.
