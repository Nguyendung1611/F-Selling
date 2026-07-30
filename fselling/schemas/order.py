from typing import List, Literal, Optional

from pydantic import BaseModel, Field


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


class CashTopup(BaseModel):
    """Khoản tiền mặt bù cho đơn chuyển thiếu.

    Server luôn thu đúng toàn bộ số còn thiếu. `amount` được giữ để client hiện
    tại gửi con số đang thấy, nhưng phải khớp phần thiếu tại lúc xử lý.
    """

    amount: Optional[float] = None
    note: Optional[str] = None


class RefundComplete(BaseModel):
    """Ghi nhận shop đã hoàn đúng toàn bộ khoản đang chờ.

    Không nhận số tiền từ client: server khóa theo `refund_due_amount`.
    """

    method: Literal["cash", "transfer"]
    note: Optional[str] = None
    reference: Optional[str] = None
    # Một id cho đúng MỘT lần bấm hoàn. Retry mạng dùng lại id này nên không thể
    # vô tình xác nhận hộ một khoản dư mới xuất hiện sau đó.
    operation_id: str = Field(min_length=8, max_length=128)
