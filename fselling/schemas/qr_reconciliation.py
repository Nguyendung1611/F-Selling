"""Strict request contracts for the I10-C reconciliation command boundary."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from ..core.numeric_limits import MAX_SAFE_QUANTITY


SQLITE_SIGNED_INT64_MAX = 9_223_372_036_854_775_807
MAX_RECONCILIATION_ID = SQLITE_SIGNED_INT64_MAX
MAX_RECONCILIATION_STATE_VERSION = MAX_SAFE_QUANTITY


class ReconciliationActionRequest(BaseModel):
    """One compare-and-set command over durable normalized bank evidence."""

    model_config = ConfigDict(extra="forbid")

    expected_state_version: StrictInt = Field(
        ge=0, le=MAX_RECONCILIATION_STATE_VERSION
    )
    action: Literal[
        "KEEP_OPEN",
        "MAP_AND_APPLY",
        "REJECT_NOT_OURS",
        "MARK_REFUNDED_EXTERNALLY",
    ]
    target_intent_id: Optional[StrictInt] = Field(
        default=None, gt=0, le=MAX_RECONCILIATION_ID
    )
    note: Optional[str] = Field(default=None, max_length=500)

    @field_validator("target_intent_id", mode="before")
    @classmethod
    def reject_explicit_null_target(cls, value):
        if value is None:
            raise ValueError("target intent must be omitted or a positive integer")
        return value


__all__ = [
    "MAX_RECONCILIATION_ID",
    "MAX_RECONCILIATION_STATE_VERSION",
    "ReconciliationActionRequest",
    "SQLITE_SIGNED_INT64_MAX",
]
