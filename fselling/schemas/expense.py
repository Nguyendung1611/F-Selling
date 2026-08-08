"""Request schemas cho chi phí vận hành."""
from typing import Literal, Optional

from pydantic import BaseModel, Field, StrictInt

from ..core.numeric_limits import MAX_SAFE_VND


class ExpenseCategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class ExpenseCategoryUpdate(BaseModel):
    """Đổi tên và/hoặc ẩn-hiện. CỐ Ý không có đường xóa vật lý."""

    name: Optional[str] = Field(default=None, max_length=120)
    is_active: Optional[bool] = None


class ExpenseTemplateCreate(BaseModel):
    category_id: StrictInt = Field(gt=0)
    name: Optional[str] = Field(default=None, max_length=200)
    amount: StrictInt = Field(ge=0, le=MAX_SAFE_VND)
    day_of_month: StrictInt = Field(default=1, ge=1, le=31)
    note: Optional[str] = Field(default=None, max_length=500)


class ExpenseTemplateUpdate(BaseModel):
    category_id: Optional[StrictInt] = Field(default=None, gt=0)
    name: Optional[str] = Field(default=None, max_length=200)
    amount: Optional[StrictInt] = Field(default=None, ge=0, le=MAX_SAFE_VND)
    day_of_month: Optional[StrictInt] = Field(default=None, ge=1, le=31)
    note: Optional[str] = Field(default=None, max_length=500)
    is_active: Optional[bool] = None


class ExpenseCreate(BaseModel):
    """Một khoản chi đã trả.

    ``amortize_months`` là cách khai trả trước: None nghĩa là tính hết vào ngày
    chi (đường thường), còn N nghĩa là khoản này phục vụ N tháng kể từ
    ``amortize_start_date``. Ngày kết thúc do SERVER tính, không nhận từ client
    — quy tắc "cùng ngày N tháng sau, trừ một ngày, tháng thiếu ngày thì lùi về
    cuối tháng" chỉ được viết ở một chỗ (``expense_service.cong_thang``) để
    giao diện và dữ liệu không bao giờ nói hai điều khác nhau.

    ``amortize_start_date`` mặc định bằng ngày chi, và tách riêng ra để khai
    được khoản TRẢ SAU: mùng 3 tháng 9 đóng tiền điện của tháng 8 thì tiền ra
    ngày 3/9 nhưng chi phí thuộc về tháng 8.
    """

    category_id: StrictInt = Field(gt=0)
    template_id: Optional[StrictInt] = Field(default=None, gt=0)
    amount: StrictInt = Field(gt=0, le=MAX_SAFE_VND)
    expense_date: Optional[str] = Field(default=None, max_length=10)
    amortize_months: Optional[StrictInt] = Field(default=None, ge=1, le=120)
    amortize_start_date: Optional[str] = Field(default=None, max_length=10)
    method: Literal["CASH_SHIFT", "TRANSFER", "OUTSIDE"]
    note: Optional[str] = Field(default=None, max_length=500)
    reference: Optional[str] = Field(default=None, max_length=128)
    operation_id: str = Field(min_length=8, max_length=128)


__all__ = [
    "ExpenseCategoryCreate",
    "ExpenseCategoryUpdate",
    "ExpenseTemplateCreate",
    "ExpenseTemplateUpdate",
    "ExpenseCreate",
]
