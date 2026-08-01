import datetime

from sqlalchemy import CheckConstraint, Column, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import relationship

from ..core.database import Base


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        Index("ux_orders_operation_id", "operation_id", unique=True),
    )
    id = Column(Integer, primary_key=True, index=True)
    shop_id = Column(Integer, ForeignKey("shops.id"))
    total_amount = Column(Float)
    discount_amount = Column(Float, default=0)
    voucher_code = Column(String, nullable=True)
    payment_method = Column(String, default="transfer")  # 'transfer' or 'cash'
    status = Column(String, default="PENDING")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    # Mã do web client giữ lại khi retry tạo đơn. Unique ở DB để lỗi mạng hoặc
    # double-click không thể trừ kho/tăng voucher hai lần.
    operation_id = Column(String(128), nullable=True)
    operation_fingerprint = Column(String(64), nullable=True)
    # Người tạo và ca bán hàng là dấu vết server-side. Nullable để giữ được
    # đơn legacy; service tạo đơn mới sẽ luôn gắn từ current_user/ca đang mở.
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    shift_id = Column(Integer, ForeignKey("cash_shifts.id"), nullable=True, index=True)
    # Tiền khách đưa và tiền thối là ảnh chụp của lần thu tiền mặt. Số thực giữ
    # lại cho đơn vẫn nằm ở cash_paid_amount/OrderPayment.
    cash_tendered_amount = Column(Float, nullable=True)
    cash_change_amount = Column(Float, nullable=True)
    # Khách hàng gắn vào đơn (tùy chọn). NULL với đơn khách vãng lai. (C2a)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True, index=True)
    # D1: tổng tiền THỰC NHẬN qua webhook ngân hàng và mã giao dịch gần nhất.
    # `bank_txn_id` cố ý KHÔNG unique: retry webhook là bình thường; chống xử
    # lý lặp nằm ở `OrderPayment.idempotency_key`.
    paid_amount = Column(Float, nullable=True)
    bank_txn_id = Column(String(128), nullable=True, index=True)
    # D4: tiền bù mặt được tách khỏi tiền ngân hàng để hóa đơn và đối soát nêu
    # đúng nguồn. Số đã hoàn là tổng lũy kế; refund_due_amount chỉ là khoản còn
    # phải hoàn ở thời điểm hiện tại.
    cash_paid_amount = Column(Float, nullable=False, default=0)
    refunded_amount = Column(Float, nullable=False, default=0)
    refund_due_amount = Column(Float, nullable=False, default=0)
    refund_completed_at = Column(DateTime, nullable=True)
    refund_completed_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    refund_method = Column(String(20), nullable=True)
    refund_note = Column(String(500), nullable=True)
    refund_reference = Column(String(128), nullable=True)
    # UNDERPAID | OVERPAID | LATE_PAYMENT | LEGACY_REVIEW | NULL (không vướng).
    reconciliation_reason = Column(String(32), nullable=True, index=True)

    shop = relationship("Shop", back_populates="orders")
    items = relationship("OrderItem", back_populates="order")
    customer = relationship("Customer")
    payments = relationship("OrderPayment", back_populates="order")
    created_by = relationship("User", foreign_keys=[created_by_user_id])
    shift = relationship("CashShift", back_populates="orders")
    returns = relationship("OrderReturn", back_populates="order")


class OrderItem(Base):
    __tablename__ = "order_items"
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"))
    # Tham chiếu sản phẩm gốc. Nullable vì các dòng tạo trước migration A1a
    # chỉ có product_name; backfill khớp được đến đâu thì điền đến đó.
    # Dùng để hoàn tồn kho chính xác khi hủy đơn (A1d) - khớp theo tên là
    # không tin cậy vì sản phẩm có thể bị đổi tên hoặc xóa.
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True, index=True)
    product_name = Column(String)
    price = Column(Float)
    # Ảnh chụp giá vốn tại thời điểm bán, giống cách `product_name` chụp tên.
    # Tra ngược Product.cost_price lúc làm báo cáo thì mỗi lần nhập lô hàng giá
    # khác là lãi của các tháng trước tự đổi số - và không cứu lại được nữa.
    # NULL = bán trước khi có giá vốn; báo cáo loại ra chứ không tính lãi bằng
    # cả giá bán.
    cost_price = Column(Float, nullable=True)
    quantity = Column(Integer)
    order = relationship("Order", back_populates="items")


class OrderReturn(Base):
    """Một lần khách mang hàng trả lại. Một đơn có thể có nhiều lần.

    CỐ Ý tách khỏi cụm `refund_*` trên `orders`: cụm đó là chu kỳ hoàn khoản
    khách CHUYỂN THỪA (một lần duy nhất, `refund_due_amount` là số vô hướng).
    Trả hàng là chuyện khác hẳn và xảy ra nhiều lần, nên phải có bảng riêng.

    Đơn giữ nguyên trạng thái `PAID`: hóa đơn đã xuất là sự thật lịch sử, việc
    khách trả lại là một sự kiện xảy ra SAU đó chứ không xóa đi lần bán.

    `shop_id` lặp lại từ đơn để báo cáo lọc theo shop + ngày trả mà không phải
    join; ngày ở đây là ngày TRẢ, không phải ngày bán.
    """

    __tablename__ = "order_returns"
    __table_args__ = (
        Index("ix_order_returns_order_id", "order_id"),
        Index("ix_order_returns_shop_id_created_at", "shop_id", "created_at"),
        Index(
            "ux_order_returns_idempotency_key", "idempotency_key", unique=True
        ),
    )
    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False)
    # Khóa chống bấm lặp nằm ở ĐÂY chứ không mượn của `order_payments`: phiếu
    # trả có tiền hoàn bằng 0 (đơn giảm giá 100%) không sinh dòng ledger nào,
    # mà vẫn phải chặn được lần bấm thứ hai.
    idempotency_key = Column(String(128), nullable=True)
    # Tiền thực hoàn cho khách, ĐÃ trừ phần giảm giá voucher phân bổ cho các
    # dòng bị trả. Hoàn theo giá niêm yết là shop chịu trọn phần đã giảm.
    refund_amount = Column(Float, nullable=False, default=0)
    refund_method = Column(String(20), nullable=True)   # cash | transfer | None khi 0đ
    reason = Column(String(200), nullable=True)
    note = Column(String(500), nullable=True)
    reference = Column(String(128), nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    shift_id = Column(Integer, ForeignKey("cash_shifts.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    order = relationship("Order", back_populates="returns")
    items = relationship("OrderReturnItem", back_populates="parent_return")


class OrderReturnItem(Base):
    """Một dòng hàng trong phiếu trả.

    `unit_price` và `cost_price` đều là ảnh chụp lấy từ `order_items` lúc trả,
    cùng lý do với ảnh chụp lúc bán: giá bán và giá vốn sau này đổi thì con số
    của lần trả này không được đổi theo.

    `restocked` phải là quyết định của TỪNG DÒNG. Áo khách mặc bẩn, sữa hết hạn
    hay hộp móp thì vẫn hoàn tiền nhưng KHÔNG được cộng lại vào tồn bán được -
    nếu không POS sẽ bán tiếp món đó cho người khác.
    """

    __tablename__ = "order_return_items"
    __table_args__ = (
        Index("ix_order_return_items_return_id", "return_id"),
        Index("ix_order_return_items_order_item_id", "order_item_id"),
    )
    id = Column(Integer, primary_key=True)
    return_id = Column(Integer, ForeignKey("order_returns.id"), nullable=False)
    order_item_id = Column(Integer, ForeignKey("order_items.id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=True)
    product_name = Column(String, nullable=True)
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Float, nullable=False)
    # Tiền hoàn của riêng dòng này sau khi phân bổ giảm giá. Tổng các dòng bằng
    # đúng `refund_amount` của phiếu.
    refund_amount = Column(Float, nullable=False, default=0)
    cost_price = Column(Float, nullable=True)
    restocked = Column(Integer, nullable=False, default=1)

    parent_return = relationship("OrderReturn", back_populates="items")


class OrderItemBatch(Base):
    """Dòng đơn này đã lấy bao nhiêu từ lô nào.

    Không có bảng này thì lúc khách trả hàng hoặc hủy đơn, hệ thống không biết
    nhập lại vào lô nào — đoán bừa là làm hỏng cả hạn sử dụng lẫn giá vốn. Một
    dòng đơn có thể ăn qua NHIỀU lô nên đây là quan hệ nhiều-nhiều thật sự.
    """

    __tablename__ = "order_item_batches"
    __table_args__ = (
        Index("ix_order_item_batches_order_item_id", "order_item_id"),
        Index("ix_order_item_batches_batch_id", "batch_id"),
    )
    id = Column(Integer, primary_key=True)
    order_item_id = Column(Integer, ForeignKey("order_items.id"), nullable=False)
    batch_id = Column(Integer, ForeignKey("product_batches.id"), nullable=False)
    quantity = Column(Integer, nullable=False)
    # Ảnh chụp giá vốn của lô tại thời điểm xuất, cùng lý do với mọi ảnh chụp
    # khác trong dự án.
    cost_price = Column(Float, nullable=True)


class OrderPayment(Base):
    """Sổ bất biến của mọi khoản tiền vào và lần ghi nhận hoàn tiền.

    `bank_txn_id` chỉ để tra cứu và cố ý không unique. `idempotency_key` mới là
    khóa chống ngân hàng gửi lặp; các thao tác thủ công để NULL.
    """

    __tablename__ = "order_payments"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_order_payments_amount_positive"),
        Index("ux_order_payments_idempotency_key", "idempotency_key", unique=True),
        Index("ix_order_payments_order_id", "order_id"),
        Index("ix_order_payments_bank_txn_id", "bank_txn_id"),
    )

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    entry_type = Column(String(24), nullable=False)  # BANK_IN | CASH_TOPUP | REFUND_*
    amount = Column(Float, nullable=False)
    idempotency_key = Column(String(128), nullable=True)
    provider = Column(String(32), nullable=True)
    bank_txn_id = Column(String(128), nullable=True)
    account_no = Column(String(64), nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    # Ca thực sự nhận/chi khoản tiền này. Có thể khác ca tạo đơn (ví dụ thu bù
    # hoặc hoàn tiền vào ngày sau), và nullable cho dữ liệu legacy/ngân hàng.
    shift_id = Column(Integer, ForeignKey("cash_shifts.id"), nullable=True, index=True)
    note = Column(String(500), nullable=True)
    reference = Column(String(128), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    order = relationship("Order", back_populates="payments")
    shift = relationship("CashShift", back_populates="order_payments")
