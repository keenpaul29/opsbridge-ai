from app.agent.graph import build_graph
from app.schemas import PolicyCitation


async def test_graph_runs_all_steps_and_cites_policy():
    cite = PolicyCitation(doc_name="refunds.md", text="30-day window", score=0.9)

    async def retriever(_q: str) -> list[PolicyCitation]:
        return [cite]

    async def context(_e: dict) -> dict:  # type: ignore[type-arg]
        return {"state": "open"}

    graph = build_graph(retriever, context)
    event = {"issue": {"number": 1, "title": "Refund for order 9", "body": "please"}}
    out = await graph.ainvoke({"event": event, "trace": []})

    assert [t["step"] for t in out["trace"]] == [
        "classify",
        "retrieve_policy",
        "fetch_context",
        "propose",
    ]
    assert out["decision"].recommended_action == "refund_draft"
    assert out["decision"].policy_citations == [cite]


async def test_llm_is_injected_and_no_policy_caps_confidence():
    from app.agent.llm import Classification
    from app.schemas import TriageDecision

    class FakeLLM:
        async def classify(self, title: str, body: str) -> Classification:
            return Classification(intent="bug", urgency="high")

        async def propose(self, classification, title, body, policies, context):  # type: ignore[no-untyped-def]
            return TriageDecision(
                recommended_action="label",
                tool_payload={"labels": ["bug"]},
                confidence_score=0.99,
                reasoning="fake",
            )

    async def retriever(_q: str) -> list[PolicyCitation]:
        return []

    async def context(_e: dict) -> dict:  # type: ignore[type-arg]
        return {}

    graph = build_graph(retriever, context, FakeLLM())
    out = await graph.ainvoke({"event": {"issue": {"number": 1, "title": "x"}}, "trace": []})
    assert out["intent"] == "bug"
    assert out["decision"].confidence_score <= 0.4


async def _run_with_floor(scores: list[float], floor: float):  # type: ignore[no-untyped-def]
    cites = [PolicyCitation(doc_name=f"d{i}.md", text="t", score=s) for i, s in enumerate(scores)]

    async def retriever(_q: str) -> list[PolicyCitation]:
        return cites

    async def context(_e: dict) -> dict:  # type: ignore[type-arg]
        return {}

    graph = build_graph(retriever, context, min_policy_score=floor)
    event = {"issue": {"number": 1, "title": "Bug: crash", "body": "bug"}}
    return await graph.ainvoke({"event": event, "trace": []})


async def test_weak_policy_matches_are_dropped_and_not_cited():
    out = await _run_with_floor([0.9, 0.2], floor=0.5)
    assert [p.doc_name for p in out["policies"]] == ["d0.md"]
    assert [p.doc_name for p in out["decision"].policy_citations] == ["d0.md"]
    retrieve = next(t for t in out["trace"] if t["step"] == "retrieve_policy")
    assert (retrieve["hits"], retrieve["dropped_below_floor"]) == (1, 1)
    assert out["decision"].confidence_score == 0.9


async def test_only_weak_matches_cap_confidence_like_no_policy():
    out = await _run_with_floor([0.3, 0.1], floor=0.5)
    assert out["policies"] == []
    assert out["decision"].policy_citations == []
    assert out["decision"].confidence_score <= 0.4  # below the auto-approve threshold


async def test_score_at_the_floor_is_kept():
    out = await _run_with_floor([0.5], floor=0.5)
    assert len(out["policies"]) == 1
