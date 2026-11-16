import json
from typing import Any

import httpx

from app.agent.llm import (
    Classification,
    HeuristicLLM,
    OpenAICompatLLM,
    make_llm,
    strict_schema,
)
from app.config import Settings
from app.schemas import PolicyCitation

CITE = PolicyCitation(doc_name="refunds.md", text="30-day window", score=0.9)


def completion(content: Any, finish_reason: str = "stop") -> dict[str, Any]:
    text = content if isinstance(content, str) else json.dumps(content)
    return {"choices": [{"finish_reason": finish_reason, "message": {"content": text}}]}


def make(handler, **overrides: Any) -> tuple[OpenAICompatLLM, list[float], list[dict[str, Any]]]:
    sleeps: list[float] = []
    bodies: list[dict[str, Any]] = []

    async def fake_sleep(s: float) -> None:
        sleeps.append(s)

    def recording(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return handler(request)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(recording),
        base_url="https://api.groq.com/openai/v1",
        headers={"Authorization": "Bearer test-key"},
    )
    settings = Settings(
        groq_api_key="test-key", llm_max_retries=2, llm_backoff_base_s=0.01, **overrides
    )
    return OpenAICompatLLM(settings, client=client, sleep=fake_sleep), sleeps, bodies


def _has_key(node: Any, key: str) -> bool:
    if isinstance(node, dict):
        return key in node or any(_has_key(v, key) for v in node.values())
    if isinstance(node, list):
        return any(_has_key(v, key) for v in node)
    return False


async def test_classify_sends_strict_schema_and_parses():
    llm, _, bodies = make(
        lambda _: httpx.Response(200, json=completion({"intent": "bug", "urgency": "high"}))
    )
    result = await llm.classify("App down", "bug in checkout")
    assert result == Classification(intent="bug", urgency="high")

    body = bodies[0]
    fmt = body["response_format"]
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["strict"] is True
    schema = fmt["json_schema"]["schema"]
    assert schema["additionalProperties"] is False
    assert sorted(schema["required"]) == ["intent", "urgency"]
    assert body["model"] == "openai/gpt-oss-120b"
    assert body["reasoning_effort"] == "low"
    assert body["include_reasoning"] is False
    # untrusted issue text is delimited
    assert "<issue>" in body["messages"][1]["content"]


def test_schemas_have_no_numeric_bounds_and_are_strict():
    from app.agent.llm import _Proposal

    for model in (Classification, _Proposal):
        schema = strict_schema(model)
        assert not _has_key(schema, "minimum")
        assert not _has_key(schema, "maximum")
        assert schema["additionalProperties"] is False
        assert sorted(schema["required"]) == sorted(schema["properties"])


async def test_propose_parses_clamps_confidence_and_attaches_citations():
    proposal = {
        "recommended_action": "label",
        "tool_payload_json": '{"labels": ["bug"]}',
        "confidence_score": 1.4,
        "reasoning": "clear bug",
    }
    llm, _, _ = make(lambda _: httpx.Response(200, json=completion(proposal)))
    decision = await llm.propose(
        Classification(intent="bug", urgency="normal"), "t", "b", [CITE], {}
    )
    assert decision.recommended_action == "label"
    assert decision.tool_payload == {"labels": ["bug"]}
    assert decision.confidence_score == 1.0
    assert decision.policy_citations == [CITE]


async def test_retries_429_honouring_retry_after():
    calls = {"n": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"retry-after": "3"})
        return httpx.Response(200, json=completion({"intent": "refund", "urgency": "normal"}))

    llm, sleeps, _ = make(handler)
    result = await llm.classify("Refund", "please")
    assert result.intent == "refund"
    assert calls["n"] == 2
    assert sleeps and sleeps[0] >= 3


async def test_classify_degrades_when_upstream_keeps_failing():
    llm, _, _ = make(lambda _: httpx.Response(503))
    assert await llm.classify("x", "y") == Classification(intent="other", urgency="normal")


async def test_propose_escalates_on_invalid_json():
    llm, _, _ = make(lambda _: httpx.Response(200, json=completion("not json at all")))
    decision = await llm.propose(Classification(intent="bug", urgency="normal"), "t", "b", [], {})
    assert decision.confidence_score == 0.0
    assert decision.recommended_action == "reply_draft"


async def test_propose_escalates_on_truncated_output():
    proposal = {
        "recommended_action": "label",
        "tool_payload_json": "{}",
        "confidence_score": 0.99,
        "reasoning": "x",
    }
    llm, _, _ = make(lambda _: httpx.Response(200, json=completion(proposal, "length")))
    decision = await llm.propose(Classification(intent="bug", urgency="normal"), "t", "b", [], {})
    assert decision.confidence_score == 0.0


async def test_propose_escalates_when_payload_is_not_an_object():
    proposal = {
        "recommended_action": "label",
        "tool_payload_json": '["bug"]',
        "confidence_score": 0.99,
        "reasoning": "x",
    }
    llm, _, _ = make(lambda _: httpx.Response(200, json=completion(proposal)))
    decision = await llm.propose(Classification(intent="bug", urgency="normal"), "t", "b", [], {})
    assert decision.confidence_score == 0.0


async def test_non_gpt_oss_model_omits_reasoning_params():
    llm, _, bodies = make(
        lambda _: httpx.Response(200, json=completion({"intent": "other", "urgency": "normal"})),
        llm_model="qwen/qwen3.8-27b",
    )
    await llm.classify("a", "b")
    assert "reasoning_effort" not in bodies[0]
    assert "include_reasoning" not in bodies[0]
    assert bodies[0]["model"] == "qwen/qwen3.8-27b"


def test_make_llm_selects_backend_by_key():
    assert isinstance(make_llm(Settings(groq_api_key="")), HeuristicLLM)
    assert isinstance(make_llm(Settings(groq_api_key="k")), OpenAICompatLLM)
