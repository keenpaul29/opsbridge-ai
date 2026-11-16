"""LLM seam for the triage agent.

`HeuristicLLM` is deterministic and offline (tests, CI evals, no API key). `AnthropicLLM` calls
Claude with schema-constrained JSON output. Any failure to obtain a valid structured answer
degrades to a low-confidence decision so the guardrail routes it to a human.
"""

import json
import logging
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from app.config import Settings
from app.schemas import PolicyCitation, TriageDecision

log = logging.getLogger("app.agent.llm")

Intent = Literal["refund", "bug", "other"]


class Classification(BaseModel):
    intent: Intent
    urgency: Literal["high", "normal"]


class _Proposal(BaseModel):
    """What the model returns; `tool_payload` is a JSON string to keep the schema strict."""

    recommended_action: Literal["label", "route", "reply_draft", "refund_draft"]
    tool_payload_json: str
    confidence_score: float = Field(ge=0.0, le=1.0)
    reasoning: str


class LLMClient(Protocol):
    async def classify(self, title: str, body: str) -> Classification: ...

    async def propose(
        self,
        classification: Classification,
        title: str,
        body: str,
        policies: list[PolicyCitation],
        context: dict[str, Any],
    ) -> TriageDecision: ...


class HeuristicLLM:
    """Deterministic stand-in (the original stub logic)."""

    async def classify(self, title: str, body: str) -> Classification:
        text = f"{title} {body}".lower()
        intent: Intent = "refund" if "refund" in text else "bug" if "bug" in text else "other"
        urgency: Literal["high", "normal"] = (
            "high" if any(w in text for w in ("urgent", "asap", "down")) else "normal"
        )
        return Classification(intent=intent, urgency=urgency)

    async def propose(
        self,
        classification: Classification,
        title: str,
        body: str,
        policies: list[PolicyCitation],
        context: dict[str, Any],
    ) -> TriageDecision:
        intent = classification.intent
        action = "refund_draft" if intent == "refund" else "label"
        return TriageDecision(
            recommended_action=action,
            tool_payload={"labels": [intent]} if action == "label" else {"intent": intent},
            policy_citations=policies,
            confidence_score=0.9 if policies else 0.4,
            reasoning=(
                f"Classified as {intent}/{classification.urgency}; {len(policies)} policy hits."
            ),
        )


_CLASSIFY_SYSTEM = (
    "You triage GitHub issues for an operations team. Classify the issue's intent "
    "(refund request, bug report, or other) and urgency (high only if the author signals an "
    "outage or hard deadline)."
)
_PROPOSE_SYSTEM = (
    "You propose one triage action for a GitHub issue, grounded ONLY in the supplied policy "
    "excerpts and live issue context. Actions: label, route, reply_draft, refund_draft. For "
    "label, tool_payload_json is {\"labels\": [...]}; for reply_draft/refund_draft it is "
    "{\"body\": \"...\"}. Set confidence_score honestly: below 0.5 when policy does not cover "
    "the request or the request is ambiguous. Never invent policy."
)


class AnthropicLLM:
    def __init__(self, settings: Settings) -> None:
        from anthropic import AsyncAnthropic  # lazy: not needed for offline runs

        self._client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._model = settings.llm_model

    async def _structured(self, system: str, user: str, schema_model: type[BaseModel]) -> Any:
        schema = schema_model.model_json_schema()
        schema["additionalProperties"] = False
        resp = await self._client.messages.create(
            model=self._model,
            max_tokens=2000,
            system=system,
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": user}],
        )
        if resp.stop_reason == "refusal":
            raise ValueError("model refused")
        text = next((b.text for b in resp.content if b.type == "text"), "")
        return schema_model.model_validate_json(text)

    async def classify(self, title: str, body: str) -> Classification:
        try:
            result = await self._structured(
                _CLASSIFY_SYSTEM, f"Title: {title}\n\nBody:\n{body}", Classification
            )
            assert isinstance(result, Classification)
            return result
        except Exception:  # noqa: BLE001 - degrade, never crash the pipeline
            log.exception("classify failed; defaulting to other/normal")
            return Classification(intent="other", urgency="normal")

    async def propose(
        self,
        classification: Classification,
        title: str,
        body: str,
        policies: list[PolicyCitation],
        context: dict[str, Any],
    ) -> TriageDecision:
        policy_text = "\n".join(f"[{p.doc_name}] {p.text}" for p in policies) or "(none found)"
        user = (
            f"Classification: {classification.model_dump_json()}\n\n"
            f"Issue title: {title}\nIssue body:\n{body}\n\n"
            f"Live issue context: {json.dumps(context, default=str)[:4000]}\n\n"
            f"Policy excerpts:\n{policy_text}"
        )
        try:
            p = await self._structured(_PROPOSE_SYSTEM, user, _Proposal)
            assert isinstance(p, _Proposal)
            payload = json.loads(p.tool_payload_json)
            if not isinstance(payload, dict):
                raise ValueError("tool payload must be an object")
            return TriageDecision(
                recommended_action=p.recommended_action,
                tool_payload=payload,
                policy_citations=policies,
                confidence_score=p.confidence_score,
                reasoning=p.reasoning,
            )
        except Exception:  # noqa: BLE001 - invalid/refused output must escalate, not crash
            log.exception("propose failed; escalating to human review")
            return TriageDecision(
                recommended_action="reply_draft",
                tool_payload={},
                policy_citations=policies,
                confidence_score=0.0,
                reasoning="LLM output unavailable or invalid; needs human review.",
            )


def make_llm(settings: Settings) -> LLMClient:
    return AnthropicLLM(settings) if settings.anthropic_api_key else HeuristicLLM()
