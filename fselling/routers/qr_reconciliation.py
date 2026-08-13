"""I10-C durable QR-bank inbox and reconciliation HTTP boundary."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request
from pydantic import AfterValidator, BeforeValidator
from sqlalchemy.orm import Session

from .. import models
from ..dependencies import get_current_user, get_db
from ..schemas.qr_reconciliation import (
    MAX_RECONCILIATION_ID,
    ReconciliationActionRequest,
)
from ..services import qr_reconciliation_service, qr_webhook_service


router = APIRouter(tags=["qr-reconciliation"])


def _canonical_path_id(value: object) -> int:
    if type(value) is not str or not value or not value.isascii() or not value.isdecimal():
        raise ValueError("path ID must be canonical decimal")
    if value != "0" and value.startswith("0"):
        raise ValueError("path ID must be canonical decimal")
    return int(value)


def _bounded_path_id(value: int) -> int:
    if value < 1 or value > MAX_RECONCILIATION_ID:
        raise ValueError("path ID is outside SQLite signed-int64")
    return value


ReconciliationPathId = Annotated[
    int,
    BeforeValidator(_canonical_path_id),
    AfterValidator(_bounded_path_id),
    Path(),
]


@router.post("/api/qr-payments/webhook")
async def ingest_qr_bank_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    runtime = qr_webhook_service.get_runtime()
    metadata = qr_webhook_service.validate_metadata(request, runtime)
    envelope = await qr_webhook_service.read_authenticated_envelope(
        request, runtime, metadata
    )
    event, replay = qr_webhook_service.process_envelope(db, envelope, runtime)
    return qr_webhook_service.serialize_event(event, replay=replay)


@router.get("/api/qr-reconciliation/events")
def list_qr_bank_events(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=100_000),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return qr_reconciliation_service.list_unapplied_events(
        db, current_user, limit=limit, offset=offset
    )


@router.get("/api/qr-reconciliation/events/{event_id}")
def get_qr_bank_event(
    event_id: ReconciliationPathId,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return qr_reconciliation_service.get_event(db, current_user, event_id)


@router.post("/api/qr-reconciliation/events/{event_id}/actions")
def reconcile_qr_bank_event(
    event_id: ReconciliationPathId,
    command: ReconciliationActionRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return qr_reconciliation_service.reconcile_event(
        db, current_user, event_id, command
    )


__all__ = ["router"]
