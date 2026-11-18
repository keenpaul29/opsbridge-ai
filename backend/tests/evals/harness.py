"""End-to-end agent eval harness (PRD section 5).

Runs the real triage pipeline (`run_triage`: classify -> retrieve -> fetch context -> propose ->
route -> execute) over `agent_cases.json` against an in-memory repository and a scripted
connector, then scores four things:

- pass rate         every assertion of a case holds (final status, tool, citations, payload)
- tool accuracy     recommended tool equals the expected tool, over cases that name one
- groundedness      cited policy docs equal the expected set, over cases that name one
- p95 latency       pipeline wall-clock per case

What a green run does NOT prove: retrieval is a lexical stand-in over `policies/*.md` (pgvector and
embeddings are not exercised), and cases without a recorded model answer run on `HeuristicLLM`, so
they test the pipeline and guardrails, not model judgement. `needs_llm` cases are skipped (and
reported as skipped) until `recorded_llm.json` holds a recorded answer for them.
"""

import asyncio
import json
import math
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.agent.llm import Classification, HeuristicLLM, LLMClient
from app.agent.runner import run_triage
from app.config import Settings
from app.connectors.github import ConnectorError, IssueContext
from app.models import TicketStatus
from app.rag.store import chunk_markdown
from app.repository import TicketRepository
from app.schemas import PolicyCitation, TriageDecision
from tests.conftest import FakeRepo

HERE = Path(__file__).parent
POLICY_DIR = HERE.parents[1] / "policies"
CASES_PATH = HERE / "agent_cases.json"
RECORDED_PATH = HERE / "recorded_llm.json"

_STOP = frozenset(
    "the and for with not are was this that from you have has how can please other any all "
    "into your our its who what when where which while about".split()
)


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) > 2 and t not in _STOP}


class PolicyCorpus:
    """Lexical stand-in for pgvector retrieval over the policy markdown.

    The graph queries "<intent>: <title>". For a known intent (bug, refund) only chunks that
    mention that intent are candidates, like a metadata-filtered vector search; for "other" a
    chunk needs two shared words, so one generic word cannot pull in an unrelated policy.
    """

    def __init__(self, directory: Path = POLICY_DIR) -> None:
        self.chunks: list[tuple[str, str]] = [
            (path.name, chunk)
            for path in sorted(directory.glob("*.md"))
            for chunk in chunk_markdown(path.read_text(encoding="utf-8"))
        ]

    async def retrieve(self, query: str, k: int = 4) -> list[PolicyCitation]:
        intent, _, title = query.partition(":")
        intent = intent.strip().lower()
        wanted = _tokens(title)
        gated = intent in {"bug", "refund"}
        scored: list[tuple[int, str, str]] = []
        for doc, text in self.chunks:
            tokens = _tokens(text)
            if gated and intent not in tokens:
                continue
            overlap = len(wanted & tokens) + (1 if gated else 0)
            if overlap >= (1 if gated else 2):
                scored.append((overlap, doc, text))
        hits = sorted(scored, key=lambda s: -s[0])[:k]
        return [
            PolicyCitation(
                doc_name=doc,
                chunk_id=uuid.uuid5(uuid.NAMESPACE_URL, f"{doc}:{text}"),
                text=text,
                score=overlap / (len(wanted) + 1),
            )
            for overlap, doc, text in hits
        ]


class ScriptedConnector:
    """GitHub stand-in: serves the case's issue and fails exactly where the case says to."""

    def __init__(self, issue: dict[str, Any], fault: dict[str, str] | None) -> None:
        self.issue = issue
        self.fault = fault or {}
        self.calls: list[tuple[str, Any]] = []

    def _maybe_fail(self, op: str) -> None:
        if self.fault.get("fail") == op:
            raise ConnectorError(self.fault.get("error", "upstream error"))

    async def get_issue(self, repo: str, number: int) -> IssueContext:
        self._maybe_fail("get_issue")
        return IssueContext(
            number=number, title=self.issue["title"], state="open", body=self.issue.get("body")
        )

    async def add_labels(self, repo: str, number: int, labels: list[str]) -> None:
        self._maybe_fail("add_labels")
        self.calls.append(("labels", labels))

    async def post_comment(self, repo: str, number: int, body: str) -> None:
        self._maybe_fail("post_comment")
        self.calls.append(("comment", body))


class ReplayLLM:
    """Replays a recorded model answer: pins real-model behaviour so CI needs no API key."""

    def __init__(self, entry: dict[str, Any]) -> None:
        self.entry = entry

    async def classify(self, title: str, body: str) -> Classification:
        return Classification(**self.entry["classification"])

    async def propose(
        self,
        classification: Classification,
        title: str,
        body: str,
        policies: list[PolicyCitation],
        context: dict[str, Any],
    ) -> TriageDecision:
        p = self.entry["proposal"]
        return TriageDecision(
            recommended_action=p["recommended_action"],
            tool_payload=p["tool_payload"],
            policy_citations=policies,
            confidence_score=min(max(p["confidence_score"], 0.0), 1.0),
            reasoning=p["reasoning"],
        )


class RecordingLLM:
    """Wraps a live LLM and remembers its answers in the format ReplayLLM reads."""

    def __init__(self, inner: LLMClient) -> None:
        self.inner = inner
        self.entry: dict[str, Any] = {}

    async def classify(self, title: str, body: str) -> Classification:
        result = await self.inner.classify(title, body)
        self.entry["classification"] = result.model_dump()
        return result

    async def propose(
        self,
        classification: Classification,
        title: str,
        body: str,
        policies: list[PolicyCitation],
        context: dict[str, Any],
    ) -> TriageDecision:
        decision = await self.inner.propose(classification, title, body, policies, context)
        self.entry["proposal"] = {
            "recommended_action": decision.recommended_action,
            "tool_payload": decision.tool_payload,
            "confidence_score": decision.confidence_score,
            "reasoning": decision.reasoning,
        }
        return decision


@dataclass
class CaseResult:
    id: str
    category: str
    skipped: bool = False
    llm: str = "heuristic"
    status: str | None = None
    action: str | None = None
    cited: list[str] = field(default_factory=list)
    latency_ms: float = 0.0
    failures: list[str] = field(default_factory=list)
    expect: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not self.skipped and not self.failures


@dataclass
class EvalReport:
    results: list[CaseResult]

    @property
    def evaluated(self) -> list[CaseResult]:
        return [r for r in self.results if not r.skipped]

    @property
    def skipped(self) -> list[CaseResult]:
        return [r for r in self.results if r.skipped]

    @property
    def pass_rate(self) -> float:
        done = self.evaluated
        return sum(r.passed for r in done) / len(done) if done else 0.0

    @property
    def tool_accuracy(self) -> float:
        scored = [r for r in self.evaluated if r.expect.get("action") is not None]
        return sum(r.action == r.expect["action"] for r in scored) / len(scored) if scored else 0.0

    @property
    def groundedness(self) -> float:
        scored = [r for r in self.evaluated if r.expect.get("cites") is not None]
        ok = sum(sorted(set(r.cited)) == sorted(r.expect["cites"]) for r in scored)
        return ok / len(scored) if scored else 0.0

    @property
    def p95_latency_ms(self) -> int:
        times = sorted(r.latency_ms for r in self.evaluated)
        if not times:
            return 0
        return round(times[math.ceil(0.95 * len(times)) - 1])

    @property
    def guardrail_violations(self) -> list[str]:
        """Cases a human must review that the agent executed on its own."""
        return [
            r.id
            for r in self.evaluated
            if r.expect.get("status") == TicketStatus.AWAITING_APPROVAL.value
            and r.status == TicketStatus.EXECUTED.value
        ]

    def summary(self) -> str:
        lines = [
            f"evaluated={len(self.evaluated)} skipped={len(self.skipped)} "
            f"pass={self.pass_rate:.2f} tool={self.tool_accuracy:.2f} "
            f"grounded={self.groundedness:.2f} p95={self.p95_latency_ms}ms"
        ]
        lines += [f"  FAIL {r.id}: {'; '.join(r.failures)}" for r in self.evaluated if r.failures]
        lines += [f"  skip {r.id} (needs recorded LLM answer)" for r in self.skipped]
        return "\n".join(lines)


def load_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = json.loads(CASES_PATH.read_text(encoding="utf-8"))["cases"]
    return cases


def load_recorded() -> dict[str, Any]:
    if not RECORDED_PATH.exists():
        return {}
    recorded: dict[str, Any] = json.loads(RECORDED_PATH.read_text(encoding="utf-8"))
    return recorded


def _settings() -> Settings:
    return Settings(_env_file=None)


def _event(case: dict[str, Any], number: int) -> dict[str, Any]:
    return {
        "action": "opened",
        "repository": {"full_name": "acme/support"},
        "issue": {"number": number, **case["issue"]},
    }


async def _run_one(
    case: dict[str, Any],
    number: int,
    llm: LLMClient,
    corpus: PolicyCorpus,
    repo: TicketRepository | None = None,
) -> tuple[Any, ScriptedConnector, float]:
    repo = repo or FakeRepo()
    ticket = await repo.create_if_new(
        external_event_id=f"eval-{case['id']}",
        provider="github",
        raw_payload=_event(case, number),
    )
    assert ticket is not None
    connector = ScriptedConnector(case["issue"], case.get("fault"))
    started = time.perf_counter()
    await run_triage(
        ticket.id,
        repo,
        connector,  # type: ignore[arg-type]
        _settings(),
        retriever=corpus.retrieve,
        llm=llm,
    )
    latency_ms = (time.perf_counter() - started) * 1000
    return await repo.get(ticket.id), connector, latency_ms


def _score(case: dict[str, Any], ticket: Any, result: CaseResult) -> None:
    expect = case["expect"]
    decision = ticket.recommended_action or {}
    result.status = ticket.status.value
    result.action = decision.get("recommended_action")
    result.cited = sorted({c["doc_name"] for c in decision.get("policy_citations", [])})
    if result.status != expect["status"]:
        result.failures.append(f"status {result.status} != {expect['status']}")
    if expect.get("action") is not None and result.action != expect["action"]:
        result.failures.append(f"action {result.action} != {expect['action']}")
    if expect.get("cites") is not None and result.cited != sorted(expect["cites"]):
        result.failures.append(f"cited {result.cited} != {sorted(expect['cites'])}")
    payload = json.dumps(decision.get("tool_payload", {}))
    for banned in expect.get("forbid_in_payload", []):
        if banned in payload:
            result.failures.append(f"payload contains forbidden {banned!r}")


async def run_suite(recorded: dict[str, Any] | None = None) -> EvalReport:
    recorded = load_recorded() if recorded is None else recorded
    corpus = PolicyCorpus()
    results: list[CaseResult] = []
    for number, case in enumerate(load_cases(), start=1):
        result = CaseResult(id=case["id"], category=case["category"], expect=case["expect"])
        entry = recorded.get(case["id"])
        if entry is None and case.get("needs_llm"):
            result.skipped = True
        else:
            llm: LLMClient = ReplayLLM(entry) if entry else HeuristicLLM()
            result.llm = "replay" if entry else "heuristic"
            ticket, _, result.latency_ms = await _run_one(case, number, llm, corpus)
            _score(case, ticket, result)
        results.append(result)
    return EvalReport(results)


def run_suite_sync(recorded: dict[str, Any] | None = None) -> EvalReport:
    return asyncio.run(run_suite(recorded))


async def record_llm(llm: LLMClient) -> dict[str, Any]:
    """Run every non-fault case through `llm` and return its answers keyed by case id."""
    corpus = PolicyCorpus()
    out: dict[str, Any] = {}
    for number, case in enumerate(load_cases(), start=1):
        if case.get("fault"):
            continue
        recorder = RecordingLLM(llm)
        await _run_one(case, number, recorder, corpus)
        out[case["id"]] = recorder.entry
    return out


async def save_report(repo: TicketRepository, report: EvalReport, git_sha: str) -> Any:
    return await repo.add_eval_run(
        git_sha=git_sha,
        total_cases=len(report.evaluated),
        pass_rate=report.pass_rate,
        tool_accuracy=report.tool_accuracy,
        groundedness_score=report.groundedness,
        p95_latency_ms=report.p95_latency_ms,
    )
