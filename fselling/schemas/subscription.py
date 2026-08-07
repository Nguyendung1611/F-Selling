"""Payload API gói Free/Pro."""
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class SubscriptionCheckoutCreate(BaseModel):
    cycle: Literal["MONTHLY", "YEARLY"]
    operation_id: str = Field(min_length=8, max_length=128)

    @field_validator("cycle", mode="before")
    @classmethod
    def normalize_cycle(cls, value):
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("operation_id", mode="before")
    @classmethod
    def clean_operation_id(cls, value):
        if not isinstance(value, str):
            return value
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("operation_id không được để trống")
        return cleaned


class SubscriptionGiftCreate(BaseModel):
    expires_on: date
    reason: str = Field(min_length=3, max_length=500)
    operation_id: str = Field(min_length=8, max_length=128)

    @field_validator("reason", "operation_id", mode="before")
    @classmethod
    def clean_required_text(cls, value):
        if not isinstance(value, str):
            return value
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Nội dung không được để trống")
        return cleaned


class SubscriptionGiftRevoke(BaseModel):
    reason: str = Field(min_length=3, max_length=500)
    operation_id: str = Field(min_length=8, max_length=128)

    @field_validator("reason", "operation_id", mode="before")
    @classmethod
    def clean_required_text(cls, value):
        if not isinstance(value, str):
            return value
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Nội dung không được để trống")
        return cleaned


__all__ = [
    "SubscriptionCheckoutCreate",
    "SubscriptionGiftCreate",
    "SubscriptionGiftRevoke",
]
