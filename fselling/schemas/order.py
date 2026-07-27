from typing import List, Optional

from pydantic import BaseModel


class OrderItemCreate(BaseModel):
    product_name: str
    price: float
    quantity: int


class OrderCreate(BaseModel):
    items: List[OrderItemCreate]
    voucher_code: Optional[str] = None
    payment_method: str = "transfer"
    # Gắn khách vào đơn (tùy chọn). Bỏ trống = khách vãng lai.
    customer_id: Optional[int] = None


class PaymentWebhook(BaseModel):
    order_id: int
    status: Optional[str] = "PAID"
    transaction_id: Optional[str] = None
    amount: Optional[float] = None
