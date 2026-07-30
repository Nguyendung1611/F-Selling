"""Request schemas cho ca thu ngân."""
from typing import Literal, Optional

from pydantic import BaseModel, Field, FiniteFloat


class ShiftOpen(BaseModel):
    opening_cash_amount: FiniteFloat = Field(default=0, ge=0)
    note: Optional[str] = Field(default=None, max_length=500)


class CashMovementCreate(BaseModel):
    movement_type: Literal["PAY_IN", "PAY_OUT"]
    amount: FiniteFloat = Field(gt=0)
    # Bắt buộc lý do để mọi khoản tiền ngoài bán hàng đều có thể kiểm tra lại.
    note: str = Field(min_length=1, max_length=500)
    # Client dùng lại cùng mã khi retry. Unique index ở DB mới là lớp bảo vệ
    # cuối cùng trước double-click/hai request chạy đồng thời.
    operation_id: str = Field(min_length=8, max_length=128)


class ShiftClose(BaseModel):
    counted_cash_amount: FiniteFloat = Field(ge=0)
    note: Optional[str] = Field(default=None, max_length=500)
