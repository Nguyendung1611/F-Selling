"""Owner-authorized recovery for frozen offline receipts (I09-G1).

The recovery file is an integrity envelope, not an authentication mechanism.
SHA-256 detects accidental damage; anybody who edits a file can recompute it.
Every operation still requires the current shop owner or global ADMIN JWT.

Import stores only bounded metadata and a content digest.  The raw document is
never persisted.  Resolution resubmits that document, creates a new immutable
receipt artifact, and tombstones the original UUID in the same transaction as
the order, payment, inventory, cost evidence, issues and transaction-local audit.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid as uuid_module
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import and_, exists, or_, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models
from ..core.i18n import tr
from ..core.money import checked_add, checked_multiply, exact_vnd
from ..schemas.offline_recovery import (
    RecoveryLineResolution,
    RecoveryReceiptV0,
    RecoveryReceiptV1,
    RecoveryResolveRequest,
)
from . import inventory_service, offline_service, order_service
from .offline_fingerprint import (
    OfflineFingerprintV0,
    OfflineFingerprintV1,
    OfflineTotalOverflowError,
    canonical_time_text,
    canonical_time_text_v1,
    fingerprint_offline_receipt_v0,
    fingerprint_offline_receipt_v1,
    normalize_text,
)

RECOVERY_FORMAT = "FS-OFFLINE-RECOVERY"
RECOVERY_FORMAT_VERSION = 1
MAX_RECOVERY_ITEMS = 200
MAX_PAGE_LIMIT = 100
MAX_PAGE_OFFSET = 10_000

STATE_ABANDONED = "ABANDONED"
STATE_SUPERSEDED = "SUPERSEDED"
STATE_INGESTED = "INGESTED"

ACTION_IMPORT = "IMPORT"
ACTION_CORRECT = "CORRECT"
ACTION_LEGACY_INGEST = "LEGACY_INGEST"

RESOLUTION_ACCEPT_UNKNOWN = "OWNER_ACCEPT_UNKNOWN_COST"
RESOLUTION_INFORMATIONAL = offline_service.RESOLUTION_INFORMATIONAL

ERROR_NOT_FOUND = "OFFLINE_RECOVERY_NOT_FOUND"
ERROR_MALFORMED = "OFFLINE_RECOVERY_MALFORMED"
ERROR_HASH_MISMATCH = "OFFLINE_RECOVERY_HASH_MISMATCH"
ERROR_VERSION_UNSUPPORTED = "OFFLINE_RECOVERY_VERSION_UNSUPPORTED"
ERROR_CONTENT_CONFLICT = "OFFLINE_RECOVERY_CONTENT_CONFLICT"
ERROR_STATE_CONFLICT = "OFFLINE_RECOVERY_STATE_CONFLICT"
ERROR_LINE_DECISION_REQUIRED = "OFFLINE_RECOVERY_LINE_DECISION_REQUIRED"
ERROR_LINE_DECISION_INVALID = "OFFLINE_RECOVERY_LINE_DECISION_INVALID"
ERROR_MAP_INVALID = "OFFLINE_RECOVERY_MAP_INVALID"
ERROR_ALREADY_INGESTED = "OFFLINE_RECOVERY_ALREADY_INGESTED"
ERROR_SEQUENCE_CONFLICT = "OFFLINE_RECOVERY_SEQUENCE_CONFLICT"
ERROR_TON_AM_FORBIDDEN = "OFFLINE_RECOVERY_TON_AM_FORBIDDEN"
ERROR_PREEXISTING_ORDER = "OFFLINE_RECOVERY_PREEXISTING_ORDER"


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": tr(message)})


def _not_found() -> HTTPException:
    # The same status/body is used for an unknown shop, STAFF, a cross-shop
    # candidate and an unknown candidate.  Nothing below leaks which one exists.
    return _error(404, ERROR_NOT_FOUND, "Không tìm thấy dữ liệu phục hồi")


def authorize_recovery_shop(
    db: Session, shop_id: int, current_user: models.User
) -> models.Shop:
    """Require the exact owner or global ADMIN without a shop-existence oracle."""
    shop = db.query(models.Shop).filter(models.Shop.id == int(shop_id)).first()
    allowed = bool(
        shop is not None
        and (
            current_user.role == "ADMIN"
            or int(shop.owner_id or 0) == int(current_user.id)
        )
    )
    if not allowed:
        raise _not_found()
    return shop


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


@dataclass(frozen=True)
class CanonicalRecoveryDocument:
    shop_id: int
    contract_version: int
    receipt: dict[str, Any]
    source_fingerprint: str
    content_sha256: str
    file_bytes: bytes
    canonical: OfflineFingerprintV0 | OfflineFingerprintV1

    @property
    def offline_uuid(self) -> str:
        return str(self.receipt["offline_uuid"])


def _canonicalize_receipt(shop_id: int, raw: Any) -> tuple[dict[str, Any], Any, str]:
    if not isinstance(raw, dict):
        raise _error(422, ERROR_MALFORMED, "Phiếu phục hồi không hợp lệ")
    version = raw.get("contract_version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise _error(422, ERROR_MALFORMED, "Phiếu phục hồi không hợp lệ")

    try:
        if version == 0:
            parsed = RecoveryReceiptV0.model_validate(raw)
            sold_at_text = canonical_time_text_v1(parsed.sold_at_utc)
            sold_at = datetime.strptime(sold_at_text, "%Y-%m-%d %H:%M:%S.%f")
            canonical = fingerprint_offline_receipt_v0(
                shop_id=int(shop_id),
                offline_uuid=parsed.offline_uuid,
                sold_at=sold_at,
                items=[item.model_dump() for item in parsed.items],
                cash_tendered_vnd=parsed.cash_tendered_vnd,
                # Device labels are intentionally stripped from recovery files.
                device_label=None,
            )
            receipt = {
                "contract_version": 0,
                "offline_uuid": canonical.offline_uuid,
                "sold_at_utc": canonical.sold_at_text,
                "items": [
                    {
                        "product_id": item.product_id,
                        "product_name": item.product_name,
                        "unit_price_vnd": item.unit_price_vnd,
                        "quantity": item.quantity,
                    }
                    for item in canonical.items
                ],
                "cash_tendered_vnd": int(parsed.cash_tendered_vnd),
            }
            return receipt, canonical, canonical.fingerprint

        if version == 1:
            parsed = RecoveryReceiptV1.model_validate(raw)
            canonical = fingerprint_offline_receipt_v1(
                shop_id=int(shop_id),
                sold_at_client_utc=parsed.sold_at_client_utc,
                client_monotonic_ms=parsed.client_monotonic_ms,
                monotonic_valid=parsed.monotonic_valid,
                server_anchor_id=parsed.server_anchor_id,
                lease_id=parsed.lease_id,
                device_id=parsed.device_id,
                offline_session_id=parsed.offline_session_id,
                sequence=parsed.sequence,
                offline_uuid=parsed.offline_uuid,
                catalog_version=parsed.catalog_version,
                catalog_snapshot_digest=parsed.catalog_snapshot_digest,
                items=[item.model_dump() for item in parsed.items],
                cash_tendered_vnd=parsed.cash_tendered_vnd,
            )
            receipt = {
                "contract_version": 1,
                "lease_id": parsed.lease_id,
                "device_id": parsed.device_id,
                "offline_session_id": parsed.offline_session_id,
                "sequence": parsed.sequence,
                "offline_uuid": canonical.offline_uuid,
                "sold_at_client_utc": canonical.sold_at_client_utc,
                "client_monotonic_ms": canonical.client_monotonic_ms,
                "monotonic_valid": parsed.monotonic_valid,
                "server_anchor_id": canonical.server_anchor_id,
                "catalog_version": canonical.catalog_version,
                "catalog_snapshot_digest": canonical.catalog_snapshot_digest,
                "items": [
                    {
                        "product_id": item.product_id,
                        "product_name": item.product_name,
                        "unit_price_vnd": item.unit_price_vnd,
                        "quantity": item.quantity,
                    }
                    for item in canonical.items
                ],
                "cash_tendered_vnd": canonical.cash_tendered_vnd,
            }
            return receipt, canonical, canonical.digest
    except OfflineTotalOverflowError as exc:
        raise _error(400, "OFFLINE_TOTAL_OVERFLOW", "Tổng tiền phiếu vượt giới hạn") from exc
    except (ValidationError, TypeError, ValueError, KeyError) as exc:
        raise _error(422, ERROR_MALFORMED, "Phiếu phục hồi không hợp lệ") from exc

    raise _error(
        422,
        ERROR_VERSION_UNSUPPORTED,
        "Phiên bản file phục hồi không được hỗ trợ",
    )


def build_export_file(shop_id: int, raw_receipt: Any) -> CanonicalRecoveryDocument:
    receipt, canonical, source_fingerprint = _canonicalize_receipt(shop_id, raw_receipt)
    core = {
        "format": RECOVERY_FORMAT,
        "payload": {"receipt": receipt, "shop_id": int(shop_id)},
        "version": RECOVERY_FORMAT_VERSION,
    }
    digest = _sha256(_canonical_json_bytes(core))
    full = dict(core)
    full["sha256"] = digest
    return CanonicalRecoveryDocument(
        shop_id=int(shop_id),
        contract_version=int(receipt["contract_version"]),
        receipt=receipt,
        source_fingerprint=source_fingerprint,
        content_sha256=digest,
        file_bytes=_canonical_json_bytes(full),
        canonical=canonical,
    )


def parse_recovery_file(shop_id: int, raw: Any) -> CanonicalRecoveryDocument:
    if not isinstance(raw, dict):
        raise _error(422, ERROR_MALFORMED, "File phục hồi không hợp lệ")
    if raw.get("format") != RECOVERY_FORMAT:
        raise _error(422, ERROR_MALFORMED, "File phục hồi không hợp lệ")
    version = raw.get("version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise _error(422, ERROR_MALFORMED, "File phục hồi không hợp lệ")
    if version != RECOVERY_FORMAT_VERSION:
        raise _error(
            422,
            ERROR_VERSION_UNSUPPORTED,
            "Phiên bản file phục hồi không được hỗ trợ",
        )
    if set(raw) != {"format", "payload", "sha256", "version"}:
        raise _error(422, ERROR_MALFORMED, "File phục hồi không hợp lệ")
    payload = raw.get("payload")
    if not isinstance(payload, dict) or set(payload) != {"receipt", "shop_id"}:
        raise _error(422, ERROR_MALFORMED, "File phục hồi không hợp lệ")
    payload_shop = payload.get("shop_id")
    if (
        isinstance(payload_shop, bool)
        or not isinstance(payload_shop, int)
        or payload_shop != int(shop_id)
    ):
        raise _not_found()

    canonical = build_export_file(shop_id, payload.get("receipt"))
    supplied = raw.get("sha256")
    if (
        not isinstance(supplied, str)
        or len(supplied) != 64
        or any(ch not in "0123456789abcdef" for ch in supplied)
        or not hmac.compare_digest(supplied, canonical.content_sha256)
    ):
        raise _error(
            422,
            ERROR_HASH_MISMATCH,
            "Checksum file phục hồi không khớp",
        )
    return canonical


def _recovery_checkpoint(_name: str) -> None:
    """Fault-injection seam used by transaction rollback regressions."""


def _add_recovery_action(
    db: Session,
    *,
    shop_id: int,
    actor_user_id: int,
    action_kind: str,
    original_uuid: str,
    original_fingerprint: str,
    replacement_uuid: Optional[str],
    digest: str,
    reason: str,
    performed_at: str,
    audit_details: str,
) -> models.OfflineRecoveryAction:
    log = models.SystemLog(
        user_id=int(actor_user_id),
        shop_id=int(shop_id),
        action=f"OFFLINE_RECOVERY_{action_kind}",
        details=audit_details,
    )
    db.add(log)
    db.flush()
    action = models.OfflineRecoveryAction(
        shop_id=int(shop_id),
        action_kind=action_kind,
        original_offline_uuid=original_uuid,
        original_fingerprint=original_fingerprint,
        replacement_offline_uuid=replacement_uuid,
        file_digest=digest,
        reason=reason,
        performed_by_user_id=int(actor_user_id),
        performed_at=performed_at,
        system_log_id=int(log.id),
    )
    db.add(action)
    db.flush()
    return action


def _import_action(db: Session, shop_id: int, offline_uuid: str):
    return (
        db.query(models.OfflineRecoveryAction)
        .filter(
            models.OfflineRecoveryAction.shop_id == int(shop_id),
            models.OfflineRecoveryAction.original_offline_uuid == offline_uuid,
            models.OfflineRecoveryAction.action_kind == ACTION_IMPORT,
        )
        .order_by(models.OfflineRecoveryAction.id.asc())
        .first()
    )


def _fence_pre_registry_order(
    db: Session,
    *,
    shop_id: int,
    offline_uuid: str,
    registry: Optional[models.OfflineReceiptRegistry],
) -> Optional[models.Order]:
    """Fence durable legacy financial history that predates receipt evidence.

    An Order without registry/receipt cannot prove compatibility with an
    owner-supplied recovery file.  It is therefore never staged or replaced.
    """

    order = (
        db.query(models.Order)
        .filter(models.Order.offline_uuid == offline_uuid)
        .first()
    )
    if order is not None and int(order.shop_id) != int(shop_id):
        raise _not_found()
    if order is not None and (
        registry is None
        or registry.state != STATE_INGESTED
        or registry.order_id != order.id
    ):
        raise _error(
            409,
            ERROR_PREEXISTING_ORDER,
            "Phiếu đã có giao dịch tài chính nhưng thiếu bằng chứng để đối chiếu",
        )
    return order


def _candidate_payload(
    db: Session, registry: models.OfflineReceiptRegistry
) -> dict[str, Any]:
    imported = _import_action(db, int(registry.shop_id), registry.offline_uuid)
    if imported is None:
        raise _error(
            409,
            ERROR_STATE_CONFLICT,
            "Dữ liệu phục hồi không nhất quán",
        )
    order_id = None
    if registry.superseded_by_offline_uuid:
        replacement = db.get(
            models.OfflineReceiptRegistry, registry.superseded_by_offline_uuid
        )
        if replacement is None or int(replacement.shop_id) != int(registry.shop_id):
            raise _error(409, ERROR_STATE_CONFLICT, "Dữ liệu phục hồi không nhất quán")
        order_id = replacement.order_id
    return {
        "offline_uuid": registry.offline_uuid,
        "contract_version": int(registry.contract_version),
        "state": registry.state,
        "state_version": int(registry.state_version),
        "content_sha256": imported.file_digest,
        "replacement_offline_uuid": registry.superseded_by_offline_uuid,
        "order_id": order_id,
        "created_at": registry.created_at,
        "updated_at": registry.updated_at,
    }


def _ingested_v0_candidate_payload(
    db: Session, registry: models.OfflineReceiptRegistry
) -> dict[str, Any]:
    """Sanitized read model for an already-ingested legacy catalog issue.

    This is not an import candidate and deliberately contains no recovery file,
    digest, lease credential, or recomputed financial values.  It only makes the
    G1 direct MAP/ACCEPT path discoverable to an authorized owner UI.
    """
    receipt = (
        db.query(models.OfflineReceipt)
        .filter(models.OfflineReceipt.offline_uuid == registry.offline_uuid)
        .first()
    )
    order = db.get(models.Order, registry.order_id)
    if receipt is None or order is None or not offline_service._receipt_v0_consistent(
        order, registry, receipt
    ):
        raise _error(409, ERROR_STATE_CONFLICT, "Dữ liệu phục hồi không nhất quán")
    issues = (
        db.query(models.OfflineReceiptIssue)
        .filter(
            models.OfflineReceiptIssue.order_id == int(order.id),
            models.OfflineReceiptIssue.issue_code == offline_service.ISSUE_SP_KHONG_CON,
            models.OfflineReceiptIssue.state == offline_service.STATE_OPEN,
        )
        .order_by(models.OfflineReceiptIssue.order_item_id.asc(), models.OfflineReceiptIssue.id.asc())
        .all()
    )
    order_lines = (
        db.query(models.OrderItem)
        .filter(models.OrderItem.order_id == int(order.id))
        .order_by(models.OrderItem.id.asc())
        .all()
    )
    lines_by_id = {int(row.id): (index + 1, row) for index, row in enumerate(order_lines)}
    return {
        "offline_uuid": registry.offline_uuid,
        "contract_version": 0,
        "state": STATE_INGESTED,
        "state_version": int(registry.state_version),
        "order_id": int(order.id),
        "created_at": registry.created_at,
        "updated_at": registry.updated_at,
        "time_confidence": receipt.time_confidence,
        "direct_legacy_resolution": True,
        "issues": [
            {
                "id": int(issue.id),
                "code": issue.issue_code,
                "state": issue.state,
                "state_version": int(issue.state_version),
                "item_ordinal": lines_by_id[int(issue.order_item_id)][0]
                if issue.order_item_id in lines_by_id else 0,
                "product_name": lines_by_id[int(issue.order_item_id)][1].product_name
                if issue.order_item_id in lines_by_id else "",
            }
            for issue in issues
        ],
    }


def import_candidate(
    db: Session,
    current_user: models.User,
    shop_id: int,
    document: CanonicalRecoveryDocument,
) -> dict[str, Any]:
    actor_id = int(current_user.id)
    db.rollback()
    try:
        order_service._lock_shop_for_order(db, int(shop_id))
        authorize_recovery_shop(db, shop_id, current_user)

        if document.contract_version == 1:
            lease = db.get(models.OfflineLease, document.receipt["lease_id"])
            if lease is None or int(lease.shop_id) != int(shop_id):
                raise _not_found()

        registry = db.get(models.OfflineReceiptRegistry, document.offline_uuid)
        _fence_pre_registry_order(
            db,
            shop_id=shop_id,
            offline_uuid=document.offline_uuid,
            registry=registry,
        )
        if registry is not None and int(registry.shop_id) != int(shop_id):
            raise _not_found()
        if registry is not None:
            imported = _import_action(db, shop_id, document.offline_uuid)
            if (
                imported is None
                or imported.file_digest != document.content_sha256
                or registry.server_fingerprint != document.source_fingerprint
                or int(registry.contract_version) != document.contract_version
            ):
                raise _error(
                    409,
                    ERROR_CONTENT_CONFLICT,
                    "UUID phục hồi đã gắn với nội dung khác",
                )
            if registry.state in (STATE_ABANDONED, STATE_SUPERSEDED):
                response = _candidate_payload(db, registry)
                response["created"] = False
                db.rollback()
                return response
            if registry.state == STATE_INGESTED:
                raise _error(
                    409,
                    ERROR_ALREADY_INGESTED,
                    "Phiếu đã được ghi nhận trước khi phục hồi",
                )
            raise _error(409, ERROR_STATE_CONFLICT, "Trạng thái phục hồi không hợp lệ")

        now_text = canonical_time_text(datetime.utcnow())
        registry = models.OfflineReceiptRegistry(
            offline_uuid=document.offline_uuid,
            shop_id=int(shop_id),
            order_id=None,
            server_fingerprint=document.source_fingerprint,
            contract_version=document.contract_version,
            state=STATE_ABANDONED,
            superseded_by_offline_uuid=None,
            created_at=now_text,
            updated_at=now_text,
            state_version=0,
        )
        db.add(registry)
        db.flush()
        _add_recovery_action(
            db,
            shop_id=shop_id,
            actor_user_id=actor_id,
            action_kind=ACTION_IMPORT,
            original_uuid=document.offline_uuid,
            original_fingerprint=document.source_fingerprint,
            replacement_uuid=None,
            digest=document.content_sha256,
            reason="Owner recovery import",
            performed_at=now_text,
            audit_details=f"Imported offline recovery candidate contract v{document.contract_version}",
        )
        _recovery_checkpoint("import_before_commit")
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(registry)
    response = _candidate_payload(db, registry)
    response["created"] = True
    return response


def list_candidates(
    db: Session,
    current_user: models.User,
    shop_id: int,
    *,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    authorize_recovery_shop(db, shop_id, current_user)
    if not 1 <= int(limit) <= MAX_PAGE_LIMIT or not 0 <= int(offset) <= MAX_PAGE_OFFSET:
        raise _error(422, ERROR_MALFORMED, "Phân trang phục hồi không hợp lệ")
    imported_exists = exists().where(
        models.OfflineRecoveryAction.shop_id == int(shop_id),
        models.OfflineRecoveryAction.original_offline_uuid
        == models.OfflineReceiptRegistry.offline_uuid,
        models.OfflineRecoveryAction.action_kind == ACTION_IMPORT,
    )
    open_catalog_issue_exists = exists().where(
        models.OfflineReceiptIssue.order_id
        == models.OfflineReceiptRegistry.order_id,
        models.OfflineReceiptIssue.issue_code == offline_service.ISSUE_SP_KHONG_CON,
        models.OfflineReceiptIssue.state == offline_service.STATE_OPEN,
    )
    # One bounded registry query is deliberately used for both candidate kinds.
    # EXISTS avoids multiplying a receipt that has several open catalog issues.
    rows = (
        db.query(models.OfflineReceiptRegistry)
        .filter(
            models.OfflineReceiptRegistry.shop_id == int(shop_id),
            or_(
                and_(
                    models.OfflineReceiptRegistry.state.in_(
                        (STATE_ABANDONED, STATE_SUPERSEDED)
                    ),
                    imported_exists,
                ),
                and_(
                    models.OfflineReceiptRegistry.state == STATE_INGESTED,
                    models.OfflineReceiptRegistry.contract_version == 0,
                    open_catalog_issue_exists,
                ),
            ),
        )
        .order_by(
            models.OfflineReceiptRegistry.updated_at.desc(),
            models.OfflineReceiptRegistry.offline_uuid.asc(),
        )
        .offset(int(offset))
        .limit(int(limit) + 1)
        .all()
    )
    has_more = len(rows) > int(limit)
    rows = rows[: int(limit)]
    return {
        "items": [
            _ingested_v0_candidate_payload(db, row)
            if row.state == STATE_INGESTED
            else _candidate_payload(db, row)
            for row in rows
        ],
        "limit": int(limit),
        "offset": int(offset),
        "next_offset": int(offset) + len(rows) if has_more else None,
    }


def read_candidate(
    db: Session,
    current_user: models.User,
    shop_id: int,
    offline_uuid: str,
) -> dict[str, Any]:
    authorize_recovery_shop(db, shop_id, current_user)
    registry = (
        db.query(models.OfflineReceiptRegistry)
        .filter(
            models.OfflineReceiptRegistry.offline_uuid == offline_uuid,
            models.OfflineReceiptRegistry.shop_id == int(shop_id),
            models.OfflineReceiptRegistry.state.in_(
                (STATE_ABANDONED, STATE_SUPERSEDED, STATE_INGESTED)
            ),
        )
        .first()
    )
    if registry is None:
        raise _not_found()
    if registry.state == STATE_INGESTED:
        payload = _ingested_v0_candidate_payload(db, registry)
        if not payload["issues"]:
            raise _not_found()
        return payload
    if _import_action(db, shop_id, offline_uuid) is None:
        raise _not_found()
    return _candidate_payload(db, registry)


def _normalize_reason(reason: str) -> str:
    try:
        normalized = normalize_text(reason)
    except ValueError as exc:
        raise _error(422, ERROR_MALFORMED, "Lý do phục hồi không hợp lệ") from exc
    if not 10 <= len(normalized) <= 500:
        raise _error(422, ERROR_MALFORMED, "Lý do phục hồi phải có 10-500 ký tự")
    return normalized


def _resolution_map(
    resolutions: list[RecoveryLineResolution], item_count: int
) -> dict[int, RecoveryLineResolution]:
    result: dict[int, RecoveryLineResolution] = {}
    for resolution in resolutions:
        ordinal = int(resolution.item_ordinal)
        if ordinal > item_count or ordinal in result:
            raise _error(422, ERROR_LINE_DECISION_INVALID, "Quyết định dòng không hợp lệ")
        if resolution.action == "MAP" and resolution.product_id is None:
            raise _error(422, ERROR_LINE_DECISION_INVALID, "Map sản phẩm cần product_id")
        if resolution.action == "ACCEPT_UNKNOWN" and resolution.product_id is not None:
            raise _error(422, ERROR_LINE_DECISION_INVALID, "Accept unknown không nhận product_id")
        result[ordinal] = resolution
    return result


def _intent_digest(
    document: CanonicalRecoveryDocument,
    reason: str,
    resolutions: dict[int, RecoveryLineResolution],
    sold_at_effective: str,
) -> str:
    material = {
        "content_sha256": document.content_sha256,
        "line_resolutions": [
            {
                "action": resolutions[key].action,
                "item_ordinal": key,
                "product_id": resolutions[key].product_id,
            }
            for key in sorted(resolutions)
        ],
        "reason": reason,
        "sold_at_effective_utc": sold_at_effective,
    }
    return _sha256(_canonical_json_bytes(material))


def _in_place_intent_digest(
    *,
    durable_fingerprint: str,
    reason: str,
    resolutions: dict[int, RecoveryLineResolution],
    sold_at_effective: str,
) -> str:
    material = {
        "durable_fingerprint": durable_fingerprint,
        "line_resolutions": [
            {
                "action": resolutions[key].action,
                "item_ordinal": key,
                "product_id": resolutions[key].product_id,
            }
            for key in sorted(resolutions)
        ],
        "reason": reason,
        "sold_at_effective_utc": sold_at_effective,
    }
    return _sha256(_canonical_json_bytes(material))


def _verified_product(
    db: Session, shop_id: int, product_id: int
) -> Optional[models.Product]:
    return (
        db.query(models.Product)
        .filter(
            models.Product.id == int(product_id),
            models.Product.shop_id == int(shop_id),
            models.Product.is_active.is_(True),
        )
        .first()
    )


def _claimed_product(db: Session, product_id: int) -> Optional[models.Product]:
    """Read claimed identity without treating cross-shop/inactive as sellable."""

    return db.get(models.Product, int(product_id))


def _build_recovered_lines(
    db: Session,
    *,
    shop_id: int,
    items: list[dict[str, Any]],
    resolutions: dict[int, RecoveryLineResolution],
) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    for ordinal, item in enumerate(items, start=1):
        claimed = _claimed_product(db, int(item["product_id"]))
        existing = (
            claimed
            if claimed is not None
            and int(claimed.shop_id) == int(shop_id)
            and bool(claimed.is_active)
            else None
        )
        decision = resolutions.get(ordinal)
        accepted_unknown = False
        order_item_product_id: Optional[int] = None
        if decision is not None and decision.action == "MAP":
            product = _verified_product(db, shop_id, int(decision.product_id))
            if product is None:
                raise _error(409, ERROR_MAP_INVALID, "Sản phẩm map không hợp lệ")
            order_item_product_id = int(product.id)
        elif decision is not None and decision.action == "ACCEPT_UNKNOWN":
            if existing is not None:
                raise _error(
                    409,
                    ERROR_LINE_DECISION_INVALID,
                    "Không thể bỏ giá vốn của sản phẩm còn hợp lệ",
                )
            product = None
            accepted_unknown = True
            # Verifier 0006 requires an existing same-shop claimed identity to
            # remain in the business FK even when inactive.  It is identity
            # only: ``product`` stays None, so no inventory/cost path runs.
            if claimed is not None and int(claimed.shop_id) == int(shop_id):
                order_item_product_id = int(claimed.id)
        elif existing is None:
            raise _error(
                409,
                ERROR_LINE_DECISION_REQUIRED,
                "Dòng thiếu sản phẩm cần map hoặc accept unknown",
            )
        else:
            product = existing
            order_item_product_id = int(product.id)

        if product is not None:
            try:
                product_name = normalize_text(product.name)
            except ValueError as exc:
                raise _error(409, ERROR_MAP_INVALID, "Tên sản phẩm server không hợp lệ") from exc
            if not product_name:
                raise _error(409, ERROR_MAP_INVALID, "Tên sản phẩm server không hợp lệ")
            corrected_product_id = int(product.id)
        else:
            # Historical label only.  It is never used to resolve identity or cost.
            product_name = str(item["product_name"])
            corrected_product_id = int(item["product_id"])

        lines.append(
            {
                "ordinal": ordinal,
                "product": product,
                "order_item_product_id": order_item_product_id,
                "accepted_unknown": accepted_unknown,
                "product_id": corrected_product_id,
                "product_name": product_name,
                "unit_price_vnd": int(item["unit_price_vnd"]),
                "quantity": int(item["quantity"]),
            }
        )
    return lines


def _existing_resolution_response(
    db: Session,
    *,
    shop_id: int,
    original: models.OfflineReceiptRegistry,
    intent_digest: str,
) -> dict[str, Any]:
    action = (
        db.query(models.OfflineRecoveryAction)
        .filter(
            models.OfflineRecoveryAction.shop_id == int(shop_id),
            models.OfflineRecoveryAction.original_offline_uuid == original.offline_uuid,
            models.OfflineRecoveryAction.action_kind == ACTION_CORRECT,
        )
        .order_by(models.OfflineRecoveryAction.id.asc())
        .first()
    )
    if (
        action is None
        or action.file_digest != intent_digest
        or action.replacement_offline_uuid != original.superseded_by_offline_uuid
    ):
        raise _error(409, ERROR_STATE_CONFLICT, "Phiếu đã được phục hồi bằng quyết định khác")
    replacement = db.get(
        models.OfflineReceiptRegistry, original.superseded_by_offline_uuid
    )
    if (
        replacement is None
        or replacement.state != STATE_INGESTED
        or int(replacement.shop_id) != int(shop_id)
        or replacement.order_id is None
    ):
        raise _error(409, ERROR_STATE_CONFLICT, "Dữ liệu phục hồi không nhất quán")
    order = db.get(models.Order, replacement.order_id)
    receipt = (
        db.query(models.OfflineReceipt)
        .filter(models.OfflineReceipt.offline_uuid == replacement.offline_uuid)
        .first()
    )
    if order is None or receipt is None:
        raise _error(409, ERROR_STATE_CONFLICT, "Dữ liệu phục hồi không nhất quán")
    consistent = (
        offline_service._receipt_v0_consistent(order, replacement, receipt)
        if int(replacement.contract_version) == 0
        else offline_service._receipt_v1_consistent(db, order, replacement, receipt)
    )
    if not consistent:
        raise _error(409, ERROR_STATE_CONFLICT, "Dữ liệu phục hồi không nhất quán")
    return {
        "offline_uuid": original.offline_uuid,
        "state": STATE_SUPERSEDED,
        "state_version": int(original.state_version),
        "replacement_offline_uuid": replacement.offline_uuid,
        "order_id": int(order.id),
        "contract_version": int(replacement.contract_version),
        "recovery_digest": intent_digest,
        "created": False,
    }


def _in_place_action(
    db: Session, shop_id: int, offline_uuid: str
) -> Optional[models.OfflineRecoveryAction]:
    rows = (
        db.query(models.OfflineRecoveryAction)
        .filter(
            models.OfflineRecoveryAction.shop_id == int(shop_id),
            models.OfflineRecoveryAction.original_offline_uuid == offline_uuid,
            models.OfflineRecoveryAction.action_kind == ACTION_LEGACY_INGEST,
        )
        .order_by(models.OfflineRecoveryAction.id.asc())
        .all()
    )
    if len(rows) > 1:
        raise _error(409, ERROR_STATE_CONFLICT, "Dữ liệu phục hồi bị trùng quyết định")
    return rows[0] if rows else None


def _in_place_response(
    *,
    registry: models.OfflineReceiptRegistry,
    order: models.Order,
    intent_digest: str,
) -> dict[str, Any]:
    return {
        "offline_uuid": registry.offline_uuid,
        "state": STATE_INGESTED,
        "state_version": int(registry.state_version),
        "replacement_offline_uuid": None,
        "order_id": int(order.id),
        "contract_version": 0,
        "recovery_digest": intent_digest,
        "created": False,
    }


def _durable_v0_order_lines(
    db: Session,
    *,
    order: models.Order,
    document: Optional[CanonicalRecoveryDocument],
) -> list[models.OrderItem]:
    lines = (
        db.query(models.OrderItem)
        .filter(models.OrderItem.order_id == int(order.id))
        .order_by(models.OrderItem.id.asc())
        .all()
    )
    total = 0
    if not 1 <= len(lines) <= MAX_RECOVERY_ITEMS:
        raise _error(409, ERROR_STATE_CONFLICT, "Số dòng đơn đã ghi không hợp lệ")
    canonical_items = document.canonical.items if document is not None else None
    if canonical_items is not None and len(lines) != len(canonical_items):
        raise _error(409, ERROR_CONTENT_CONFLICT, "Dòng hàng phục hồi không khớp đơn")
    for ordinal, line in enumerate(lines):
        line_total = checked_multiply(int(line.quantity), int(line.price))
        total = checked_add(total, line_total)
        if int(line.net_amount_vnd) != line_total:
            raise _error(409, ERROR_STATE_CONFLICT, "Dòng đơn đã ghi không nhất quán")
        if canonical_items is not None:
            item = canonical_items[ordinal]
            if (
                line.product_name != item.product_name
                or int(line.price) != int(item.unit_price_vnd)
                or int(line.quantity) != int(item.quantity)
            ):
                raise _error(
                    409, ERROR_CONTENT_CONFLICT, "Dòng hàng phục hồi không khớp đơn"
                )
            raise _error(409, ERROR_CONTENT_CONFLICT, "Dòng hàng phục hồi không khớp đơn")
    if total != int(order.total_amount):
        raise _error(409, ERROR_CONTENT_CONFLICT, "Tổng phục hồi không khớp đơn")
    return lines


def _append_mapped_inventory(
    db: Session,
    *,
    order: models.Order,
    order_item: models.OrderItem,
    product: models.Product,
    quantity: int,
    now_text: str,
) -> tuple[int, int, int]:
    allocations, shortage = offline_service._tru_ton_chiu_thieu(
        db, product, int(quantity)
    )
    known_qty, allocated_unknown_qty, cost_basis = (
        inventory_service.allocation_totals(allocations)
    )
    allocated_qty = sum(allocation.quantity for allocation in allocations)
    unallocated_qty = max(int(quantity) - allocated_qty, 0)
    unknown_qty = allocated_unknown_qty + unallocated_qty

    if product.track_batches:
        for allocation in allocations:
            if allocation.batch is None:
                raise _error(409, ERROR_STATE_CONFLICT, "Thiếu provenance lô phục hồi")
            db.add(
                models.OrderItemBatch(
                    order_item_id=int(order_item.id),
                    batch_id=int(allocation.batch.id),
                    quantity=allocation.quantity,
                    cost_known_qty=allocation.known_qty,
                    cost_unknown_qty=allocation.unknown_qty,
                    cost_basis_vnd=allocation.cost_basis_vnd,
                )
            )
        if unallocated_qty > 0:
            deficit = models.OfflineBatchStockDeficit(
                order_item_id=int(order_item.id),
                product_id=int(product.id),
                deficit_quantity=unallocated_qty,
                remaining_quantity=unallocated_qty,
                state_version=0,
            )
            db.add(deficit)
            db.flush()
            db.add(
                offline_service._issue_moi(
                    order_id=int(order.id),
                    issue_code=offline_service.ISSUE_TON_AM,
                    evidence_kind=offline_service.EVIDENCE_BATCH_DEFICIT,
                    severity=offline_service.SEVERITY_ACTION,
                    opened_at=now_text,
                    order_item_id=int(order_item.id),
                    product_id=int(product.id),
                    evidence_id=int(deficit.id),
                )
            )
    elif shortage > 0:
        deficit = models.OfflineStockDeficit(
            order_item_id=int(order_item.id),
            product_id=int(product.id),
            deficit_quantity=shortage,
            remaining_quantity=shortage,
            state_version=0,
        )
        db.add(deficit)
        db.flush()
        db.add(
            offline_service._issue_moi(
                order_id=int(order.id),
                issue_code=offline_service.ISSUE_TON_AM,
                evidence_kind=offline_service.EVIDENCE_STOCK_DEFICIT,
                severity=offline_service.SEVERITY_ACTION,
                opened_at=now_text,
                order_item_id=int(order_item.id),
                product_id=int(product.id),
                evidence_id=int(deficit.id),
            )
        )
    if shortage > 0:
        codes = [code for code in (order.offline_issue or "").split(",") if code]
        if offline_service.ISSUE_TON_AM not in codes:
            codes.append(offline_service.ISSUE_TON_AM)
            order.offline_issue = ",".join(codes)
    return known_qty, unknown_qty, cost_basis


def _resolve_ingested_v0_catalog(
    db: Session,
    *,
    current_user: models.User,
    shop_id: int,
    registry: models.OfflineReceiptRegistry,
    document: Optional[CanonicalRecoveryDocument],
    payload: RecoveryResolveRequest,
    reason: str,
    resolutions: dict[int, RecoveryLineResolution],
    effective: str,
    intent_digest: str,
) -> tuple[dict[str, Any], bool]:
    """Resolve normal-ingested v0 catalog issues without new revenue rows."""

    order = db.get(models.Order, registry.order_id)
    receipt = (
        db.query(models.OfflineReceipt)
        .filter(models.OfflineReceipt.offline_uuid == registry.offline_uuid)
        .first()
    )
    if (
        int(registry.contract_version) != 0
        or order is None
        or receipt is None
        or not offline_service._receipt_v0_consistent(order, registry, receipt)
        or document is not None
        and (
            document.contract_version != 0
            or registry.server_fingerprint != document.source_fingerprint
        )
        or effective != receipt.sold_at_effective
        or order.status != order_service.STATUS_PAID
    ):
        raise _error(409, ERROR_CONTENT_CONFLICT, "Phiếu đã ghi không khớp phục hồi")

    payments = (
        db.query(models.OrderPayment)
        .filter(models.OrderPayment.idempotency_key == f"offline:{registry.offline_uuid}")
        .all()
    )
    if (
        len(payments) != 1
        or payments[0].order_id != order.id
        or payments[0].entry_type != offline_service.ENTRY_SALE_CASH
        or int(payments[0].amount) != int(order.total_amount)
    ):
        raise _error(409, ERROR_STATE_CONFLICT, "Ledger phiếu đã ghi không nhất quán")

    action = _in_place_action(db, shop_id, registry.offline_uuid)
    if action is not None:
        if action.file_digest != intent_digest:
            raise _error(409, ERROR_STATE_CONFLICT, "Phiếu đã được xử lý bằng quyết định khác")
        open_catalog = (
            db.query(models.OfflineReceiptIssue.id)
            .filter(
                models.OfflineReceiptIssue.order_id == int(order.id),
                models.OfflineReceiptIssue.issue_code == offline_service.ISSUE_SP_KHONG_CON,
                models.OfflineReceiptIssue.state == offline_service.STATE_OPEN,
            )
            .first()
        )
        if open_catalog is not None:
            raise _error(409, ERROR_STATE_CONFLICT, "Quyết định phục hồi chưa hoàn tất")
        return _in_place_response(
            registry=registry, order=order, intent_digest=intent_digest
        ), False

    if int(registry.state_version) != int(payload.state_version):
        raise _error(409, ERROR_STATE_CONFLICT, "Candidate đã đổi phiên bản")

    lines = _durable_v0_order_lines(db, order=order, document=document)
    issues = (
        db.query(models.OfflineReceiptIssue)
        .filter(
            models.OfflineReceiptIssue.order_id == int(order.id),
            models.OfflineReceiptIssue.issue_code == offline_service.ISSUE_SP_KHONG_CON,
            models.OfflineReceiptIssue.state == offline_service.STATE_OPEN,
        )
        .order_by(models.OfflineReceiptIssue.id.asc())
        .all()
    )
    if not issues:
        has_exact_deficit = (
            db.query(models.OfflineReceiptIssue.id)
            .filter(
                models.OfflineReceiptIssue.order_id == int(order.id),
                models.OfflineReceiptIssue.issue_code == offline_service.ISSUE_TON_AM,
                models.OfflineReceiptIssue.evidence_kind.in_(
                    (
                        offline_service.EVIDENCE_STOCK_DEFICIT,
                        offline_service.EVIDENCE_BATCH_DEFICIT,
                    )
                ),
                models.OfflineReceiptIssue.state == offline_service.STATE_OPEN,
            )
            .first()
        )
        if has_exact_deficit is not None:
            raise _error(
                409,
                ERROR_TON_AM_FORBIDDEN,
                "TON_AM exact chỉ được giải bằng kiểm kê có snapshot/CAS",
            )
        raise _error(409, ERROR_ALREADY_INGESTED, "Phiếu đã được ghi nhận")

    ordinal_by_item_id = {int(line.id): ordinal for ordinal, line in enumerate(lines, 1)}
    issue_by_ordinal: dict[int, models.OfflineReceiptIssue] = {}
    for issue in issues:
        ordinal = ordinal_by_item_id.get(int(issue.order_item_id or 0))
        if ordinal is None or ordinal in issue_by_ordinal:
            raise _error(409, ERROR_STATE_CONFLICT, "Catalog issue không nhất quán")
        issue_by_ordinal[ordinal] = issue
    if set(resolutions) != set(issue_by_ordinal):
        raise _error(
            409,
            ERROR_LINE_DECISION_REQUIRED,
            "Mỗi dòng SP_KHONG_CON cần đúng một quyết định",
        )

    now_text = canonical_time_text(datetime.utcnow())
    for ordinal in sorted(issue_by_ordinal):
        issue = issue_by_ordinal[ordinal]
        line = lines[ordinal - 1]
        item = (
            document.receipt["items"][ordinal - 1]
            if document is not None
            else None
        )
        decision = resolutions[ordinal]
        if (
            line.product_id is not None
            or int(line.cost_known_qty or 0) != 0
            or int(line.cost_unknown_qty or 0) != int(line.quantity)
            or int(line.cost_basis_vnd or 0) != 0
            or int(line.returned_total_qty or 0) != 0
            or db.query(models.OrderItemBatch.id)
            .filter(models.OrderItemBatch.order_item_id == int(line.id))
            .first()
            is not None
        ):
            raise _error(409, ERROR_STATE_CONFLICT, "Dòng catalog đã có provenance khác")

        claimed = (
            _claimed_product(db, int(item["product_id"]))
            if item is not None
            else None
        )
        target_product_id: Optional[int]
        known_qty = 0
        unknown_qty = int(line.quantity)
        cost_basis = 0
        resolution_kind: str
        if decision.action == "MAP":
            product = _verified_product(db, shop_id, int(decision.product_id))
            if product is None:
                raise _error(409, ERROR_MAP_INVALID, "Sản phẩm map không hợp lệ")
            target_product_id = int(product.id)
            known_qty, unknown_qty, cost_basis = _append_mapped_inventory(
                db,
                order=order,
                order_item=line,
                product=product,
                quantity=int(line.quantity),
                now_text=now_text,
            )
            resolution_kind = "OWNER_MAP_PRODUCT"
        else:
            if (
                claimed is not None
                and int(claimed.shop_id) == int(shop_id)
                and bool(claimed.is_active)
            ):
                raise _error(
                    409,
                    ERROR_LINE_DECISION_INVALID,
                    "Không thể bỏ giá vốn của sản phẩm còn hợp lệ",
                )
            target_product_id = (
                int(claimed.id)
                if claimed is not None and int(claimed.shop_id) == int(shop_id)
                else None
            )
            resolution_kind = RESOLUTION_ACCEPT_UNKNOWN

        line_cas = db.execute(
            text(
                """UPDATE order_items
                      SET product_id = :product_id,
                          cost_known_qty = :known_qty,
                          cost_unknown_qty = :unknown_qty,
                          cost_basis_vnd = :cost_basis
                    WHERE id = :id AND order_id = :order_id
                      AND product_id IS NULL
                      AND cost_known_qty = 0
                      AND cost_unknown_qty = :quantity
                      AND cost_basis_vnd = 0
                      AND returned_total_qty = 0"""
            ),
            {
                "product_id": target_product_id,
                "known_qty": known_qty,
                "unknown_qty": unknown_qty,
                "cost_basis": cost_basis,
                "id": int(line.id),
                "order_id": int(order.id),
                "quantity": int(line.quantity),
            },
        )
        if line_cas.rowcount != 1:
            raise _error(409, ERROR_STATE_CONFLICT, "Dòng catalog đã đổi trạng thái")
        issue_cas = db.execute(
            text(
                """UPDATE offline_receipt_issues
                      SET state = 'RESOLVED', reason = :reason,
                          resolved_at = :resolved_at,
                          resolved_by_user_id = :actor,
                          resolution_kind = :resolution_kind,
                          state_version = state_version + 1
                    WHERE id = :id AND order_id = :order_id
                      AND issue_code = 'SP_KHONG_CON'
                      AND state = 'OPEN' AND state_version = :state_version"""
            ),
            {
                "reason": reason,
                "resolved_at": now_text,
                "actor": int(current_user.id),
                "resolution_kind": resolution_kind,
                "id": int(issue.id),
                "order_id": int(order.id),
                "state_version": int(issue.state_version),
            },
        )
        if issue_cas.rowcount != 1:
            raise _error(409, ERROR_STATE_CONFLICT, "Catalog issue đã đổi trạng thái")

    _recovery_checkpoint("ingested_catalog_rows_flushed")
    registry_cas = db.execute(
        text(
            """UPDATE offline_receipt_registry
                  SET state_version = state_version + 1
                WHERE offline_uuid = :offline_uuid AND shop_id = :shop_id
                  AND state = 'INGESTED' AND order_id = :order_id
                  AND state_version = :state_version"""
        ),
        {
            "offline_uuid": registry.offline_uuid,
            "shop_id": int(shop_id),
            "order_id": int(order.id),
            "state_version": int(payload.state_version),
        },
    )
    if registry_cas.rowcount != 1:
        raise _error(409, ERROR_STATE_CONFLICT, "Candidate đã đổi phiên bản")
    _recovery_checkpoint("ingested_catalog_registry_cas")
    _add_recovery_action(
        db,
        shop_id=shop_id,
        actor_user_id=int(current_user.id),
        action_kind=ACTION_LEGACY_INGEST,
        original_uuid=registry.offline_uuid,
        original_fingerprint=registry.server_fingerprint,
        replacement_uuid=None,
        digest=intent_digest,
        reason=reason,
        performed_at=now_text,
        audit_details=(
            f"Resolved legacy offline catalog issues in-place for order #{order.id}"
        ),
    )
    _recovery_checkpoint("ingested_catalog_before_commit")
    response = _in_place_response(
        registry=registry, order=order, intent_digest=intent_digest
    )
    response["state_version"] = int(payload.state_version) + 1
    return response, True


def _append_recovered_financial_rows(
    db: Session,
    *,
    shop_id: int,
    actor_user_id: int,
    document: CanonicalRecoveryDocument,
    lease: Optional[models.OfflineLease],
    lines: list[dict[str, Any]],
    replacement_uuid: str,
    sold_at_effective: str,
    reason: str,
    now_text: str,
) -> tuple[models.Order, models.OfflineReceipt, models.OfflineReceiptRegistry]:
    sold_at = datetime.strptime(sold_at_effective, "%Y-%m-%d %H:%M:%S.%f")
    contract_version = document.contract_version
    source = document.receipt

    corrected_items = [
        {
            "product_id": line["product_id"],
            "product_name": line["product_name"],
            "unit_price_vnd": line["unit_price_vnd"],
            "quantity": line["quantity"],
        }
        for line in lines
    ]
    if contract_version == 0:
        replacement_canonical = fingerprint_offline_receipt_v0(
            shop_id=int(shop_id),
            offline_uuid=replacement_uuid,
            sold_at=sold_at,
            items=corrected_items,
            cash_tendered_vnd=int(source["cash_tendered_vnd"]),
            device_label=None,
        )
        replacement_fingerprint = replacement_canonical.fingerprint
        canonical_items = replacement_canonical.items
        claimed_user_id = actor_user_id
        offline_device = None
    else:
        if lease is None:
            raise _error(409, ERROR_STATE_CONFLICT, "Lease phục hồi không tồn tại")
        replacement_canonical = fingerprint_offline_receipt_v1(
            shop_id=int(shop_id),
            sold_at_client_utc=source["sold_at_client_utc"],
            client_monotonic_ms=int(source["client_monotonic_ms"]),
            monotonic_valid=bool(source["monotonic_valid"]),
            server_anchor_id=lease.server_anchor_id,
            lease_id=lease.lease_id,
            device_id=lease.device_id,
            offline_session_id=lease.lease_id,
            sequence=int(source["sequence"]),
            offline_uuid=replacement_uuid,
            catalog_version=int(lease.catalog_version),
            catalog_snapshot_digest=lease.catalog_snapshot_digest,
            items=corrected_items,
            cash_tendered_vnd=int(source["cash_tendered_vnd"]),
        )
        replacement_fingerprint = replacement_canonical.digest
        canonical_items = replacement_canonical.items
        claimed_user_id = int(lease.user_id)
        offline_device = lease.device_id

    total = 0
    for item in canonical_items:
        total = checked_add(total, checked_multiply(item.quantity, item.unit_price_vnd))
    tendered = exact_vnd(source["cash_tendered_vnd"])
    if tendered < total:
        raise _error(400, "OFFLINE_TENDER_TOO_LOW", "Tiền khách đưa nhỏ hơn tổng đơn")

    shift = offline_service._ca_phu_gio_ban(db, shop_id, claimed_user_id, sold_at)
    issues: list[str] = []
    if shift is None:
        issues.append(offline_service.ISSUE_KHONG_CO_CA)
    elif shift.status != "OPEN":
        issues.append(offline_service.ISSUE_CA_DA_CHOT)

    order = models.Order(
        shop_id=int(shop_id),
        created_by_user_id=claimed_user_id,
        shift_id=shift.id if shift else None,
        total_amount=total,
        discount_amount=0,
        payment_method=order_service.PAYMENT_METHOD_CASH,
        status=order_service.STATUS_PAID,
        cash_paid_amount=total,
        cash_tendered_amount=tendered,
        cash_change_amount=max(tendered - total, 0),
        created_at=sold_at,
        sold_offline_at=sold_at,
        offline_uuid=replacement_uuid,
        offline_device=offline_device,
    )
    db.add(order)
    db.flush()

    replacement_registry = models.OfflineReceiptRegistry(
        offline_uuid=replacement_uuid,
        shop_id=int(shop_id),
        order_id=int(order.id),
        server_fingerprint=replacement_fingerprint,
        contract_version=contract_version,
        state=STATE_INGESTED,
        superseded_by_offline_uuid=None,
        created_at=now_text,
        updated_at=now_text,
        state_version=0,
    )
    db.add(replacement_registry)
    db.flush()

    if contract_version == 0:
        receipt = models.OfflineReceipt(
            order_id=int(order.id),
            offline_uuid=replacement_uuid,
            contract_version=0,
            lease_id=None,
            device_id=None,
            offline_session_id=None,
            sequence=None,
            server_fingerprint=replacement_fingerprint,
            client_fingerprint=None,
            client_fingerprint_mismatch=0,
            sold_by_claimed_user_id=actor_user_id,
            synced_by_user_id=actor_user_id,
            attribution_kind="LEGACY_UNKNOWN",
            sold_at_effective=sold_at_effective,
            sold_at_client_utc=sold_at_effective,
            sold_at_upper_bound=None,
            time_confidence="LEGACY",
            client_monotonic_ms=None,
            server_anchor_id=None,
            ingested_at=now_text,
        )
    else:
        receipt = models.OfflineReceipt(
            order_id=int(order.id),
            offline_uuid=replacement_uuid,
            contract_version=1,
            lease_id=lease.lease_id,
            device_id=lease.device_id,
            offline_session_id=lease.lease_id,
            sequence=int(source["sequence"]),
            server_fingerprint=replacement_fingerprint,
            # The replacement fingerprint is computed by the server.  Recovery
            # has no client assertion for this new artifact, so do not fabricate
            # one by copying the server value into the client-evidence column.
            client_fingerprint=None,
            client_fingerprint_mismatch=0,
            sold_by_claimed_user_id=claimed_user_id,
            synced_by_user_id=actor_user_id,
            attribution_kind="OWNER_RECOVERY",
            sold_at_effective=sold_at_effective,
            sold_at_client_utc=source["sold_at_client_utc"],
            # This equality is not a claimed time bound.  It only preserves the
            # original monotonic_valid=False bit so fsofr1 is reconstructable;
            # RECOVERED explicitly says the accounting time is an owner action.
            sold_at_upper_bound=(
                None if bool(source["monotonic_valid"]) else sold_at_effective
            ),
            time_confidence="RECOVERED",
            client_monotonic_ms=int(source["client_monotonic_ms"]),
            server_anchor_id=lease.server_anchor_id,
            ingested_at=now_text,
        )
    db.add(receipt)
    db.flush()

    # Duplicate tuples deliberately remain separate; consume each line entry in
    # canonical order instead of grouping quantities.
    duplicate_queues: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for line in lines:
        key = (
            int(line["product_id"]),
            line["product_name"],
            int(line["unit_price_vnd"]),
            int(line["quantity"]),
        )
        duplicate_queues.setdefault(key, []).append(line)

    for ordinal, item in enumerate(canonical_items, start=1):
        key = (item.product_id, item.product_name, item.unit_price_vnd, item.quantity)
        queue = duplicate_queues.get(key) or []
        if not queue:
            raise _error(409, ERROR_STATE_CONFLICT, "Canonical recovery line mismatch")
        line = queue.pop(0)
        product: Optional[models.Product] = line["product"]
        allocations: list[inventory_service.CostAllocation] = []
        shortage = item.quantity if product is None else 0
        if product is not None:
            allocations, shortage = offline_service._tru_ton_chiu_thieu(
                db, product, item.quantity
            )
            if shortage > 0 and offline_service.ISSUE_TON_AM not in issues:
                issues.append(offline_service.ISSUE_TON_AM)

        known_qty, allocated_unknown_qty, cost_basis = (
            inventory_service.allocation_totals(allocations)
        )
        allocated_qty = sum(allocation.quantity for allocation in allocations)
        unallocated_qty = max(int(item.quantity) - allocated_qty, 0)
        unknown_qty = allocated_unknown_qty + unallocated_qty
        line_total = checked_multiply(item.quantity, item.unit_price_vnd)
        order_item = models.OrderItem(
            order_id=int(order.id),
            product_id=line["order_item_product_id"],
            product_name=item.product_name,
            price=item.unit_price_vnd,
            quantity=item.quantity,
            discount_vnd=0,
            loyalty_discount_vnd=0,
            net_amount_vnd=line_total,
            cost_known_qty=known_qty,
            cost_unknown_qty=unknown_qty,
            cost_basis_vnd=cost_basis,
        )
        db.add(order_item)
        db.flush()

        if contract_version == 1:
            db.add(
                models.OfflineReceiptItem(
                    receipt_id=int(receipt.id),
                    order_item_id=int(order_item.id),
                    item_ordinal=ordinal,
                    claimed_product_id=item.product_id,
                    product_name=item.product_name,
                    unit_price_vnd=item.unit_price_vnd,
                    quantity=item.quantity,
                )
            )

        if line["accepted_unknown"]:
            if offline_service.ISSUE_SP_KHONG_CON not in issues:
                issues.append(offline_service.ISSUE_SP_KHONG_CON)
            db.add(
                models.OfflineReceiptIssue(
                    order_id=int(order.id),
                    order_item_id=int(order_item.id),
                    product_id=None,
                    issue_code=offline_service.ISSUE_SP_KHONG_CON,
                    evidence_kind=offline_service.EVIDENCE_CATALOG,
                    evidence_id=None,
                    severity=offline_service.SEVERITY_ACTION,
                    state=offline_service.STATE_RESOLVED,
                    reason=reason,
                    opened_at=now_text,
                    resolved_at=now_text,
                    resolved_by_user_id=actor_user_id,
                    resolution_kind=RESOLUTION_ACCEPT_UNKNOWN,
                    state_version=0,
                )
            )
        elif product is not None and exact_vnd(product.price) != item.unit_price_vnd:
            if offline_service.ISSUE_GIA_DOI not in issues:
                issues.append(offline_service.ISSUE_GIA_DOI)
            db.add(
                offline_service._issue_moi(
                    order_id=int(order.id),
                    issue_code=offline_service.ISSUE_GIA_DOI,
                    evidence_kind=offline_service.EVIDENCE_CATALOG,
                    severity=offline_service.SEVERITY_INFO,
                    opened_at=now_text,
                    order_item_id=int(order_item.id),
                    product_id=int(product.id),
                    resolution_kind=RESOLUTION_INFORMATIONAL,
                    resolved_by_user_id=actor_user_id,
                )
            )

        if product is not None and product.track_batches and unallocated_qty > 0:
            deficit = models.OfflineBatchStockDeficit(
                order_item_id=int(order_item.id),
                product_id=int(product.id),
                deficit_quantity=unallocated_qty,
                remaining_quantity=unallocated_qty,
                state_version=0,
            )
            db.add(deficit)
            db.flush()
            db.add(
                offline_service._issue_moi(
                    order_id=int(order.id),
                    issue_code=offline_service.ISSUE_TON_AM,
                    evidence_kind=offline_service.EVIDENCE_BATCH_DEFICIT,
                    severity=offline_service.SEVERITY_ACTION,
                    opened_at=now_text,
                    order_item_id=int(order_item.id),
                    product_id=int(product.id),
                    evidence_id=int(deficit.id),
                )
            )
        elif product is not None and not product.track_batches and shortage > 0:
            deficit = models.OfflineStockDeficit(
                order_item_id=int(order_item.id),
                product_id=int(product.id),
                deficit_quantity=shortage,
                remaining_quantity=shortage,
                state_version=0,
            )
            db.add(deficit)
            db.flush()
            db.add(
                offline_service._issue_moi(
                    order_id=int(order.id),
                    issue_code=offline_service.ISSUE_TON_AM,
                    evidence_kind=offline_service.EVIDENCE_STOCK_DEFICIT,
                    severity=offline_service.SEVERITY_ACTION,
                    opened_at=now_text,
                    order_item_id=int(order_item.id),
                    product_id=int(product.id),
                    evidence_id=int(deficit.id),
                )
            )

        if product is not None and product.track_batches:
            for allocation in allocations:
                if allocation.batch is None:
                    raise _error(409, ERROR_STATE_CONFLICT, "Thiếu provenance lô phục hồi")
                db.add(
                    models.OrderItemBatch(
                        order_item_id=int(order_item.id),
                        batch_id=int(allocation.batch.id),
                        quantity=allocation.quantity,
                        cost_known_qty=allocation.known_qty,
                        cost_unknown_qty=allocation.unknown_qty,
                        cost_basis_vnd=allocation.cost_basis_vnd,
                    )
                )

    for shift_issue in (
        offline_service.ISSUE_CA_DA_CHOT,
        offline_service.ISSUE_KHONG_CO_CA,
    ):
        if shift_issue in issues:
            db.add(
                offline_service._issue_moi(
                    order_id=int(order.id),
                    issue_code=shift_issue,
                    evidence_kind=offline_service.EVIDENCE_SHIFT,
                    severity=offline_service.SEVERITY_ACTION,
                    opened_at=now_text,
                )
            )
    if issues:
        order.offline_issue = ",".join(issues)

    offline_service._add_offline_cash_payment(
        db,
        order_id=int(order.id),
        amount=total,
        offline_uuid=replacement_uuid,
        actor_user_id=claimed_user_id,
        shift_id=shift.id if shift else None,
        sold_at=sold_at,
        note="Bán tiền mặt qua owner recovery",
    )
    return order, receipt, replacement_registry


def resolve_candidate(
    db: Session,
    current_user: models.User,
    shop_id: int,
    offline_uuid: str,
    document: Optional[CanonicalRecoveryDocument],
    payload: RecoveryResolveRequest,
) -> dict[str, Any]:
    if document is not None and document.offline_uuid != offline_uuid:
        raise _not_found()
    reason = _normalize_reason(payload.reason)
    resolutions = _resolution_map(
        payload.line_resolutions,
        len(document.receipt["items"])
        if document is not None
        else MAX_RECOVERY_ITEMS,
    )
    effective: Optional[str] = None
    intent_digest: Optional[str] = None
    if document is not None:
        source_time = (
            document.receipt["sold_at_utc"]
            if document.contract_version == 0
            else document.receipt["sold_at_client_utc"]
        )
        try:
            effective = canonical_time_text_v1(
                payload.sold_at_effective_utc or source_time
            )
        except ValueError as exc:
            raise _error(422, ERROR_MALFORMED, "Giờ phục hồi không hợp lệ") from exc
        if datetime.strptime(
            effective, "%Y-%m-%d %H:%M:%S.%f"
        ) > datetime.utcnow() + timedelta(minutes=2):
            raise _error(400, "OFFLINE_TIME_FUTURE", "Giờ phục hồi nằm ở tương lai")
        intent_digest = _intent_digest(document, reason, resolutions, effective)
    actor_id = int(current_user.id)

    db.rollback()
    try:
        order_service._lock_shop_for_order(db, int(shop_id))
        authorize_recovery_shop(db, shop_id, current_user)
        original = db.get(models.OfflineReceiptRegistry, offline_uuid)
        _fence_pre_registry_order(
            db,
            shop_id=shop_id,
            offline_uuid=offline_uuid,
            registry=original,
        )
        if original is None or int(original.shop_id) != int(shop_id):
            raise _not_found()
        if original.state == STATE_SUPERSEDED:
            if intent_digest is None:
                raise _error(422, ERROR_MALFORMED, "Resolve replacement cần file phục hồi")
            response = _existing_resolution_response(
                db,
                shop_id=shop_id,
                original=original,
                intent_digest=intent_digest,
            )
            db.rollback()
            return response
        if original.state == STATE_INGESTED:
            durable_receipt = (
                db.query(models.OfflineReceipt)
                .filter(models.OfflineReceipt.offline_uuid == offline_uuid)
                .first()
            )
            if durable_receipt is None:
                raise _error(409, ERROR_STATE_CONFLICT, "Phiếu đã ghi thiếu receipt")
            try:
                effective = canonical_time_text_v1(
                    payload.sold_at_effective_utc
                    or durable_receipt.sold_at_effective
                )
            except ValueError as exc:
                raise _error(422, ERROR_MALFORMED, "Giờ phục hồi không hợp lệ") from exc
            if datetime.strptime(
                effective, "%Y-%m-%d %H:%M:%S.%f"
            ) > datetime.utcnow() + timedelta(minutes=2):
                raise _error(400, "OFFLINE_TIME_FUTURE", "Giờ phục hồi nằm ở tương lai")
            intent_digest = _in_place_intent_digest(
                durable_fingerprint=original.server_fingerprint,
                reason=reason,
                resolutions=resolutions,
                sold_at_effective=effective,
            )
            response, changed = _resolve_ingested_v0_catalog(
                db,
                current_user=current_user,
                shop_id=shop_id,
                registry=original,
                document=document,
                payload=payload,
                reason=reason,
                resolutions=resolutions,
                effective=effective,
                intent_digest=intent_digest,
            )
            if changed:
                db.commit()
            else:
                db.rollback()
            return response
        if document is None or effective is None or intent_digest is None:
            raise _error(422, ERROR_MALFORMED, "Resolve candidate cần file phục hồi")
        imported = _import_action(db, shop_id, offline_uuid)
        if (
            original.state != STATE_ABANDONED
            or imported is None
            or imported.file_digest != document.content_sha256
            or original.server_fingerprint != document.source_fingerprint
            or int(original.contract_version) != document.contract_version
        ):
            raise _error(409, ERROR_CONTENT_CONFLICT, "Nội dung phục hồi không khớp import")
        if int(original.state_version) != int(payload.state_version):
            raise _error(409, ERROR_STATE_CONFLICT, "Candidate đã đổi phiên bản")

        lease = None
        if document.contract_version == 1:
            lease = db.get(models.OfflineLease, document.receipt["lease_id"])
            if lease is None or int(lease.shop_id) != int(shop_id):
                raise _not_found()
            sequence_owner = (
                db.query(models.OfflineReceipt)
                .filter(
                    models.OfflineReceipt.lease_id == lease.lease_id,
                    models.OfflineReceipt.sequence == int(document.receipt["sequence"]),
                )
                .first()
            )
            if sequence_owner is not None:
                raise _error(
                    409,
                    ERROR_SEQUENCE_CONFLICT,
                    "Sequence đã thuộc một phiếu khác",
                )

        lines = _build_recovered_lines(
            db,
            shop_id=shop_id,
            items=document.receipt["items"],
            resolutions=resolutions,
        )
        replacement_uuid = f"rcv-{uuid_module.uuid4()}"
        now_text = canonical_time_text(datetime.utcnow())
        order, receipt, replacement = _append_recovered_financial_rows(
            db,
            shop_id=shop_id,
            actor_user_id=actor_id,
            document=document,
            lease=lease,
            lines=lines,
            replacement_uuid=replacement_uuid,
            sold_at_effective=effective,
            reason=reason,
            now_text=now_text,
        )
        db.flush()
        _recovery_checkpoint("financial_rows_flushed")

        cas = db.execute(
            text(
                """UPDATE offline_receipt_registry
                      SET state = 'SUPERSEDED', order_id = NULL,
                          superseded_by_offline_uuid = :replacement,
                          updated_at = :updated_at,
                          state_version = state_version + 1
                    WHERE offline_uuid = :original
                      AND shop_id = :shop_id
                      AND state = 'ABANDONED'
                      AND state_version = :expected_version"""
            ),
            {
                "replacement": replacement_uuid,
                "updated_at": now_text,
                "original": offline_uuid,
                "shop_id": int(shop_id),
                "expected_version": int(payload.state_version),
            },
        )
        if cas.rowcount != 1:
            raise _error(409, ERROR_STATE_CONFLICT, "Candidate đã đổi phiên bản")
        _recovery_checkpoint("original_tombstoned")

        _add_recovery_action(
            db,
            shop_id=shop_id,
            actor_user_id=actor_id,
            action_kind=ACTION_CORRECT,
            original_uuid=offline_uuid,
            original_fingerprint=document.source_fingerprint,
            replacement_uuid=replacement_uuid,
            digest=intent_digest,
            reason=reason,
            performed_at=now_text,
            audit_details=(
                f"Recovered offline receipt contract v{document.contract_version} "
                f"as order #{order.id} with owner-approved correction"
            ),
        )
        _recovery_checkpoint("before_recovery_commit")
        db.commit()
    except IntegrityError:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise

    return {
        "offline_uuid": offline_uuid,
        "state": STATE_SUPERSEDED,
        "state_version": int(payload.state_version) + 1,
        "replacement_offline_uuid": replacement_uuid,
        "order_id": int(order.id),
        "contract_version": int(document.contract_version),
        "recovery_digest": intent_digest,
        "created": True,
    }


__all__ = [
    "ERROR_ALREADY_INGESTED",
    "ERROR_CONTENT_CONFLICT",
    "ERROR_HASH_MISMATCH",
    "ERROR_LINE_DECISION_INVALID",
    "ERROR_LINE_DECISION_REQUIRED",
    "ERROR_MALFORMED",
    "ERROR_MAP_INVALID",
    "ERROR_NOT_FOUND",
    "ERROR_PREEXISTING_ORDER",
    "ERROR_SEQUENCE_CONFLICT",
    "ERROR_STATE_CONFLICT",
    "ERROR_TON_AM_FORBIDDEN",
    "ERROR_VERSION_UNSUPPORTED",
    "MAX_PAGE_LIMIT",
    "MAX_PAGE_OFFSET",
    "RECOVERY_FORMAT",
    "RECOVERY_FORMAT_VERSION",
    "authorize_recovery_shop",
    "build_export_file",
    "import_candidate",
    "list_candidates",
    "parse_recovery_file",
    "read_candidate",
    "resolve_candidate",
]
