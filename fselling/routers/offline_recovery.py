"""Owner-only HTTP boundary for I09-G1 offline receipt recovery."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import ValidationError
from sqlalchemy.orm import Session

from .. import models
from ..dependencies import get_current_user, get_db
from ..schemas.offline_recovery import RecoveryResolveRequest
from ..services import offline_recovery_service

router = APIRouter(prefix="/api/offline/recovery", tags=["offline-recovery"])

BODY_CAP_BYTES = 64 * 1024
LINE_CAP = 200
MEDIA_TYPE = "application/vnd.fselling.offline-recovery+json"


def _http_error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


async def _read_bounded(request: Request) -> bytes:
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            declared_size = int(declared, 10)
        except ValueError:
            declared_size = -1
        if declared_size > BODY_CAP_BYTES:
            raise _http_error(
                413,
                "OFFLINE_RECOVERY_BODY_TOO_LARGE",
                "Body vượt giới hạn 64 KiB",
            )
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > BODY_CAP_BYTES:
            raise _http_error(
                413,
                "OFFLINE_RECOVERY_BODY_TOO_LARGE",
                "Body vượt giới hạn 64 KiB",
            )
        body.extend(chunk)
    if body.count(b"\n") + 1 > LINE_CAP:
        raise _http_error(
            422,
            offline_recovery_service.ERROR_MALFORMED,
            "File phục hồi vượt giới hạn 200 dòng",
        )
    return bytes(body)


def _json_object(body: bytes) -> dict:
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _http_error(
            422,
            offline_recovery_service.ERROR_MALFORMED,
            "JSON phục hồi không hợp lệ",
        ) from exc
    if not isinstance(value, dict):
        raise _http_error(
            422,
            offline_recovery_service.ERROR_MALFORMED,
            "JSON phục hồi không hợp lệ",
        )
    return value


@router.post("/{shop_id}/export")
async def export_recovery_file(
    shop_id: int,
    request: Request,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Authorization happens before the ASGI stream is read.
    offline_recovery_service.authorize_recovery_shop(db, shop_id, current_user)
    raw = _json_object(await _read_bounded(request))
    if set(raw) != {"receipt"}:
        raise _http_error(
            422,
            offline_recovery_service.ERROR_MALFORMED,
            "Yêu cầu export phục hồi không hợp lệ",
        )
    document = offline_recovery_service.build_export_file(shop_id, raw["receipt"])
    return Response(
        content=document.file_bytes,
        media_type=MEDIA_TYPE,
        headers={
            "Content-Disposition": 'attachment; filename="offline-recovery-v1.json"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/{shop_id}/import")
async def import_recovery_file(
    shop_id: int,
    request: Request,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    offline_recovery_service.authorize_recovery_shop(db, shop_id, current_user)
    raw = _json_object(await _read_bounded(request))
    document = offline_recovery_service.parse_recovery_file(shop_id, raw)
    return offline_recovery_service.import_candidate(
        db, current_user, shop_id, document
    )


@router.get("/{shop_id}/candidates")
def get_recovery_candidates(
    shop_id: int,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10_000),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return offline_recovery_service.list_candidates(
        db,
        current_user,
        shop_id,
        limit=limit,
        offset=offset,
    )


@router.get("/{shop_id}/candidates/{offline_uuid}")
def get_recovery_candidate(
    shop_id: int,
    offline_uuid: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return offline_recovery_service.read_candidate(
        db, current_user, shop_id, offline_uuid
    )


@router.post("/{shop_id}/candidates/{offline_uuid}/resolve")
async def resolve_recovery_candidate(
    shop_id: int,
    offline_uuid: str,
    request: Request,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    offline_recovery_service.authorize_recovery_shop(db, shop_id, current_user)
    raw = _json_object(await _read_bounded(request))
    try:
        payload = RecoveryResolveRequest.model_validate(raw)
    except ValidationError as exc:
        raise _http_error(
            422,
            offline_recovery_service.ERROR_MALFORMED,
            "Yêu cầu resolve phục hồi không hợp lệ",
        ) from exc
    document = (
        offline_recovery_service.parse_recovery_file(shop_id, payload.document)
        if payload.document is not None
        else None
    )
    return offline_recovery_service.resolve_candidate(
        db,
        current_user,
        shop_id,
        offline_uuid,
        document,
        payload,
    )
