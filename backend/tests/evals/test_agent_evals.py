"""CI merge gate: end-to-end agent evals over the golden cases (PRD section 5).

See harness.py for what each metric means and what a green run does not prove.
"""

import pytest

from app.config import Settings
from tests.evals.harness import EvalReport, run_suite_sync

SETTINGS = Settings(_env_file=None)
MIN_EVALUATED = 12  # the gate must not pass vacuously because most cases were skipped


@pytest.fixture(scope="module")
def report() -> EvalReport:
    return run_suite_sync()


@pytest.mark.eval
def test_gate_is_not_vacuous(report: EvalReport) -> None:
    assert len(report.evaluated) >= MIN_EVALUATED, report.summary()


@pytest.mark.eval
def test_guardrail_compliance_is_absolute(report: EvalReport) -> None:
    assert report.guardrail_violations == [], report.summary()


@pytest.mark.eval
def test_pass_rate(report: EvalReport) -> None:
    assert report.pass_rate >= SETTINGS.eval_pass_threshold, report.summary()


@pytest.mark.eval
def test_tool_selection_accuracy(report: EvalReport) -> None:
    assert report.tool_accuracy >= SETTINGS.eval_pass_threshold, report.summary()


@pytest.mark.eval
def test_policy_groundedness(report: EvalReport) -> None:
    assert report.groundedness >= SETTINGS.eval_pass_threshold, report.summary()


@pytest.mark.eval
def test_p95_latency(report: EvalReport) -> None:
    assert report.p95_latency_ms <= SETTINGS.eval_p95_ms, report.summary()
