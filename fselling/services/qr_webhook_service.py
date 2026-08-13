"""I10-C normalized webhook adapter boundary and durable financial inbox.

The installed runtime is deliberately disabled.  The only enabled adapter in
this slice is an explicit deterministic test seam.  Raw envelopes and auth
metadata exist only long enough to authenticate, parse and hash the request;
they are never returned, logged or persisted.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from fastapi import HTTPException, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from .. import models
from ..core import config
from ..core.database import SessionLocal


MAX_BODY_BYTES = 64 * 1024
MAX_JSON_NESTING = 32
MAX_SAFE_VND = 9_000_000_000_000_000
PROVIDER_MOCK = "mock_bank"
MOCK_PROFILE = "mock_webhook.v1"
DISABLED_PROFILE = "disabled_webhook.v1"
_IDENTIFIER = re.compile(r"^[A-Za-z0-9._:/-]{1,128}$")
_REFERENCE = re.compile(r"^[A-Z0-9._:/-]{1,128}$")
_RAW_HEADER_NAME = re.compile(rb"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_RAW_AUTH_TOKEN = re.compile(rb"^[\x21-\x7e]{1,256}$")
_RAW_HEX_64 = re.compile(rb"^[0-9a-f]{64}$")
_CANONICAL_CONTENT_LENGTH = re.compile(rb"^(?:0|[1-9][0-9]*)$")
_CONTENT_TYPE_HEADER = b"content-type"
_CONTENT_LENGTH_HEADER = b"content-length"
_TRANSFER_ENCODING_HEADER = b"transfer-encoding"
_TOKEN_HEADER = b"x-bank-webhook-token"
_SIGNATURE_HEADER = b"x-bank-webhook-signature"
_ENVELOPE_KEYS = frozenset(
    {
        "provider_event_id",
        "account_no",
        "direction",
        "amount_vnd",
        "references",
        "reference_truncated",
        "occurred_at",
    }
)

ERROR_DISABLED = "QR_WEBHOOK_DISABLED"
ERROR_AUTH = "QR_WEBHOOK_AUTH_INVALID"
ERROR_CONTENT_TYPE = "QR_WEBHOOK_CONTENT_TYPE_INVALID"
ERROR_BODY_SIZE = "QR_WEBHOOK_BODY_TOO_LARGE"
ERROR_BODY = "QR_WEBHOOK_BODY_INVALID"
ERROR_PERSISTENCE = "QR_WEBHOOK_PERSISTENCE_FAILED"
REASON_PROVIDER_COLLISION = "PROVIDER_EVENT_COLLISION"


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


@dataclass(frozen=True)
class AuthMetadata:
    token: str
    signature: str
    content_length: int | None = None


@dataclass(frozen=True)
class NormalizedBankEvent:
    provider: str
    provider_event_id: str | None
    normalized_account_no: str | None
    direction: str
    amount_vnd: int | None
    reference_state: str
    normalized_reference: str | None
    occurred_at: str | None


class WebhookAdapter(Protocol):
    profile_id: str
    test_only: bool

    def authenticate(self, envelope: bytes, metadata: AuthMetadata) -> bool: ...

    def normalize(self, envelope: bytes) -> NormalizedBankEvent: ...


class DisabledWebhookAdapter:
    profile_id = DISABLED_PROFILE
    test_only = False

    def authenticate(self, _envelope: bytes, _metadata: AuthMetadata) -> bool:
        return False

    def normalize(self, _envelope: bytes) -> NormalizedBankEvent:
        raise RuntimeError(ERROR_DISABLED)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _json_nesting_is_bounded(envelope: bytes) -> bool:
    """Bound container nesting before JSON allocates an attacker-shaped tree."""
    depth = 0
    in_string = False
    escaped = False
    for byte in envelope:
        if in_string:
            if escaped:
                escaped = False
            elif byte == 0x5C:  # backslash
                escaped = True
            elif byte == 0x22:  # quote
                in_string = False
            continue
        if byte == 0x22:
            in_string = True
        elif byte in (0x7B, 0x5B):  # { [
            depth += 1
            if depth > MAX_JSON_NESTING:
                return False
        elif byte in (0x7D, 0x5D):  # } ]
            depth -= 1
            if depth < 0:
                return False
    return depth == 0 and not in_string


def _canonical_utc(value: Any) -> str:
    if type(value) is not str or not value or len(value) > 64:
        raise ValueError("invalid timestamp")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(candidate)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include timezone")
    return parsed.astimezone(timezone.utc).replace(tzinfo=None).strftime(
        "%Y-%m-%d %H:%M:%S.%f"
    )


def _optional_identifier(value: Any, *, maximum: int) -> str | None:
    if value is None:
        return None
    if type(value) is not str:
        raise ValueError("identifier must be text")
    canonical = value.strip()
    if (
        not canonical
        or len(canonical) > maximum
        or len(canonical.encode("utf-8")) > maximum * 3
        or _IDENTIFIER.fullmatch(canonical) is None
    ):
        raise ValueError("invalid identifier")
    return canonical


def _canonical_reference(value: Any) -> str:
    if type(value) is not str:
        raise ValueError("reference must be text")
    canonical = value.strip().upper()
    if (
        not canonical
        or len(canonical.encode("utf-8")) > 128
        or _REFERENCE.fullmatch(canonical) is None
    ):
        raise ValueError("invalid reference")
    return canonical


def _normalize_reference(payload: dict[str, Any]) -> tuple[str, str | None]:
    truncated = payload.get("reference_truncated", False)
    if type(truncated) is not bool:
        raise ValueError("reference_truncated must be boolean")
    raw = payload.get("references")
    if raw is None or raw == "" or raw == []:
        return "MISSING", None
    values = [raw] if type(raw) is str else raw
    if type(values) is not list:
        raise ValueError("references must be text or list")
    if len(values) != 1:
        return "MULTIPLE", None
    try:
        canonical = _canonical_reference(values[0])
    except ValueError:
        return "INVALID", None
    return ("TRUNCATED" if truncated else "EXACT"), canonical


class DeterministicMockWebhookAdapter:
    """Strict local-only adapter used solely through an explicit test seam."""

    profile_id = MOCK_PROFILE
    test_only = True

    def __init__(self, *, token: str, signing_key: bytes):
        if type(token) is not str or not token or len(token) > 256:
            raise ValueError("mock token must be bounded text")
        if type(signing_key) is not bytes or not signing_key:
            raise ValueError("mock signing key must be non-empty bytes")
        self._token = token
        self._signing_key = signing_key

    def signature_for(self, envelope: bytes) -> str:
        return hmac.new(self._signing_key, envelope, hashlib.sha256).hexdigest()

    def authenticate(self, envelope: bytes, metadata: AuthMetadata) -> bool:
        expected = self.signature_for(envelope)
        token_valid = hmac.compare_digest(metadata.token, self._token)
        signature_valid = hmac.compare_digest(metadata.signature, expected)
        return token_valid and signature_valid

    def normalize(self, envelope: bytes) -> NormalizedBankEvent:
        if not _json_nesting_is_bounded(envelope):
            raise ValueError("JSON nesting is invalid")
        payload = json.loads(
            envelope.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys
        )
        if type(payload) is not dict or set(payload) - _ENVELOPE_KEYS:
            raise ValueError("invalid envelope shape")

        provider_event_id = _optional_identifier(
            payload.get("provider_event_id"), maximum=128
        )
        account = _optional_identifier(payload.get("account_no"), maximum=64)
        if account is not None:
            account = account.upper()

        direction = payload.get("direction", "UNKNOWN")
        if type(direction) is not str:
            raise ValueError("invalid direction")
        direction = direction.strip().upper()
        if direction not in {"IN", "OUT", "UNKNOWN"}:
            raise ValueError("invalid direction")

        amount = payload.get("amount_vnd")
        if amount is not None and (
            type(amount) is not int or amount < 0 or amount > MAX_SAFE_VND
        ):
            raise ValueError("invalid exact VND")

        reference_state, reference = _normalize_reference(payload)
        occurred_at = (
            _canonical_utc(payload["occurred_at"])
            if payload.get("occurred_at") is not None
            else None
        )
        return NormalizedBankEvent(
            provider=PROVIDER_MOCK,
            provider_event_id=provider_event_id,
            normalized_account_no=account,
            direction=direction,
            amount_vnd=amount,
            reference_state=reference_state,
            normalized_reference=reference,
            occurred_at=occurred_at,
        )


@dataclass(frozen=True)
class WebhookRuntime:
    mode: str
    adapter: WebhookAdapter

    @property
    def enabled_test_adapter(self) -> bool:
        return (
            self.mode == config.QR_WEBHOOK_MODE_REPORT_ONLY
            and getattr(self.adapter, "test_only", False) is True
            and getattr(self.adapter, "profile_id", None) == MOCK_PROFILE
        )


_DISABLED = DisabledWebhookAdapter()


def get_runtime() -> WebhookRuntime:
    """Installed runtime: always disabled, regardless of environment/request."""
    return WebhookRuntime(mode=config.QR_WEBHOOK_MODE, adapter=_DISABLED)


def report_only_test_runtime(
    *, token: str = "i10c-test-token", signing_key: bytes = b"i10c-test-key"
) -> WebhookRuntime:
    return WebhookRuntime(
        mode=config.QR_WEBHOOK_MODE_REPORT_ONLY,
        adapter=DeterministicMockWebhookAdapter(token=token, signing_key=signing_key)
    )


def _raw_header_map(request: Request) -> dict[bytes, list[bytes]]:
    """Read the ASGI framing metadata without Starlette header collapsing."""
    raw_headers = request.scope.get("headers")
    if type(raw_headers) not in {list, tuple}:
        raise _error(400, ERROR_BODY, "Webhook body is invalid")
    result: dict[bytes, list[bytes]] = {}
    for item in raw_headers:
        if type(item) not in {list, tuple} or len(item) != 2:
            raise _error(400, ERROR_BODY, "Webhook body is invalid")
        name, value = item
        if (
            type(name) is not bytes
            or type(value) is not bytes
            or _RAW_HEADER_NAME.fullmatch(name) is None
            or any(byte < 0x20 or byte > 0x7E for byte in value)
        ):
            raise _error(400, ERROR_BODY, "Webhook body is invalid")
        result.setdefault(name.lower(), []).append(value)
    return result


def _single_header(
    headers: dict[bytes, list[bytes]],
    name: bytes,
    *,
    status: int,
    code: str,
    message: str,
) -> bytes:
    values = headers.get(name, [])
    if len(values) != 1:
        raise _error(status, code, message)
    return values[0]


def _bounded_content_length(value: bytes) -> int:
    if _CANONICAL_CONTENT_LENGTH.fullmatch(value) is None:
        raise _error(400, ERROR_BODY, "Webhook body is invalid")
    maximum = str(MAX_BODY_BYTES).encode("ascii")
    if len(value) > len(maximum) or (
        len(value) == len(maximum) and value > maximum
    ):
        raise _error(413, ERROR_BODY_SIZE, "Webhook body is too large")
    return int(value)


def validate_metadata(request: Request, runtime: WebhookRuntime) -> AuthMetadata:
    if not runtime.enabled_test_adapter:
        raise _error(503, ERROR_DISABLED, "Webhook QR is disabled")

    headers = _raw_header_map(request)
    if _TRANSFER_ENCODING_HEADER in headers:
        raise _error(400, ERROR_BODY, "Webhook body is invalid")
    content_type = _single_header(
        headers,
        _CONTENT_TYPE_HEADER,
        status=415,
        code=ERROR_CONTENT_TYPE,
        message="Webhook content type is invalid",
    )
    if content_type != b"application/json":
        raise _error(415, ERROR_CONTENT_TYPE, "Webhook content type is invalid")

    token_raw = _single_header(
        headers,
        _TOKEN_HEADER,
        status=401,
        code=ERROR_AUTH,
        message="Webhook authentication is invalid",
    )
    signature_raw = _single_header(
        headers,
        _SIGNATURE_HEADER,
        status=401,
        code=ERROR_AUTH,
        message="Webhook authentication is invalid",
    )
    if (
        _RAW_AUTH_TOKEN.fullmatch(token_raw) is None
        or _RAW_HEX_64.fullmatch(signature_raw) is None
    ):
        raise _error(401, ERROR_AUTH, "Webhook authentication is invalid")

    declared_values = headers.get(_CONTENT_LENGTH_HEADER, [])
    if len(declared_values) > 1:
        raise _error(400, ERROR_BODY, "Webhook body is invalid")
    declared = (
        _bounded_content_length(declared_values[0]) if declared_values else None
    )
    return AuthMetadata(
        token=token_raw.decode("ascii"),
        signature=signature_raw.decode("ascii"),
        content_length=declared,
    )


async def read_authenticated_envelope(
    request: Request, runtime: WebhookRuntime, metadata: AuthMetadata
) -> bytes:
    body = bytearray()
    try:
        async for chunk in request.stream():
            if type(chunk) is not bytes:
                raise ValueError("invalid ASGI body chunk")
            if len(body) + len(chunk) > MAX_BODY_BYTES:
                raise _error(413, ERROR_BODY_SIZE, "Webhook body is too large")
            body.extend(chunk)
    except HTTPException:
        raise
    except Exception:
        raise _error(400, ERROR_BODY, "Webhook body is invalid") from None
    envelope = bytes(body)
    if metadata.content_length is not None and len(envelope) != metadata.content_length:
        raise _error(400, ERROR_BODY, "Webhook body is invalid")
    try:
        authenticated = bool(
            envelope and runtime.adapter.authenticate(envelope, metadata)
        )
    except Exception:
        authenticated = False
    if not authenticated:
        raise _error(401, ERROR_AUTH, "Webhook authentication is invalid")
    return envelope


def _canonical_normalized(event: NormalizedBankEvent) -> bytes:
    return json.dumps(
        {
            "account_no": event.normalized_account_no,
            "amount_vnd": event.amount_vnd,
            "direction": event.direction,
            "occurred_at": event.occurred_at,
            "provider": event.provider,
            "provider_event_id": event.provider_event_id,
            "reference": event.normalized_reference,
            "reference_state": event.reference_state,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _idempotency_key(
    event: NormalizedBankEvent, normalized_sha: str, envelope_sha: str
) -> str:
    identity = event.provider_event_id or "NO_PROVIDER_EVENT_ID"
    return _digest(
        f"i10c|{event.provider}|{identity}|{normalized_sha}|{envelope_sha}".encode(
            "utf-8"
        )
    )


def _utc_now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.%f")


def _account_key(value: str | None) -> str:
    if not value:
        return ""
    canonical = value.strip().upper()
    return canonical.lstrip("0") or "0"


def _has_money_conflict(db: Session, intent: models.QrPaymentIntent) -> bool:
    applied = (
        db.query(models.BankWebhookEvent.id)
        .filter(
            models.BankWebhookEvent.intent_id == intent.id,
            models.BankWebhookEvent.disposition == "APPLIED",
        )
        .first()
        is not None
    )
    if applied:
        return True
    return (
        db.query(models.OrderPayment.id)
        .filter(models.OrderPayment.order_id == intent.order_id)
        .first()
        is not None
    )


def _classify(
    db: Session,
    event: NormalizedBankEvent,
    *,
    collision: bool,
) -> tuple[str, models.QrPaymentIntent | None, models.Order | None]:
    # Provider identity conflict is established from durable evidence before
    # any reference lookup. A conflicting envelope can never use its own
    # untrusted reference to acquire tenant scope.
    if collision:
        return REASON_PROVIDER_COLLISION, None, None
    if event.reference_state != "EXACT":
        return f"REFERENCE_{event.reference_state}", None, None
    intent = (
        db.query(models.QrPaymentIntent)
        .filter(
            models.QrPaymentIntent.contract_version == 1,
            models.QrPaymentIntent.canonical_reference == event.normalized_reference,
        )
        .one_or_none()
    )
    if intent is None:
        return "REFERENCE_UNKNOWN", None, None
    order = (
        db.query(models.Order)
        .filter(
            models.Order.id == intent.order_id,
            models.Order.shop_id == intent.shop_id,
        )
        .one_or_none()
    )
    if order is None:
        return "ORDER_UNAVAILABLE", intent, None
    if order.status == "CANCELLED":
        return "ORDER_FINAL_CANCELLED", intent, order
    if order.status == "PAID" or _has_money_conflict(db, intent):
        return "ORDER_PAYMENT_CONFLICT", intent, order
    if order.status != "PENDING":
        return "ORDER_NOT_PENDING", intent, order
    if not event.normalized_account_no:
        return "ACCOUNT_MISSING", intent, order
    if _account_key(event.normalized_account_no) != _account_key(intent.account_no):
        return "ACCOUNT_MISMATCH", intent, order
    if event.direction == "OUT":
        return "DIRECTION_OUTBOUND", intent, order
    if event.direction != "IN":
        return "DIRECTION_UNKNOWN", intent, order
    if event.amount_vnd is None:
        return "AMOUNT_MISSING", intent, order
    if event.amount_vnd == 0:
        return "AMOUNT_ZERO", intent, order
    if event.amount_vnd < intent.expected_vnd:
        return "AMOUNT_UNDERPAID", intent, order
    if event.amount_vnd > intent.expected_vnd:
        return "AMOUNT_OVERPAID", intent, order
    return "READY_TO_MAP", intent, order


def _acquire_inbox_write_lock(db: Session) -> None:
    """Serialize identity lookup + insert; SQLite's durable writer fence."""
    db.rollback()
    db.execute(text("BEGIN IMMEDIATE"))


def _commit_inbox(db: Session) -> None:
    db.commit()


def _safe_rollback(db: Session) -> None:
    try:
        db.rollback()
    except Exception:
        # A driver can leave the request session unusable after an ambiguous
        # commit. Recovery below never relies on this session.
        pass


def _matches_exact_evidence(
    row: models.BankWebhookEvent,
    normalized: NormalizedBankEvent,
    *,
    key: str,
    normalized_sha: str,
    envelope_sha: str,
) -> bool:
    return bool(
        row.provider == normalized.provider
        and row.provider_event_id == normalized.provider_event_id
        and row.idempotency_key == key
        and row.normalized_account_no == normalized.normalized_account_no
        and row.direction == normalized.direction
        and row.amount_vnd == normalized.amount_vnd
        and row.reference_state == normalized.reference_state
        and row.normalized_reference == normalized.normalized_reference
        and row.normalized_sha256 == normalized_sha
        and row.envelope_sha256 == envelope_sha
    )


def _recover_exact_winner(
    normalized: NormalizedBankEvent,
    *,
    key: str,
    normalized_sha: str,
    envelope_sha: str,
) -> models.BankWebhookEvent | None:
    """Read a possible durable winner from a clean post-failure session."""
    recovery = SessionLocal()
    try:
        winner = (
            recovery.query(models.BankWebhookEvent)
            .filter(
                models.BankWebhookEvent.provider == normalized.provider,
                models.BankWebhookEvent.idempotency_key == key,
                models.BankWebhookEvent.normalized_sha256 == normalized_sha,
                models.BankWebhookEvent.envelope_sha256 == envelope_sha,
            )
            .one_or_none()
        )
        if winner is None or not _matches_exact_evidence(
            winner,
            normalized,
            key=key,
            normalized_sha=normalized_sha,
            envelope_sha=envelope_sha,
        ):
            return None
        recovery.expunge(winner)
        return winner
    except Exception:
        return None
    finally:
        recovery.close()


def ingest_normalized(
    db: Session, normalized: NormalizedBankEvent, envelope: bytes
) -> tuple[models.BankWebhookEvent, bool]:
    normalized_sha = _digest(_canonical_normalized(normalized))
    envelope_sha = _digest(envelope)
    key = _idempotency_key(normalized, normalized_sha, envelope_sha)
    try:
        _acquire_inbox_write_lock(db)
        existing = (
            db.query(models.BankWebhookEvent)
            .filter(
                models.BankWebhookEvent.provider == normalized.provider,
                models.BankWebhookEvent.idempotency_key == key,
                models.BankWebhookEvent.normalized_sha256 == normalized_sha,
                models.BankWebhookEvent.envelope_sha256 == envelope_sha,
            )
            .one_or_none()
        )
        if existing is not None:
            db.rollback()
            return existing, True

        collision = False
        if normalized.provider_event_id is not None:
            identity_rows = (
                db.query(models.BankWebhookEvent)
                .filter(
                    models.BankWebhookEvent.provider == normalized.provider,
                    models.BankWebhookEvent.provider_event_id
                    == normalized.provider_event_id,
                )
                .all()
            )
            collision = any(
                row.normalized_sha256 != normalized_sha
                or row.envelope_sha256 != envelope_sha
                for row in identity_rows
            )

        reason, intent, order = _classify(db, normalized, collision=collision)
        now = _utc_now()
        row = models.BankWebhookEvent(
            provider=normalized.provider,
            provider_event_id=normalized.provider_event_id,
            idempotency_key=key,
            normalized_account_no=normalized.normalized_account_no,
            direction=normalized.direction,
            amount_vnd=normalized.amount_vnd,
            reference_state=normalized.reference_state,
            normalized_reference=normalized.normalized_reference,
            normalized_sha256=normalized_sha,
            envelope_sha256=envelope_sha,
            intent_id=intent.id if intent is not None and order is not None else None,
            order_id=order.id if order is not None else None,
            shop_id=order.shop_id if order is not None else None,
            payment_id=None,
            disposition="UNAPPLIED",
            reason_code=reason,
            received_at=now,
            updated_at=now,
            state_version=0,
        )
        db.add(row)
        _commit_inbox(db)
        db.refresh(row)
        return row, False
    except HTTPException:
        _safe_rollback(db)
        raise
    except Exception:
        _safe_rollback(db)
        winner = _recover_exact_winner(
            normalized,
            key=key,
            normalized_sha=normalized_sha,
            envelope_sha=envelope_sha,
        )
        if winner is not None:
            return winner, True
        raise _error(503, ERROR_PERSISTENCE, "Webhook evidence was not stored") from None


def process_envelope(
    db: Session, envelope: bytes, runtime: WebhookRuntime
) -> tuple[models.BankWebhookEvent, bool]:
    try:
        normalized = runtime.adapter.normalize(envelope)
    except (ValueError, UnicodeDecodeError, RecursionError, TypeError, OverflowError):
        raise _error(400, ERROR_BODY, "Webhook body is invalid") from None
    if not isinstance(normalized, NormalizedBankEvent):
        raise _error(400, ERROR_BODY, "Webhook body is invalid")
    return ingest_normalized(db, normalized, envelope)


def serialize_event(event: models.BankWebhookEvent, *, replay: bool | None = None) -> dict:
    result = {
        "id": int(event.id),
        "disposition": event.disposition,
        "reason_code": event.reason_code,
        "amount_vnd": event.amount_vnd,
        "direction": event.direction,
        "reference_state": event.reference_state,
        "received_at": event.received_at,
        "updated_at": event.updated_at,
        "state_version": int(event.state_version),
        "intent_id": event.intent_id,
        "order_id": event.order_id,
        "shop_id": event.shop_id,
    }
    if replay is not None:
        result["exact_replay"] = replay
    return result


__all__ = [
    "AuthMetadata",
    "DeterministicMockWebhookAdapter",
    "DisabledWebhookAdapter",
    "NormalizedBankEvent",
    "REASON_PROVIDER_COLLISION",
    "WebhookAdapter",
    "WebhookRuntime",
    "get_runtime",
    "ingest_normalized",
    "process_envelope",
    "read_authenticated_envelope",
    "report_only_test_runtime",
    "serialize_event",
    "validate_metadata",
]
