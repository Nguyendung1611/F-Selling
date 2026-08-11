"""Canonical server fingerprint for legacy offline receipt contract v0."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from ..core.money import checked_quantity, checked_vnd

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
]
