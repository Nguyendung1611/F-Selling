"""Request schemas cho ca thu ngân."""
from typing import Literal, Optional

from pydantic import BaseModel, Field

from ..core.numeric_limits import MAX_SAFE_VND
from .money import ExactVND


class ShiftOpen(BaseModel):
    opening_cash_amount: ExactVND = Field(default=0, ge=0, le=MAX_SAFE_VND)
    note: Optional[str] = Field(default=None, max_length=500)


class CashMovementCreate(BaseModel):
    movement_type: Literal["PAY_IN", "PAY_OUT"]
    amount: ExactVND = Field(gt=0, le=MAX_SAFE_VND)
    note: str = Field(min_length=1, max_length=500)
    operation_id: str = Field(min_length=8, max_length=128)


class ShiftClose(BaseModel):
    counted_cash_amount: ExactVND = Field(ge=0, le=MAX_SAFE_VND)
    note: Optional[str] = Field(default=None, max_length=500)
