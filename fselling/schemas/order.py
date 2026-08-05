from datetime import datetime
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
    operation_id: Optional[str] = Field(default=None, min_length=8, max_length=128)
    # Gắn khách vào đơn (tùy chọn). Bỏ trống = khách vãng lai.
    customer_id: Optional[int] = None


class OfflineOrderItem(BaseModel):
    """Một dòng hàng trên phiếu đã bán khi mất mạng.

    `unit_price` ở đây KHÁC HẲN `price` của `OrderItemCreate`: chỗ kia bị bỏ đi
    và server tính lại từ database, còn chỗ này là **giá khách đã thật sự trả**
    và server phải tôn trọng. Tính lại theo giá hôm nay là ghi sai số tiền đã
    nằm trong két — xem bẫy 28 trong KIEN_TRUC.md.

    `product_name` là bản chụp tên lúc bán, dùng khi sản phẩm đã bị xóa giữa
    lúc bán và lúc đồng bộ: mất tên thì dòng tiền đó không còn tra được về đâu.
    """

    product_id: int
    product_name: str = Field(min_length=1, max_length=300)
    unit_price: float = Field(ge=0)
    quantity: int = Field(gt=0)


class OfflineOrderCreate(BaseModel):
    """Phiếu bán offline gửi lên khi máy có mạng trở lại.

    CỐ Ý không có `voucher_code`, `customer_id` hay `payment_method`: khi mất
    mạng chỉ bán được TIỀN MẶT. Voucher cần đếm lượt dùng trên server, ghi nợ
    cần kiểm hạn mức trên server — cả hai không kiểm được lúc offline, và đoán
    bừa thì hậu quả là tiền.
    """

    offline_uuid: str = Field(min_length=8, max_length=64)
    # Giờ bán theo UTC. Server dùng nó để chọn ca thu ngân, KHÔNG dùng giờ sync.
    sold_at: datetime
    items: List[OfflineOrderItem] = Field(min_length=1)
    # Tiền khách đưa. Nhỏ hơn tổng đơn là phiếu sai, server từ chối.
    cash_tendered: float = Field(ge=0)
    device_label: Optional[str] = Field(default=None, max_length=64)


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


class CashPayment(BaseModel):
    """Tiền khách thực đưa khi thanh toán một đơn tiền mặt.

    Server tự tính tiền thừa từ tổng đơn đã chốt trong DB; client không được
    gửi hay tự quyết định số tiền phải trả lại.
    """

    tendered_amount: float


class OrderReturnItemCreate(BaseModel):
    """Một dòng khách mang trả.

    Định danh bằng `order_item_id` chứ không phải `product_id`: dòng đơn mới là
    thứ giữ giá bán và giá vốn đã chốt lúc bán, và là mốc để biết còn được trả
    bao nhiêu.
    """

    order_item_id: int
    quantity: int
    # Hàng còn tốt thì cộng lại tồn kho; hàng hỏng/bẩn/hết hạn thì vẫn hoàn tiền
    # nhưng KHÔNG được quay lại kệ.
    restock: bool = True


class OrderReturnCreate(BaseModel):
    """Một lần nhận hàng trả. Server tự tính tiền hoàn, client không gửi số tiền.

    `method` được phép bỏ trống khi tiền hoàn bằng 0 (đơn giảm giá 100%).
    """

    items: List[OrderReturnItemCreate]
    method: Optional[Literal["cash", "transfer"]] = None
    reason: Optional[str] = None
    note: Optional[str] = None
    reference: Optional[str] = None
    # Một id cho đúng MỘT lần bấm nhận trả. Retry mạng dùng lại id này nên không
    # thể vô tình tạo hai phiếu trả cho cùng một lần khách mang hàng đến.
    operation_id: str = Field(min_length=8, max_length=128)


class DebtPayment(BaseModel):
    """Một lần khách trả bớt nợ. Trả bao nhiêu cũng được, nhiều lần cũng được.

    Khác `CashTopup` ở chỗ đó: `CashTopup` bắt trả trọn phần còn thiếu vì nó
    dành cho đơn chuyển khoản thiếu, còn trả nợ dần là chuyện bình thường của
    bán ghi sổ.
    """

    amount: float
    method: Literal["cash", "transfer"]
    note: Optional[str] = None
    reference: Optional[str] = None
    # Một id cho đúng MỘT lần bấm thu tiền. Retry mạng dùng lại id này nên không
    # ghi thành hai lần trả.
    operation_id: str = Field(min_length=8, max_length=128)


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
