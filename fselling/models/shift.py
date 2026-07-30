"""Ca thu ngân và sổ điều chỉnh tiền mặt.

Ca là dữ liệu server-side, không đại diện cho một thiết bị hay một két vật lý.
Mỗi người vận hành có tối đa một ca OPEN trong một shop. Tiền bán/hoàn của đơn
nằm ở ``order_payments``; bảng ``cash_movements`` chỉ ghi các khoản thu/chi
thủ công để tránh đếm hai lần.
"""
import datetime

from sqlalchemy import CheckConstraint, Column, DateTime, Float, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import relationship

from ..core.database import Base


class CashShift(Base):
    __tablename__ = "cash_shifts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('OPEN', 'CLOSED')",
            name="ck_cash_shifts_status",
        ),
        CheckConstraint(
            "opening_cash_amount >= 0",
            name="ck_cash_shifts_opening_cash_nonnegative",
        ),
        Index("ix_cash_shifts_shop_id", "shop_id"),
        Index("ix_cash_shifts_opened_by_user_id", "opened_by_user_id"),
        # Nhiều thu ngân được mở ca đồng thời trong cùng shop, nhưng một người
        # không thể có hai ca OPEN. Partial index giữ được lịch sử ca đã đóng.
        Index(
            "ux_cash_shifts_shop_user_open",
            "shop_id",
            "opened_by_user_id",
            unique=True,
            sqlite_where=text("status = 'OPEN'"),
        ),
    )

    id = Column(Integer, primary_key=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False)
    status = Column(String(16), nullable=False, default="OPEN")
    opening_cash_amount = Column(Float, nullable=False, default=0)
    opening_note = Column(String(500), nullable=True)
    opened_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    opened_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)

    counted_cash_amount = Column(Float, nullable=True)
    expected_cash_amount = Column(Float, nullable=True)
    variance_amount = Column(Float, nullable=True)
    closing_note = Column(String(500), nullable=True)
    closed_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    closed_at = Column(DateTime, nullable=True)

    shop = relationship("Shop", back_populates="cash_shifts")
    opened_by = relationship("User", foreign_keys=[opened_by_user_id])
    closed_by = relationship("User", foreign_keys=[closed_by_user_id])
    movements = relationship("CashMovement", back_populates="shift")
    orders = relationship("Order", back_populates="shift")
    order_payments = relationship("OrderPayment", back_populates="shift")


class CashMovement(Base):
    """Một khoản thu/chi tiền mặt thủ công, append-only trong một ca."""

    __tablename__ = "cash_movements"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_cash_movements_amount_positive"),
        CheckConstraint(
            "direction IN ('IN', 'OUT')",
            name="ck_cash_movements_direction",
        ),
        Index("ix_cash_movements_shift_id", "shift_id"),
        Index("ix_cash_movements_order_id", "order_id"),
        Index(
            "ux_cash_movements_operation_id",
            "operation_id",
            unique=True,
        ),
    )

    id = Column(Integer, primary_key=True)
    shift_id = Column(Integer, ForeignKey("cash_shifts.id"), nullable=False)
    # Chừa liên kết tùy chọn để các nghiệp vụ bù/hoàn sau này truy vết về đơn.
    # Tiền bán hàng vẫn được tính từ OrderPayment, không ghi lặp vào bảng này.
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=True)
    movement_type = Column(String(24), nullable=False)  # PAY_IN | PAY_OUT
    direction = Column(String(8), nullable=False)  # IN | OUT
    amount = Column(Float, nullable=False)
    operation_id = Column(String(128), nullable=False)
    note = Column(String(500), nullable=False)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)

    shift = relationship("CashShift", back_populates="movements")
    order = relationship("Order")
    created_by = relationship("User")
