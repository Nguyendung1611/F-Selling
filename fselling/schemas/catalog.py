from typing import Optional

from pydantic import BaseModel


class ProductCreate(BaseModel):
    name: str
    price: float
    category_id: int
    image_url: Optional[str] = None


class CategoryUpdate(BaseModel):
    name: str
    is_active: bool


class VoucherCreate(BaseModel):
    code: str
    discount_type: str
    discount_value: float
    min_order_value: float = 0
    max_discount: float = 0
    usage_limit: int = -1
    expires_at: Optional[str] = None


class StockAdjust(BaseModel):
    delta: int  # >0 nhập kho, <0 xuất kho
