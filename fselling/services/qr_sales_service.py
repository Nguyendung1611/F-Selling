"""I10-B atomic sales-QR intent issuance and same-origin rendering.

Only immutable I10-A intent rows are written here.  QR output is an
instruction, never payment evidence, and adapters return bytes rather than a
remote URL.  The installed runtime is always disabled; REPORT_ONLY issuance
requires the explicit deterministic mock/test runtime seam in this module.
"""
from __future__ import annotations

import binascii
import hashlib
import json
import secrets
import struct
import zlib
from dataclasses import dataclass
from typing import Protocol

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models
from ..core import config
from ..core.config import log_to_file
from ..core.i18n import tr
from ..dependencies import PERMISSION_SALE, require_staff_permission


CONTRACT_VERSION = 1
ADAPTER_PROFILE_DISABLED = "disabled.v1"
ADAPTER_PROFILE_MOCK = "mock.v1"
REFERENCE_ATTEMPTS = 5
RENDER_MAX_BYTES = 512 * 1024
RENDER_MEDIA_TYPES = frozenset({"image/png"})
AUDIT_ACTION_INTENT_ISSUED = "QR_PAYMENT_INTENT_ISSUED"

ERROR_INTENT_NOT_FOUND = "QR_INTENT_NOT_FOUND"
ERROR_INTENT_ISSUANCE_FAILED = "QR_INTENT_ISSUANCE_FAILED"
ERROR_INTENT_AUDIT_FAILED = "QR_INTENT_AUDIT_FAILED"
ERROR_REFERENCE_UNAVAILABLE = "QR_INTENT_REFERENCE_UNAVAILABLE"
ERROR_RENDER_UNAVAILABLE = "QR_RENDER_UNAVAILABLE"
ERROR_RENDER_FAILED = "QR_RENDER_FAILED"
ERROR_RENDER_INVALID_OUTPUT = "QR_RENDER_INVALID_OUTPUT"
ERROR_RENDER_HIDDEN_UNDERPAYMENT = "QR_RENDER_HIDDEN_UNDERPAYMENT"


@dataclass(frozen=True)
class QrInstruction:
    """Sanitized immutable instruction passed to a server-side adapter."""

    contract_version: int
    order_id: int
    shop_id: int
    canonical_reference: str
    expected_vnd: int
    bank_code: str
    account_no: str
    account_name: str


@dataclass(frozen=True)
class QrRenderResult:
    content: bytes
    media_type: str


class QrRenderAdapter(Protocol):
    """Small byte-only adapter contract; remote URLs are not valid output."""

    profile_id: str
    test_only: bool

    def render(self, instruction: QrInstruction) -> QrRenderResult: ...


class QrAdapterUnavailable(RuntimeError):
    pass


class QrRenderFailure(RuntimeError):
    pass


class DisabledQrAdapter:
    profile_id = ADAPTER_PROFILE_DISABLED
    test_only = False

    def render(self, _instruction: QrInstruction) -> QrRenderResult:
        raise QrAdapterUnavailable(ERROR_RENDER_UNAVAILABLE)


def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    checksum = binascii.crc32(kind + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)


class DeterministicMockQrAdapter:
    """Test-only deterministic PNG renderer; it never calls a provider/network.

    The bitmap is a synthetic hash pattern, intentionally not a production QR
    encoder.  It proves the adapter boundary and byte contract without choosing
    a provider/reference standard that belongs to I10-R.
    """

    profile_id = ADAPTER_PROFILE_MOCK
    test_only = True

    def render(self, instruction: QrInstruction) -> QrRenderResult:
        canonical = json.dumps(
            {
                "account_name": instruction.account_name,
                "account_no": instruction.account_no,
                "bank_code": instruction.bank_code,
                "contract_version": instruction.contract_version,
                "expected_vnd": instruction.expected_vnd,
                "order_id": instruction.order_id,
                "reference": instruction.canonical_reference,
                "shop_id": instruction.shop_id,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        digest = hashlib.sha256(canonical).digest()
        width = height = 21
        rows = bytearray()
        for y in range(height):
            rows.append(0)  # PNG scanline filter
            for x in range(width):
                bit_index = (y * width + x) % (len(digest) * 8)
                bit = (digest[bit_index // 8] >> (bit_index % 8)) & 1
                rows.append(0 if bit else 255)
        header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
        png = (
            b"\x89PNG\r\n\x1a\n"
            + _png_chunk(b"IHDR", header)
            + _png_chunk(b"IDAT", zlib.compress(bytes(rows), level=9))
            + _png_chunk(b"IEND", b"")
        )
        return QrRenderResult(content=png, media_type="image/png")


@dataclass(frozen=True)
class QrSalesRuntime:
    mode: str
    adapter: QrRenderAdapter

    @property
    def report_only_mock(self) -> bool:
        return (
            self.mode == config.QR_SALES_MODE_REPORT_ONLY
            and getattr(self.adapter, "test_only", False) is True
            and getattr(self.adapter, "profile_id", None) == ADAPTER_PROFILE_MOCK
        )

    @property
    def render_available(self) -> bool:
        """Runtime-level capability; intent profile matching is checked later."""
        return self.report_only_mock


_DISABLED_ADAPTER = DisabledQrAdapter()


def get_runtime() -> QrSalesRuntime:
    """Return the fail-closed installed runtime.

    Even ``QR_SALES_MODE=REPORT_ONLY`` remains non-issuing until a test replaces
    this seam with :func:`report_only_test_runtime`.
    """
    return QrSalesRuntime(mode=config.QR_SALES_MODE, adapter=_DISABLED_ADAPTER)


def report_only_test_runtime(
    adapter: QrRenderAdapter | None = None,
) -> QrSalesRuntime:
    """Explicit test seam; no application startup path calls this function."""
    selected = adapter or DeterministicMockQrAdapter()
    if (
        getattr(selected, "test_only", False) is not True
        or getattr(selected, "profile_id", None) != ADAPTER_PROFILE_MOCK
    ):
        raise ValueError("REPORT_ONLY test runtime requires a test-only adapter")
    return QrSalesRuntime(
        mode=config.QR_SALES_MODE_REPORT_ONLY,
        adapter=selected,
    )


def _http_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": tr(message)},
    )


def _canonical_reference() -> str:
    """Globally unique, non-secret, canonical v1 reference candidate."""
    return "FS1-" + secrets.token_hex(16).upper()


def _issued_at_text() -> str:
    # Keep the exact SQLite contract released by 0007: UTC-naive, six digits.
    from datetime import datetime

    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.%f")


def _is_reference_collision(exc: IntegrityError) -> bool:
    message = str(getattr(exc, "orig", exc)).lower()
    return (
        "qr_payment_intents.canonical_reference" in message
        or "ux_qr_payment_intents_reference" in message
    )


def _insert_intent_candidate(db: Session, intent: models.QrPaymentIntent) -> None:
    """Flush one candidate inside the caller's nested savepoint."""
    db.add(intent)
    db.flush()


def _insert_issuance_audit(db: Session, audit: models.SystemLog) -> None:
    """Flush the issuance audit without committing the caller's transaction."""
    db.add(audit)
    db.flush()


def _add_issuance_audit(
    db: Session,
    order: models.Order,
    intent: models.QrPaymentIntent,
) -> None:
    """Add one minimal, non-secret audit for a newly issued intent.

    This deliberately does not use ``log_system_action()``: that legacy helper
    commits independently and swallows failures.  The explicit flush makes an
    audit write failure abort the outer order transaction before its one commit.
    """
    details = json.dumps(
        {
            "contract_version": int(intent.contract_version),
            "entity": "qr_payment_intent",
            "intent_id": int(intent.id),
            "order_id": int(intent.order_id),
            "shop_id": int(intent.shop_id),
            "status": "ISSUED",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    audit = models.SystemLog(
        user_id=(
            int(order.created_by_user_id)
            if order.created_by_user_id is not None
            else None
        ),
        shop_id=int(intent.shop_id),
        action=AUDIT_ACTION_INTENT_ISSUED,
        details=details,
    )
    _insert_issuance_audit(db, audit)


def issue_intent_if_enabled(
    db: Session,
    order: models.Order,
    shop: models.Shop,
    *,
    runtime: QrSalesRuntime | None = None,
) -> models.QrPaymentIntent | None:
    """Issue one immutable intent inside the existing order transaction.

    No commit occurs here.  Reference collisions roll back only their nested
    savepoint; every other failure is sanitized and left for ``create_order``
    to roll back together with order/items/inventory/cost/loyalty.
    """
    selected = runtime or get_runtime()
    if not selected.report_only_mock:
        return None
    if (
        order.payment_method != "transfer"
        or int(order.total_amount or 0) <= 0
        or order.offline_uuid is not None
    ):
        return None

    for _attempt in range(REFERENCE_ATTEMPTS):
        candidate = _canonical_reference()
        intent = models.QrPaymentIntent(
            contract_version=CONTRACT_VERSION,
            order_id=order.id,
            shop_id=order.shop_id,
            canonical_reference=candidate,
            expected_vnd=int(order.total_amount),
            bank_code=shop.bank_code,
            account_no=shop.bank_account_no,
            account_name=shop.bank_account_name,
            adapter_profile_id=selected.adapter.profile_id,
            issued_at=_issued_at_text(),
            display_expires_at=None,
            cancel_after=None,
        )
        try:
            with db.begin_nested():
                _insert_intent_candidate(db, intent)
        except IntegrityError as exc:
            if _is_reference_collision(exc):
                continue
            log_to_file("QR intent issuance failed code=QR_INTENT_ISSUANCE_FAILED")
            raise _http_error(
                503,
                ERROR_INTENT_ISSUANCE_FAILED,
                "Chưa thể tạo hướng dẫn chuyển khoản",
            ) from None
        try:
            _add_issuance_audit(db, order, intent)
        except Exception:
            log_to_file("QR intent issuance failed code=QR_INTENT_AUDIT_FAILED")
            raise _http_error(
                503,
                ERROR_INTENT_AUDIT_FAILED,
                "Chưa thể ghi nhận hướng dẫn chuyển khoản",
            ) from None
        return intent

    log_to_file("QR intent issuance failed code=QR_INTENT_REFERENCE_UNAVAILABLE")
    raise _http_error(
        503,
        ERROR_REFERENCE_UNAVAILABLE,
        "Chưa thể tạo mã tham chiếu chuyển khoản",
    )


def _instruction(intent: models.QrPaymentIntent) -> QrInstruction:
    return QrInstruction(
        contract_version=int(intent.contract_version),
        order_id=int(intent.order_id),
        shop_id=int(intent.shop_id),
        canonical_reference=str(intent.canonical_reference),
        expected_vnd=int(intent.expected_vnd),
        bank_code=str(intent.bank_code),
        account_no=str(intent.account_no),
        account_name=str(intent.account_name),
    )


def _can_render(
    intent: models.QrPaymentIntent,
    runtime: QrSalesRuntime,
) -> bool:
    return (
        runtime.report_only_mock
        and runtime.adapter.profile_id == intent.adapter_profile_id
    )


def serialize_intent(
    intent: models.QrPaymentIntent,
    *,
    runtime: QrSalesRuntime | None = None,
    hidden_underpayment: bool = False,
) -> dict:
    """Return approved display fields only; adapter/provider internals stay server-side."""
    selected = runtime or get_runtime()
    render_available = _can_render(intent, selected)
    if hidden_underpayment:
        return {
            "contract_version": int(intent.contract_version),
            "expected_vnd": int(intent.expected_vnd),
            "issued_at": intent.issued_at,
            "instruction_only": True,
            "hidden": True,
            "hidden_reason": "UNDERPAYMENT_UNAPPLIED",
            "capability": {
                "mode": selected.mode,
                "render_available": False,
                "render_endpoint": None,
            },
        }
    return {
        "contract_version": int(intent.contract_version),
        "canonical_reference": intent.canonical_reference,
        "expected_vnd": int(intent.expected_vnd),
        "bank_code": intent.bank_code,
        "bank_account_no": intent.account_no,
        "bank_account_name": intent.account_name,
        "issued_at": intent.issued_at,
        "instruction_only": True,
        "capability": {
            "mode": selected.mode,
            "render_available": render_available,
            "render_endpoint": (
                f"/api/orders/{intent.order_id}/qr/render"
                if render_available
                else None
            ),
        },
    }


def _has_unapplied_underpayment(
    db: Session, intent: models.QrPaymentIntent
) -> bool:
    return (
        db.query(models.BankWebhookEvent.id)
        .filter(
            models.BankWebhookEvent.intent_id == intent.id,
            models.BankWebhookEvent.disposition == "UNAPPLIED",
            models.BankWebhookEvent.reason_code == "AMOUNT_UNDERPAID",
        )
        .first()
        is not None
    )


def intent_for_order(
    db: Session,
    order_id: int,
) -> models.QrPaymentIntent | None:
    return (
        db.query(models.QrPaymentIntent)
        .filter(models.QrPaymentIntent.order_id == order_id)
        .first()
    )


def metadata_for_order(
    db: Session,
    order: models.Order,
    *,
    runtime: QrSalesRuntime | None = None,
) -> dict | None:
    intent = intent_for_order(db, order.id)
    if intent is None:
        return None
    return serialize_intent(
        intent,
        runtime=runtime,
        hidden_underpayment=_has_unapplied_underpayment(db, intent),
    )


def _authorized_intent(
    db: Session,
    current_user: models.User,
    order_id: int,
) -> models.QrPaymentIntent:
    """Scope the order query before existence is revealed, then check SALE role."""
    query = (
        db.query(models.QrPaymentIntent)
        .join(models.Order, models.Order.id == models.QrPaymentIntent.order_id)
        .filter(models.Order.id == order_id)
    )
    if current_user.role == "ADMIN":
        pass
    elif current_user.role == "STAFF":
        query = query.filter(models.Order.shop_id == current_user.staff_shop_id)
    else:
        query = query.join(models.Shop, models.Shop.id == models.Order.shop_id).filter(
            models.Shop.owner_id == current_user.id
        )

    intent = query.first()
    if intent is None:
        raise _http_error(
            404,
            ERROR_INTENT_NOT_FOUND,
            "Không tìm thấy hướng dẫn chuyển khoản",
        )
    require_staff_permission(current_user, PERMISSION_SALE)
    return intent


def authorized_intent_metadata(
    db: Session,
    current_user: models.User,
    order_id: int,
    *,
    runtime: QrSalesRuntime | None = None,
) -> dict:
    intent = _authorized_intent(db, current_user, order_id)
    return serialize_intent(
        intent,
        runtime=runtime,
        hidden_underpayment=_has_unapplied_underpayment(db, intent),
    )


def render_authorized_intent(
    db: Session,
    current_user: models.User,
    order_id: int,
    *,
    runtime: QrSalesRuntime | None = None,
) -> QrRenderResult:
    """Render an existing intent without issuing, mutating or persisting bytes."""
    intent = _authorized_intent(db, current_user, order_id)
    if _has_unapplied_underpayment(db, intent):
        raise _http_error(
            409,
            ERROR_RENDER_HIDDEN_UNDERPAYMENT,
            "QR is hidden while underpayment evidence is unresolved",
        )
    selected = runtime or get_runtime()
    if not _can_render(intent, selected):
        raise _http_error(
            503,
            ERROR_RENDER_UNAVAILABLE,
            "Kênh hiển thị QR hiện không khả dụng",
        )
    try:
        rendered = selected.adapter.render(_instruction(intent))
    except QrAdapterUnavailable:
        raise _http_error(
            503,
            ERROR_RENDER_UNAVAILABLE,
            "Kênh hiển thị QR hiện không khả dụng",
        ) from None
    except Exception:
        log_to_file("QR render failed code=QR_RENDER_FAILED")
        raise _http_error(
            502,
            ERROR_RENDER_FAILED,
            "Chưa thể hiển thị QR chuyển khoản",
        ) from None

    if (
        not isinstance(rendered, QrRenderResult)
        or type(rendered.content) is not bytes
        or not rendered.content
        or len(rendered.content) > RENDER_MAX_BYTES
        or type(rendered.media_type) is not str
        or rendered.media_type not in RENDER_MEDIA_TYPES
    ):
        log_to_file("QR render failed code=QR_RENDER_INVALID_OUTPUT")
        raise _http_error(
            502,
            ERROR_RENDER_INVALID_OUTPUT,
            "Dữ liệu QR không hợp lệ",
        )
    return rendered


__all__ = [
    "AUDIT_ACTION_INTENT_ISSUED",
    "DeterministicMockQrAdapter",
    "DisabledQrAdapter",
    "QrInstruction",
    "QrRenderAdapter",
    "QrRenderFailure",
    "QrRenderResult",
    "QrSalesRuntime",
    "authorized_intent_metadata",
    "get_runtime",
    "issue_intent_if_enabled",
    "metadata_for_order",
    "render_authorized_intent",
    "report_only_test_runtime",
]
