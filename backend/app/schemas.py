"""Pydantic v2 API + agent schemas. These drive the OpenAPI spec the frontend types come from."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models import TicketStatus

# ---- Inbound webhook payload (GitHub Issues) -------------------------------------------


class GitHubLabel(BaseModel):
    name: str


class GitHubIssue(BaseModel):
    number: int
    title: str
    body: str | None = None
    labels: list[GitHubLabel] = Field(default_factory=list)


class GitHubRepo(BaseModel):
    full_name: str


class GitHubIssueEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    action: str
    issue: GitHubIssue
    repository: GitHubRepo


class WebhookResponse(BaseModel):
    status: Literal["accepted", "duplicate", "dead_lettered"]
    ticket_id: uuid.UUID | None = None


# ---- Agent output -------------------------------------------------------------------------


class PolicyCitation(BaseModel):
    doc_name: str
    chunk_id: uuid.UUID | None = None
    text: str
    score: float


class TriageDecision(BaseModel):
    recommended_action: str  # e.g. "label", "route", "reply_draft", "refund_draft"
    tool_payload: dict[str, Any] = Field(default_factory=dict)
    policy_citations: list[PolicyCitation] = Field(default_factory=list)
    confidence_score: float = Field(ge=0.0, le=1.0)
    reasoning: str


# ---- Tickets API --------------------------------------------------------------------------


class TicketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    external_event_id: str
    provider: str
    status: TicketStatus
    recommended_action: dict[str, Any] | None
    confidence_score: float | None
    created_at: datetime
    updated_at: datetime


class TicketDetail(TicketOut):
    raw_payload: dict[str, Any]


class TraceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ticket_id: uuid.UUID
    step_name: str
    input_data: dict[str, Any] | None
    output_data: dict[str, Any] | None
    citations: list[dict[str, Any]] | None
    latency_ms: int
    created_at: datetime


class ApproveRequest(BaseModel):
    """Optional operator-edited payload (the console's "Edit Payload" action)."""

    edited_payload: dict[str, Any] | None = None
    operator: str = "operator"


class RejectRequest(BaseModel):
    reason: str = ""
    operator: str = "operator"


class EvalRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    git_sha: str
    total_cases: int
    pass_rate: float
    tool_accuracy: float
    groundedness_score: float
    p95_latency_ms: int
    created_at: datetime


class HealthOut(BaseModel):
    status: Literal["ok", "degraded"]
    database: bool
    connector: bool
