"""The eval harness itself: it must be able to fail, replay recordings and report results."""

from typing import Any

from fastapi.testclient import TestClient

from app.agent.llm import Classification, HeuristicLLM
from app.config import Settings
from app.schemas import PolicyCitation, TriageDecision
from tests.conftest import FakeRepo
from tests.evals.harness import (
    PolicyCorpus,
    RecordingLLM,
    load_cases,
    record_llm,
    run_suite,
    save_report,
)


class OverconfidentLLM:
    """A broken agent: labels everything at full confidence, ignoring policy and risk."""

    async def classify(self, title: str, body: str) -> Classification:
        return Classification(intent="other", urgency="normal")

    async def propose(
        self,
        classification: Classification,
        title: str,
        body: str,
        policies: list[PolicyCitation],
        context: dict[str, Any],
    ) -> TriageDecision:
        return TriageDecision(
            recommended_action="label",
            tool_payload={"labels": ["approved"]},
            policy_citations=[],
            confidence_score=1.0,
            reasoning="always sure",
        )


async def test_retrieval_is_scoped_by_intent_and_ignores_unrelated_titles():
    corpus = PolicyCorpus()
    refund = await corpus.retrieve("refund: Refund for an unused blender")
    assert {c.doc_name for c in refund} == {"refunds.md"}
    assert await corpus.retrieve("other: Please add dark mode to settings") == []


async def test_eval_catches_a_broken_overconfident_agent(monkeypatch):
    from tests.evals import harness

    monkeypatch.setattr(harness, "HeuristicLLM", OverconfidentLLM)
    report = await run_suite(recorded={})
    assert report.guardrail_violations, "refund and ambiguous cases must flag auto-execution"
    assert report.pass_rate < Settings(_env_file=None).eval_pass_threshold


async def test_needs_llm_cases_are_skipped_until_recorded_then_replayed():
    skipped_ids = {c["id"] for c in load_cases() if c.get("needs_llm")}
    offline = await run_suite(recorded={})
    assert {r.id for r in offline.skipped} == skipped_ids

    recorded = {
        "production-down-routes-to-on-call": {
            "classification": {"intent": "other", "urgency": "high"},
            "proposal": {
                "recommended_action": "route",
                "tool_payload": {"labels": ["on-call"]},
                "confidence_score": 0.95,
                "reasoning": "production down",
            },
        }
    }
    replayed = await run_suite(recorded=recorded)
    result = next(r for r in replayed.results if r.id == "production-down-routes-to-on-call")
    assert not result.skipped
    assert result.llm == "replay"
    assert result.passed, result.failures


async def test_recording_round_trips_through_replay():
    recorded = await record_llm(HeuristicLLM())
    assert "happy-bug-checkout" in recorded
    assert not any(c["id"] in recorded for c in load_cases() if c.get("fault"))
    # needs_llm cases need a real model's answer; drop the heuristic's wrong ones.
    for case in load_cases():
        if case.get("needs_llm"):
            recorded.pop(case["id"], None)
    report = await run_suite(recorded=recorded)
    assert report.pass_rate == 1.0, report.summary()
    replayed = [r for r in report.evaluated if r.llm == "replay"]
    assert len(replayed) == len(recorded)


async def test_recording_llm_captures_both_steps():
    recorder = RecordingLLM(HeuristicLLM())
    c = await recorder.classify("Bug: x", "")
    await recorder.propose(c, "Bug: x", "", [], {})
    assert set(recorder.entry) == {"classification", "proposal"}


async def test_report_is_saved_and_served_by_the_evals_endpoint(client: TestClient, repo: FakeRepo):
    report = await run_suite(recorded={})
    saved = await save_report(repo, report, "abc1234")
    assert saved.total_cases == len(report.evaluated)
    body = client.get("/evals/latest").json()
    assert body["git_sha"] == "abc1234"
    assert body["pass_rate"] == report.pass_rate
    assert body["p95_latency_ms"] == report.p95_latency_ms
