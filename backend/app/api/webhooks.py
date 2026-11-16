"""Webhook ingestion (FR-1): HMAC verification, idempotency, schema validation, dead-lettering."""

import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from pydantic import ValidationError

from app.api.deps import TriageScheduler, get_triage_scheduler
from app.config import Settings, get_settings
from app.repository import TicketRepository, get_repository
from app.schemas import GitHubIssueEvent, WebhookResponse

router = APIRouter(tags=["webhooks"])
log = logging.getLogger("app.webhooks")

SUPPORTED_PROVIDERS = {"github"}


def verify_signature(secret: str, body: bytes, header: str | None) -> bool:
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


@router.post("/webhooks/{provider}", response_model=WebhookResponse, status_code=202)
async def receive_webhook(
    provider: str,
    request: Request,
    response: Response,
    background: BackgroundTasks,
    repo: TicketRepository = Depends(get_repository),
    settings: Settings = Depends(get_settings),
    schedule: TriageScheduler = Depends(get_triage_scheduler),
) -> WebhookResponse:
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=404, detail=f"unknown provider '{provider}'")

    body = await request.body()
    if not verify_signature(
        settings.webhook_secret, body, request.headers.get("x-hub-signature-256")
    ):
        log.warning("invalid signature", extra={"provider": provider, "status": 401})
        raise HTTPException(status_code=401, detail="invalid signature")

    event_id = request.headers.get("x-github-delivery")
    if not event_id:
        raise HTTPException(status_code=400, detail="missing X-GitHub-Delivery header")

    try:
        raw = json.loads(body)
        event = GitHubIssueEvent.model_validate(raw)
    except (ValueError, ValidationError) as exc:
        # Dead-letter: acknowledge so the provider stops retrying, but keep a structured record.
        log.error(
            "malformed webhook payload dead-lettered: %s",
            exc,
            extra={"provider": provider, "status": "dead_lettered"},
        )
        return WebhookResponse(status="dead_lettered")

    ticket = await repo.create_if_new(
        external_event_id=event_id, provider=provider, raw_payload=event.model_dump(mode="json")
    )
    if ticket is None:
        response.status_code = 200
        log.info("duplicate delivery ignored", extra={"provider": provider, "status": "duplicate"})
        return WebhookResponse(status="duplicate")

    background.add_task(schedule, ticket.id)
    return WebhookResponse(status="accepted", ticket_id=ticket.id)
