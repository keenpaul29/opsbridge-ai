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
