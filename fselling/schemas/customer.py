from typing import Optional

from pydantic import BaseModel, Field

from ..core.numeric_limits import MAX_SAFE_VND
from .money import SignedExactVND


class CustomerCreate(BaseModel):
    name: str
    phone: str
    address: Optional[str] = None
    note: Optional[str] = None
    # F4: trần công nợ. None = không giới hạn (mặc định).
    # Giá trị âm phải đến service để giữ HTTP 400 lịch sử của _kiem_han_muc.
    # Parser vẫn chỉ nhận biểu diễn VND nguyên chính xác và chặn quá giới hạn.
    credit_limit: Optional[SignedExactVND] = Field(
        default=None, ge=-MAX_SAFE_VND, le=MAX_SAFE_VND
    )


class CustomerUpdate(BaseModel):
    name: str
    phone: str
    address: Optional[str] = None
    note: Optional[str] = None
    credit_limit: Optional[SignedExactVND] = Field(
        default=None, ge=-MAX_SAFE_VND, le=MAX_SAFE_VND
    )


class CustomerStatusUpdate(BaseModel):
    is_active: bool
