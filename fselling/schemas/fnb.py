from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from ..core.numeric_limits import MAX_SAFE_QUANTITY

OperationId = str


class FnbRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FnbSettingsUpdate(FnbRequest):
    enabled: bool
    expected_revision: int = Field(ge=0, le=MAX_SAFE_QUANTITY)
    operation_id: OperationId = Field(min_length=8, max_length=128)


class FnbAreaCreate(FnbRequest):
    shop_id: int
    name: str = Field(min_length=1, max_length=100)
    sort_order: int = Field(default=0, ge=0, le=MAX_SAFE_QUANTITY)
    expected_revision: int = Field(ge=0, le=MAX_SAFE_QUANTITY)
    operation_id: OperationId = Field(min_length=8, max_length=128)


class FnbAreaUpdate(FnbRequest):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    sort_order: Optional[int] = Field(default=None, ge=0, le=MAX_SAFE_QUANTITY)
    active: Optional[bool] = None
    expected_revision: int = Field(ge=0, le=MAX_SAFE_QUANTITY)
    operation_id: OperationId = Field(min_length=8, max_length=128)


class FnbTableCreate(FnbRequest):
    shop_id: int
    area_id: int
    name: str = Field(min_length=1, max_length=100)
    sort_order: int = Field(default=0, ge=0, le=MAX_SAFE_QUANTITY)
    expected_revision: int = Field(ge=0, le=MAX_SAFE_QUANTITY)
    operation_id: OperationId = Field(min_length=8, max_length=128)


class FnbTableUpdate(FnbRequest):
    area_id: Optional[int] = None
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    sort_order: Optional[int] = Field(default=None, ge=0, le=MAX_SAFE_QUANTITY)
    active: Optional[bool] = None
    expected_revision: int = Field(ge=0, le=MAX_SAFE_QUANTITY)
    expected_state_version: int = Field(ge=0, le=MAX_SAFE_QUANTITY)
    operation_id: OperationId = Field(min_length=8, max_length=128)
