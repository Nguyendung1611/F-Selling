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


class PaymentWebhook(BaseModel):
    order_id: int
    status: Optional[str] = "PAID"
    transaction_id: Optional[str] = None
    amount: Optional[float] = None
