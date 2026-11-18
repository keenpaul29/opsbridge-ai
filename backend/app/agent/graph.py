"""LangGraph triage workflow (FR-3): classify -> retrieve policy -> fetch context -> propose.

`classify` and `propose` delegate to an injected `LLMClient` (see agent/llm.py); the default
`HeuristicLLM` is deterministic so evals run offline. The retriever and context fetcher are
injected too.
"""

import time
from collections.abc import Awaitable, Callable
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from app.agent.llm import Classification, HeuristicLLM, LLMClient
from app.schemas import PolicyCitation, TriageDecision


class TriageState(TypedDict, total=False):
    event: dict[str, Any]
    intent: str
    urgency: str
    policies: list[PolicyCitation]
    context: dict[str, Any]
    decision: TriageDecision
    trace: list[dict[str, Any]]


Retriever = Callable[[str], Awaitable[list[PolicyCitation]]]
ContextFetcher = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def _record(state: TriageState, step: str, started: float, **data: Any) -> list[dict[str, Any]]:
    entry = {"step": step, "latency_ms": int((time.perf_counter() - started) * 1000), **data}
    return [*state.get("trace", []), entry]


NO_POLICY_CONFIDENCE_CAP = 0.4


def build_graph(
    retriever: Retriever,
    fetch_context: ContextFetcher,
    llm: LLMClient | None = None,
    min_policy_score: float = 0.0,
) -> Any:
    llm = llm or HeuristicLLM()

    def _issue_text(state: TriageState) -> tuple[str, str]:
        issue = state["event"].get("issue", {})
        return issue.get("title", ""), issue.get("body") or ""

    async def classify(state: TriageState) -> TriageState:
        t = time.perf_counter()
        title, body = _issue_text(state)
        c = await llm.classify(title, body)
        return {
            "intent": c.intent,
            "urgency": c.urgency,
            "trace": _record(state, "classify", t, intent=c.intent, urgency=c.urgency),
        }

    async def retrieve_policy(state: TriageState) -> TriageState:
        t = time.perf_counter()
        issue = state["event"].get("issue", {})
        found = await retriever(f"{state['intent']}: {issue.get('title', '')}")
        # A weak match is no match: it must not be cited or count toward confidence.
        policies = [p for p in found if p.score >= min_policy_score]
        return {
            "policies": policies,
            "trace": _record(
                state,
                "retrieve_policy",
                t,
                hits=len(policies),
                dropped_below_floor=len(found) - len(policies),
            ),
        }

    async def fetch_live_context(state: TriageState) -> TriageState:
        t = time.perf_counter()
        context = await fetch_context(state["event"])
        return {"context": context, "trace": _record(state, "fetch_context", t)}

    async def propose(state: TriageState) -> TriageState:
        t = time.perf_counter()
        policies = state.get("policies", [])
        title, body = _issue_text(state)
        classification = Classification(intent=state["intent"], urgency=state["urgency"])
        decision = await llm.propose(
            classification, title, body, policies, state.get("context", {})
        )
        # Guardrail independent of the model: no retrieved policy means we cannot be confident.
        if not policies and decision.confidence_score > NO_POLICY_CONFIDENCE_CAP:
            decision = decision.model_copy(update={"confidence_score": NO_POLICY_CONFIDENCE_CAP})
        return {
            "decision": decision,
            "trace": _record(
                state,
                "propose",
                t,
                action=decision.recommended_action,
                confidence=decision.confidence_score,
            ),
        }

    graph = StateGraph(TriageState)
    graph.add_node("classify", classify)
    graph.add_node("retrieve_policy", retrieve_policy)
    graph.add_node("fetch_context", fetch_live_context)
    graph.add_node("propose", propose)
    graph.set_entry_point("classify")
    graph.add_edge("classify", "retrieve_policy")
    graph.add_edge("retrieve_policy", "fetch_context")
    graph.add_edge("fetch_context", "propose")
    graph.add_edge("propose", END)
    return graph.compile()
