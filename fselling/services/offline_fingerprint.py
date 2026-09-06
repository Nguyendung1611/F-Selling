"""Canonical server fingerprint for legacy offline receipt contract v0."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from ..core.money import checked_add, checked_multiply, checked_quantity, checked_vnd

FINGERPRINT_PREFIX_V0 = b"FS-OFFLINE-RECEIPT-v0\n"
FINGERPRINT_LABEL_V0 = "fsofr0:"


@dataclass(frozen=True)
class CanonicalOfflineItemV0:
    product_id: int
    product_name: str
    unit_price_vnd: int
    quantity: int


@dataclass(frozen=True)
class OfflineFingerprintV0:
    offline_uuid: str
    sold_at_utc: datetime
    sold_at_text: str
    device_label: str | None
    items: tuple[CanonicalOfflineItemV0, ...]
    canonical_json: str
    fingerprint: str


def canonical_utc_naive(value: datetime) -> datetime:
    """Convert an aware instant to UTC; interpret a naive value as UTC."""
    if not isinstance(value, datetime):
        raise ValueError("sold_at must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=None)
    try:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    except (OverflowError, OSError) as exc:
        # A boundary year with a large offset (year 1 at +14:00) shifts outside
        # datetime.min/max.  That is unrepresentable input, not a server fault:
        # callers translate ValueError into HTTP 400 before any side effect.
        raise ValueError("sold_at is outside the representable UTC range") from exc


def canonical_time_text(value: datetime) -> str:
    return canonical_utc_naive(value).strftime("%Y-%m-%d %H:%M:%S.%f")


def _reject_forbidden_text(value: str) -> None:
    for char in value:
        codepoint = ord(char)
        if (
            codepoint <= 0x1F
            or 0x7F <= codepoint <= 0x9F
            or 0x200B <= codepoint <= 0x200D
            or codepoint == 0xFEFF
        ):
            raise ValueError("offline receipt text contains a forbidden character")


def normalize_text(value: str) -> str:
    """NFC, Unicode trim and whitespace collapse without case folding."""
    if not isinstance(value, str):
        raise ValueError("offline receipt text must be a string")
    normalized = unicodedata.normalize("NFC", value)
    _reject_forbidden_text(normalized)
    return " ".join(normalized.split())


def normalize_nullable_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = normalize_text(value)
    return normalized or None


def normalize_offline_uuid(value: str) -> str:
    """The v0 identifier is NFC-normalized and trimmed, never case-folded."""
    if not isinstance(value, str):
        raise ValueError("offline_uuid must be a string")
    normalized = unicodedata.normalize("NFC", value)
    _reject_forbidden_text(normalized)
    return normalized.strip()


def _field(item: Any, name: str) -> Any:
    if isinstance(item, Mapping):
        return item[name]
    return getattr(item, name)


def _strict_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer")
    return value


def fingerprint_offline_receipt_v0(
    *,
    shop_id: int,
    offline_uuid: str,
    sold_at: datetime,
    items: Iterable[Any],
    cash_tendered_vnd: int,
    device_label: str | None,
) -> OfflineFingerprintV0:
    """Build the exact six-field v0 document and its SHA-256 fingerprint."""
    canonical_shop_id = _strict_int(shop_id, "shop_id")
    canonical_tendered = checked_vnd(
        _strict_int(cash_tendered_vnd, "cash_tendered_vnd")
    )
    canonical_uuid = normalize_offline_uuid(offline_uuid)
    canonical_sold_at = canonical_utc_naive(sold_at)
    sold_at_text = canonical_time_text(canonical_sold_at)
    canonical_device = normalize_nullable_text(device_label)

    canonical_items = []
    for item in items:
        product_id = _strict_int(_field(item, "product_id"), "product_id")
        quantity = checked_quantity(
            _strict_int(_field(item, "quantity"), "quantity"), positive=True
        )
        price_source = (
            _field(item, "unit_price_vnd")
            if isinstance(item, Mapping) and "unit_price_vnd" in item
            else _field(item, "unit_price")
        )
        unit_price = checked_vnd(_strict_int(price_source, "unit_price_vnd"))
        product_name = normalize_text(_field(item, "product_name"))
        if not product_name:
            # `product_name` is required evidence: for a product deleted between
            # the sale and the sync it is the only thing tying the cash in the
            # drawer back to what was sold.  A string of Unicode whitespace
            # passes the request schema but collapses to '' here, so it must be
            # rejected before any side effect.  Nullable `device_label` keeps
            # its own contract: whitespace-only stays canonical NULL.
            raise ValueError("product_name must not be empty after normalization")
        canonical_items.append(
            CanonicalOfflineItemV0(
                product_id=product_id,
                product_name=product_name,
                unit_price_vnd=unit_price,
                quantity=quantity,
            )
        )

    canonical_items.sort(
        key=lambda item: (
            item.product_id,
            item.product_name.encode("utf-8"),
            item.unit_price_vnd,
            item.quantity,
        )
    )
    document = {
        "shop_id": canonical_shop_id,
        "offline_uuid": canonical_uuid,
        "sold_at_utc": sold_at_text,
        "items": [
            {
                "product_id": item.product_id,
                "product_name": item.product_name,
                "unit_price_vnd": item.unit_price_vnd,
                "quantity": item.quantity,
            }
            for item in canonical_items
        ],
        "cash_tendered_vnd": canonical_tendered,
        "device_label": canonical_device,
    }
    canonical_json = json.dumps(
        document,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(
        FINGERPRINT_PREFIX_V0 + canonical_json.encode("utf-8")
    ).hexdigest()
    return OfflineFingerprintV0(
        offline_uuid=canonical_uuid,
        sold_at_utc=canonical_sold_at,
        sold_at_text=sold_at_text,
        device_label=canonical_device,
        items=tuple(canonical_items),
        canonical_json=canonical_json,
        fingerprint=FINGERPRINT_LABEL_V0 + digest,
    )


__all__ = [
    # v0
    "CanonicalOfflineItemV0",
    "FINGERPRINT_LABEL_V0",
    "FINGERPRINT_PREFIX_V0",
    "OfflineFingerprintV0",
    "canonical_time_text",
    "canonical_utc_naive",
    "fingerprint_offline_receipt_v0",
    "normalize_nullable_text",
    "normalize_offline_uuid",
    "normalize_text",
    # v1
    "CanonicalOfflineItemV1",
    "FINGERPRINT_LABEL_V1",
    "FINGERPRINT_PREFIX_V1",
    "OfflineFingerprintV1",
    "OfflineTotalOverflowError",
    "fingerprint_offline_receipt_v1",
    "canonical_time_text_v1",
]


# ---------------------------------------------------------------------------
# Offline contract v1 canonical fingerprint (I09-E+B2)
# Server recomputes from durable evidence; client digest is for comparison only.
# ---------------------------------------------------------------------------

FINGERPRINT_PREFIX_V1 = b"FS-OFFLINE-RECEIPT-v1\n"
FINGERPRINT_LABEL_V1 = "fsofr1:"


# Separators per spec: \x1f field, \x1e record, \n block
_V1_FIELD_SEP = "\x1f"
_V1_RECORD_SEP = "\x1e"


@dataclass(frozen=True)
class CanonicalOfflineItemV1:
    product_id: int
    product_name: str
    unit_price_vnd: int
    quantity: int


@dataclass(frozen=True)
class OfflineFingerprintV1:
    """Full v1 canonical document and computed server digest."""

    offline_uuid: str                # from input, in header
    sold_at_client_utc: str          # canonical UTC-naive fixed-width text
    client_monotonic_ms: int
    monotonic_valid: bool
    server_anchor_id: str
    catalog_version: int
    catalog_snapshot_digest: str
    cash_tendered_vnd: int
    total_vnd: int                  # server-computed
    item_count: int                 # server-computed
    items: tuple[CanonicalOfflineItemV1, ...]
    canonical_bytes: bytes
    digest: str                      # "fsofr1:" + sha256(canonical_bytes)


class OfflineTotalOverflowError(ValueError):
    """The server-computed v1 total exceeds the exact VND domain."""


def _v1_strict_int(value, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer")
    return value


def _v1_checked_vnd(value: int, label: str) -> int:
    """Strict non-negative VND."""
    v = _v1_strict_int(value, label)
    if v < 0:
        raise ValueError(f"{label} must be non-negative")
    return v


def canonical_time_text_v1(value: str | datetime) -> str:
    """Normalize an ISO instant to fixed-width UTC-naive text."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        raw = value.strip()
        if raw.endswith(("Z", "z")):
            raw = raw[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise ValueError("sold_at_client_utc must be an ISO-8601 timestamp") from exc
    else:
        raise ValueError("sold_at_client_utc must be a string or datetime")
    return canonical_time_text(parsed)


def _v1_normalize_name(value: str) -> str:
    """NFC, Unicode trim + collapse whitespace to single U+0020; no casefold."""
    if not isinstance(value, str):
        raise ValueError("product_name must be a string")
    normalized = unicodedata.normalize("NFC", value)
    # Reject forbidden characters (C0/C1, zero-width, BOM, surrogate odd)
    for char in normalized:
        cp = ord(char)
        if (
            cp <= 0x1F
            or 0x7F <= cp <= 0x9F
            or 0x200B <= cp <= 0x200D
            or cp == 0xFEFF
            or 0xD800 <= cp <= 0xDFFF
        ):
            raise ValueError("product name contains forbidden character")
        # Reject Unicode separators (U+2028, U+2029)
        if cp in (0x2028, 0x2029):
            raise ValueError("product name contains forbidden character")
    # Collapse whitespace and trim
    result = " ".join(normalized.split())
    if not result:
        raise ValueError("product_name must not be empty after normalization")
    if len(result) > 300:
        raise ValueError("product name exceeds 300 code points")
    _v1_encode(result)
    return result


def _v1_encode(value: str) -> bytes:
    """UTF-8 encode; raise if exceeds 900 bytes."""
    b = value.encode("utf-8")
    if len(b) > 900:
        raise ValueError("product name exceeds 900 UTF-8 bytes")
    return b


def _v1_text(value: Any, label: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    for char in value:
        cp = ord(char)
        if cp <= 0x1F or 0x7F <= cp <= 0x9F or 0xD800 <= cp <= 0xDFFF:
            raise ValueError(f"{label} contains a forbidden character")
    if not value and not allow_empty:
        raise ValueError(f"{label} must not be empty")
    return value


def fingerprint_offline_receipt_v1(
    *,
    shop_id: int,
    sold_at_client_utc: str,
    client_monotonic_ms: int,
    monotonic_valid: bool,
    server_anchor_id: str,
    lease_id: str,
    device_id: str,
    offline_session_id: str,
    sequence: int,
    offline_uuid: str,
    catalog_version: int,
    catalog_snapshot_digest: str,
    items: list,
    cash_tendered_vnd: int,
) -> OfflineFingerprintV1:
    """Build the exact v1 canonical document and its SHA-256 fingerprint.

    Digest = "fsofr1:" + lowercase(sha256(canonical_bytes UTF-8)).

    Items are sorted by (product_id, normalized_name UTF-8 bytes, unit_price,
    quantity). Duplicate tuples are kept intact. total_vnd and item_count are
    server-computed from items.

    Client fingerprint is stored for comparison only; server always recomputes.
    """
    canonical_shop_id = _v1_strict_int(shop_id, "shop_id")
    if canonical_shop_id < 1:
        raise ValueError("shop_id must be positive")

    canonical_lease_id = _v1_text(lease_id, "lease_id")
    canonical_device_id = _v1_text(device_id, "device_id")
    canonical_session_id = _v1_text(offline_session_id, "offline_session_id")
    canonical_uuid = _v1_text(offline_uuid, "offline_uuid")
    canonical_anchor_id = _v1_text(server_anchor_id, "server_anchor_id")
    canonical_catalog_digest = _v1_text(
        catalog_snapshot_digest, "catalog_snapshot_digest"
    )

    canonical_sequence = _v1_strict_int(sequence, "sequence")
    if canonical_sequence < 1:
        raise ValueError("sequence must be positive")

    # Validate and canonicalize wall time text.
    canonical_time = canonical_time_text_v1(sold_at_client_utc)

    # Validate monotonic_ms
    monotonic_ms = _v1_strict_int(client_monotonic_ms, "client_monotonic_ms")
    if monotonic_ms < 0:
        raise ValueError("client_monotonic_ms must be non-negative")

    # Validate monotonic_valid is bool
    if not isinstance(monotonic_valid, bool):
        raise ValueError("monotonic_valid must be a boolean")

    # Validate catalog
    catalog_ver = _v1_strict_int(catalog_version, "catalog_version")
    if catalog_ver < 0:
        raise ValueError("catalog_version must be non-negative")

    # Validate cash tendered
    tendered = _v1_checked_vnd(cash_tendered_vnd, "cash_tendered")

    # Parse and canonicalize items
    canonical_items: list[CanonicalOfflineItemV1] = []
    running_total: int = 0

    raw_items = list(items)
    if not 1 <= len(raw_items) <= 200:
        raise ValueError("items must contain between 1 and 200 rows")
    for raw_item in raw_items:
        if isinstance(raw_item, dict):
            pid = _v1_strict_int(raw_item["product_id"], "product_id")
            name_raw = raw_item.get("product_name", "")
            price = _v1_strict_int(raw_item["unit_price_vnd"], "unit_price_vnd")
            qty = _v1_strict_int(raw_item["quantity"], "quantity")
        else:
            pid = _v1_strict_int(getattr(raw_item, "product_id"), "product_id")
            name_raw = getattr(raw_item, "product_name", "")
            price = _v1_strict_int(getattr(raw_item, "unit_price_vnd"), "unit_price_vnd")
            qty = _v1_strict_int(getattr(raw_item, "quantity"), "quantity")

        if pid < 1:
            raise ValueError("product_id must be positive")
        if qty < 1:
            raise ValueError("quantity must be positive")
        if price < 0:
            raise ValueError("unit_price_vnd must be non-negative")

        name_canonical = _v1_normalize_name(name_raw)

        canonical_items.append(
            CanonicalOfflineItemV1(
                product_id=pid,
                product_name=name_canonical,
                unit_price_vnd=price,
                quantity=qty,
            )
        )

        # Server-computes total with the same bounded exact arithmetic used by
        # persisted VND values.  Python's unbounded int must not silently widen
        # the financial contract.
        try:
            running_total = checked_add(
                running_total,
                checked_multiply(qty, price),
            )
        except ValueError as exc:
            raise OfflineTotalOverflowError("offline total exceeds exact VND limit") from exc

    item_count = len(canonical_items)

    # Sort items: (product_id, normalized_name UTF-8 bytes, unit_price, quantity)
    canonical_items.sort(
        key=lambda item: (
            item.product_id,
            item.product_name.encode("utf-8"),
            item.unit_price_vnd,
            item.quantity,
        )
    )

    # Build canonical bytes
    def _v1_field(*parts: str) -> bytes:
        return _V1_FIELD_SEP.encode().join(p.encode("utf-8") for p in parts)

    def _v1_int(n: int) -> str:
        return str(n)

    def _v1_bool(b: bool) -> str:
        return "1" if b else "0"

    # Assemble
    # Header 1 (field line) — shop_id, contract_version, lease_id, device_id,
    # offline_session_id, sequence, offline_uuid all in header
    header_bytes = (
        FINGERPRINT_PREFIX_V1
        + _v1_field(
            _v1_int(canonical_shop_id),
            _v1_int(1),
            canonical_lease_id,
            canonical_device_id,
            canonical_session_id,
            _v1_int(canonical_sequence),
            canonical_uuid,
        )
        + b"\n"
    )
    # Time line
    time_bytes = (
        _v1_field(
            canonical_time,
            _v1_int(monotonic_ms),
            _v1_bool(monotonic_valid),
            canonical_anchor_id,
        )
        + b"\n"
    )
    # Catalog line
    catalog_bytes = (
        _v1_field(_v1_int(catalog_ver), canonical_catalog_digest)
        + b"\n"
    )
    # Cash summary line
    cash_bytes = (
        _v1_field(
            "CASH",
            _v1_int(tendered),
            _v1_int(running_total),
            _v1_int(item_count),
        )
        + b"\n"
    )

    # Records section: one line per item, field-sep, record-sep between items
    record_parts: list[bytes] = []
    for item in canonical_items:
        record_parts.append(
            _v1_field(
                _v1_int(item.product_id),
                item.product_name,
                _v1_int(item.unit_price_vnd),
                _v1_int(item.quantity),
            )
        )
    records_block = _V1_RECORD_SEP.encode().join(record_parts) + b"\n"

    canonical_bytes = (
        header_bytes
        + time_bytes
        + catalog_bytes
        + cash_bytes
        + records_block
    )

    digest = hashlib.sha256(canonical_bytes).hexdigest()

    return OfflineFingerprintV1(
        offline_uuid=canonical_uuid,
        sold_at_client_utc=canonical_time,
        client_monotonic_ms=monotonic_ms,
        monotonic_valid=monotonic_valid,
        server_anchor_id=canonical_anchor_id,
        catalog_version=catalog_ver,
        catalog_snapshot_digest=canonical_catalog_digest,
        cash_tendered_vnd=tendered,
        total_vnd=running_total,
        item_count=item_count,
        items=tuple(canonical_items),
        canonical_bytes=canonical_bytes,
        digest=FINGERPRINT_LABEL_V1 + digest,
    )
