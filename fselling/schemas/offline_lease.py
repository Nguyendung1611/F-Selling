"""HTTP contract nhỏ cho lifecycle credential bán offline I09-D."""

from typing import Optional

from pydantic import BaseModel, Field, field_validator


class OfflineLeaseIssue(BaseModel):
    shop_id: int
    device_id: str = Field(min_length=1, max_length=128)

    @field_validator("device_id", mode="before")
    @classmethod
    def trim_device_id(cls, value):
        return value.strip() if isinstance(value, str) else value


class OfflineLeaseRevoke(BaseModel):
    reason: str = Field(min_length=10, max_length=500)

    @field_validator("reason", mode="before")
    @classmethod
    def trim_reason(cls, value):
        return value.strip() if isinstance(value, str) else value


class OfflineLeaseStateResponse(BaseModel):
    lease_id: str
    shop_id: int
    user_id: int
    device_id: str
    contract_version: int
    status: str
    server_time_utc: str
    server_anchor_id: str
    anchor_server_time_utc: str
    issued_at: str
    expires_at: str
    catalog_version: int
    catalog_snapshot_digest: str
    state_version: int
    revoked_at: Optional[str] = None


class OfflineLeaseCredentialResponse(OfflineLeaseStateResponse):
    lease_token: str


__all__ = [
    "OfflineLeaseCredentialResponse",
    "OfflineLeaseIssue",
    "OfflineLeaseRevoke",
    "OfflineLeaseStateResponse",
]
