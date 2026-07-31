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
