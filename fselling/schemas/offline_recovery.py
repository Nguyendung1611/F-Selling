"""Strict HTTP models for owner-authorized offline receipt recovery."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from ..core.numeric_limits import MAX_SAFE_QUANTITY, MAX_SAFE_VND


class RecoveryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: int = Field(strict=True, ge=1, le=MAX_SAFE_QUANTITY)
    product_name: str = Field(min_length=1, max_length=300)
    unit_price_vnd: int = Field(strict=True, ge=0, le=MAX_SAFE_VND)
    quantity: int = Field(strict=True, ge=1, le=MAX_SAFE_QUANTITY)


class RecoveryReceiptV0(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal[0]
    offline_uuid: str = Field(min_length=8, max_length=64)
    sold_at_utc: str = Field(min_length=19, max_length=64)
    items: list[RecoveryItem] = Field(min_length=1, max_length=200)
    cash_tendered_vnd: int = Field(strict=True, ge=0, le=MAX_SAFE_VND)


class RecoveryReceiptV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal[1]
    lease_id: str = Field(min_length=1, max_length=128)
    device_id: str = Field(min_length=1, max_length=128)
    offline_session_id: str = Field(min_length=1, max_length=128)
    sequence: int = Field(strict=True, ge=1, le=MAX_SAFE_QUANTITY)
    offline_uuid: str = Field(min_length=8, max_length=64)
    sold_at_client_utc: str = Field(min_length=19, max_length=64)
    client_monotonic_ms: int = Field(strict=True, ge=0, le=MAX_SAFE_QUANTITY)
    monotonic_valid: bool = Field(strict=True)
    server_anchor_id: str = Field(min_length=1, max_length=128)
    catalog_version: int = Field(strict=True, ge=0, le=MAX_SAFE_QUANTITY)
    # This is a public receipt-contract field, not the secret lease-token digest.
    catalog_snapshot_digest: str = Field(
        min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )
    items: list[RecoveryItem] = Field(min_length=1, max_length=200)
    cash_tendered_vnd: int = Field(strict=True, ge=0, le=MAX_SAFE_VND)


class RecoveryLineResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_ordinal: int = Field(strict=True, ge=1, le=200)
    action: Literal["MAP", "ACCEPT_UNKNOWN"]
    product_id: Optional[int] = Field(
        default=None, strict=True, ge=1, le=MAX_SAFE_QUANTITY
    )


class RecoveryResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Required for staged/replacement recovery.  Normal-ingested v0 catalog
    # issues can be resolved from durable order/receipt/issue evidence alone.
    document: Optional[dict] = None
    state_version: int = Field(strict=True, ge=0, le=MAX_SAFE_QUANTITY)
    reason: str = Field(min_length=10, max_length=500)
    line_resolutions: list[RecoveryLineResolution] = Field(
        default_factory=list, max_length=200
    )
    sold_at_effective_utc: Optional[str] = Field(
        default=None, min_length=19, max_length=64
    )


__all__ = [
    "RecoveryItem",
    "RecoveryLineResolution",
    "RecoveryReceiptV0",
    "RecoveryReceiptV1",
    "RecoveryResolveRequest",
]
