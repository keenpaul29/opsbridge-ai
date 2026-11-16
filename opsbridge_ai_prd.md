# Product Requirements Document (PRD): OpsBridge AI

**Author:** Puspal Paul  
**Target Roles:** Forward Deployed Engineer (FDE) / Applied AI Engineer  
**Timeline:** 2 Weeks (14 Days)  
**Primary Stack:** Python (FastAPI, LangGraph, pytest), TypeScript (Next.js, Tailwind CSS), PostgreSQL (`pgvector`), Docker, GitHub Actions, GCP (Cloud Run + Cloud SQL) or AWS (ECS/EC2 + RDS)

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
| **Agentic Backend** | FastAPI (Python 3.11+), Pydantic v2, LangGraph (or typed tool loop) | Exposes OpenAPI-typed REST endpoints, ingests webhooks, orchestrates RAG + tool calls, and enforces confidence/policy guardrails. |
| **External Connector** | Typed Python HTTP client (`httpx`) | Connects to a real external API (GitHub Issues, Stripe, or Shopify) with exponential backoff, circuit breaking, and schema validation. |
| **Data & Vector Store** | PostgreSQL 16 + `pgvector` | Stores policy/runbook embeddings, idempotency keys, ticket state, audit logs, and evaluation run history. |
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

### FR-3: Multi-Step Agentic Triage & Human-in-the-Loop (HITL)
* **Workflow Steps:**
  1. **Classify & Extract:** Parse the incoming ticket/event into structured intent, urgency, and entity IDs.
  2. **Retrieve Policy:** Query `pgvector` for relevant operational rules.
  3. **Fetch Live Context:** Call the external API connector to inspect real-time order/account/issue state.
  4. **Propose Action & Score Confidence:** Output a structured `TriageDecision` (`recommended_action`, `tool_payload`, `policy_citations`, `confidence_score`, `reasoning`).
* **Guardrail Routing:**
  * **Auto-approve eligible:** Low-risk actions (e.g., tagging/routing) above confidence threshold (`>= 0.85`).
  * **Pause for Human Approval:** High-risk actions (e.g., refunds, account changes) or low confidence (`< 0.85`) transition ticket status to `AWAITING_APPROVAL` until an operator acts in the console.

### FR-4: TypeScript + Next.js Operator Console
* Generate or maintain strict TypeScript types matching FastAPI's OpenAPI schema.
* **Views:**
  * **Triage Queue:** Filterable list of tickets by status (`PENDING`, `AWAITING_APPROVAL`, `EXECUTED`, `FAILED`).
  * **Trace Inspector:** Step-by-step timeline of agent reasoning, retrieved policy citations, external API tool calls, latency per step, and raw JSON payloads.
  * **Approval Controls:** One-click **Approve & Execute**, **Edit Payload**, or **Reject** buttons (`POST /tickets/{id}/approve`, `POST /tickets/{id}/reject`) with audit logging.
  * **Eval Dashboard:** Summary view of the latest CI/eval run (pass rate, tool-selection accuracy, P95 latency).

### FR-5: Observability & Error Handling
* Emit structured JSON logs (`request_id`, `ticket_id`, `step`, `latency_ms`, `status`) across all FastAPI routes and connector calls.
* Expose `GET /health` checking database and external connector readiness.

---

## 4. Core Data Model (PostgreSQL)

* **`triage_tickets`:** `id` (UUID), `external_event_id` (TEXT UNIQUE), `provider` (TEXT), `raw_payload` (JSONB), `status` (ENUM), `recommended_action` (JSONB), `confidence_score` (FLOAT), `created_at`, `updated_at`.
* **`agent_traces`:** `id` (UUID), `ticket_id` (FK), `step_name` (TEXT), `input_data` (JSONB), `output_data` (JSONB), `citations` (JSONB), `latency_ms` (INT), `created_at`.
* **`policy_chunks`:** `id` (UUID), `doc_name` (TEXT), `content` (TEXT), `embedding` (VECTOR), `metadata` (JSONB).
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

## 6. 2-Week Implementation Plan

| Phase | Days | Key Deliverables & Acceptance Criteria |
| :--- | :--- | :--- |
| **Phase 1: Integration & RAG** | Days 1–3 | FastAPI app scaffold, PostgreSQL + `pgvector` Docker Compose setup, typed third-party connector with backoff, HMAC + idempotent webhook endpoint, structured JSON logging, and `pytest` unit tests for malformed/duplicate payloads. |
| **Phase 2: Agent & Console** | Days 4–7 | Multi-step LangGraph/tool-calling agent, `pgvector` policy retrieval, HITL approval state machine, OpenAPI-typed Next.js + TypeScript console with Trace Inspector and Approve/Reject actions. |
| **Phase 3: Evals & CI/CD** | Days 8–10 | 25–30 golden eval cases in `pytest` measuring tool accuracy, groundedness, and P95 latency; multi-stage Dockerfiles; GitHub Actions workflow blocking merges on unit or eval regressions. |
| **Phase 4: Cloud & Case Study** | Days 11–14 | Live deployment on GCP (Cloud Run + Cloud SQL) or AWS (ECS/EC2 + RDS) + public frontend URL; onboard 1 real user (small business, campus group, or OSS maintainer), fix and document 2 real-world edge cases, and publish a 1-page case study in the README. |

---

## 7. Resume & Portfolio Packaging

Once deployed and validated, place **OpsBridge AI** at the top of the **Projects** section (above EuphonicAI) with links to the live demo, GitHub repo, and case study:
1. **Cloud & Integration Resilience:** Deployed a FastAPI + PostgreSQL (`pgvector`) triage service on AWS/GCP with idempotent webhook ingestion, exponential backoff, and strict schema validation against a live third-party API.
2. **Human-in-the-Loop Agent Architecture:** Built a multi-step tool-calling agent with a TypeScript/Next.js operator console for trace inspection, policy citation review, and approval gating on low-confidence actions.
3. **Automated Evals & CI Gates:** Authored a 25–30 case `pytest` evaluation harness integrated into GitHub Actions, tracking exact tool-selection accuracy, groundedness, and P95 latency across every release.
