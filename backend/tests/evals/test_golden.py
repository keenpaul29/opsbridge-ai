"""Golden-case eval suite: the CI merge gate (PRD section 5).

Currently scores guardrail compliance (deterministic routing). Extend each case with an `event`
and expected tool/citations once the LLM-backed agent nodes exist, and record a row in
`eval_runs` from a reporter hook.
"""

import json
from pathlib import Path

import pytest

from app.config import Settings
from app.models import TicketStatus
from app.schemas import TriageDecision
from app.state_machine import route_decision

CASES = json.loads((Path(__file__).parent / "golden_cases.json").read_text())["cases"]
THRESHOLD = Settings().confidence_threshold


def _decision(spec: dict) -> TriageDecision:  # type: ignore[type-arg]
    return TriageDecision(reasoning="golden", **spec)


@pytest.mark.eval
@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_guardrail_routing(case: dict) -> None:  # type: ignore[type-arg]
    assert route_decision(_decision(case["decision"]), THRESHOLD) == TicketStatus(
        case["expected_status"]
    )


@pytest.mark.eval
def test_overall_pass_rate_meets_threshold() -> None:
    passed = sum(
        route_decision(_decision(c["decision"]), THRESHOLD) == TicketStatus(c["expected_status"])
        for c in CASES
    )
    assert passed / len(CASES) >= Settings().eval_pass_threshold
