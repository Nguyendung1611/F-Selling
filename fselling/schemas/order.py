from typing import List, Optional

from pydantic import BaseModel


class OrderItemCreate(BaseModel):
    """Một dòng hàng do client gửi lên.

    `product_id` là cách định danh chuẩn. `product_name` được giữ lại cho client
    cũ và chỉ dùng khi không có `product_id`: khớp theo tên không tin cậy vì tên
    có thể đổi, và trước đây hai sản phẩm trùng tên là gộp nhầm dòng.
    Phải có ít nhất một trong hai (kiểm ở `inventory_service`).

    `price` được nhận nhưng KHÔNG dùng để tính tiền - giá luôn lấy lại từ
    database, không tin giá client gửi.
    """

    product_id: Optional[int] = None
    product_name: Optional[str] = None
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
