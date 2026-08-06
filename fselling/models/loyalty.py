"""ORM cho chương trình khách thân thiết và sổ điểm bất biến.

Số dư KHÔNG được lưu thành một cột có thể ghi đè. Nó luôn được dựng lại từ
``LoyaltyPointEntry`` để mọi lần cộng, dùng, hoàn và trừ lại đều còn dấu vết.
"""
import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
)

from ..core.database import Base


class LoyaltyProgram(Base):
    """Cấu hình tích điểm hiện tại của một cửa hàng (tối đa một dòng/shop)."""

    __tablename__ = "loyalty_programs"
    __table_args__ = (
        Index("ux_loyalty_programs_shop_id", "shop_id", unique=True),
    )

    id = Column(Integer, primary_key=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False)
    # Mặc định TẮT: tạo bảng/migration không được tự áp một tỷ lệ tiền thay chủ
    # shop cho dữ liệu đang chạy.
    enabled = Column(Boolean, nullable=False, default=False)

    # Chi ``earn_amount`` đồng nhận ``earn_points`` điểm.
    earn_amount = Column(Float, nullable=True)
    earn_points = Column(Integer, nullable=True)
    # Dùng ``redeem_points`` điểm giảm ``redeem_amount`` đồng.
    redeem_points = Column(Integer, nullable=True)
    redeem_amount = Column(Float, nullable=True)

    min_redeem_points = Column(Integer, nullable=False, default=0)
    max_redeem_percent = Column(Float, nullable=False, default=100.0)
    # NULL = không hết hạn; số nguyên dương = hạn của từng đợt điểm.
    expiry_days = Column(Integer, nullable=True)

    updated_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
    )


class LoyaltyPointEntry(Base):
    """Một bút toán điểm bất biến.

    ``points_delta`` dương tạo một lô điểm, âm tiêu điểm theo FEFO. Khóa
    ``idempotency_key`` không được NULL vì mọi đường tài chính phải chống gửi
    lặp ngay tại database, không chỉ dựa vào kiểm tra trước ở service.
    """

    __tablename__ = "loyalty_point_entries"
    __table_args__ = (
        CheckConstraint("points_delta <> 0", name="ck_loyalty_points_delta_nonzero"),
        Index(
            "ix_loyalty_point_entries_customer_created",
            "customer_id",
            "created_at",
        ),
        Index(
            "ix_loyalty_point_entries_shop_created",
            "shop_id",
            "created_at",
        ),
        Index(
            "ux_loyalty_point_entries_idempotency_key",
            "idempotency_key",
            unique=True,
        ),
    )

    id = Column(Integer, primary_key=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=True)
    return_id = Column(Integer, ForeignKey("order_returns.id"), nullable=True)
    entry_type = Column(String(32), nullable=False)
    points_delta = Column(Integer, nullable=False)
    expires_at = Column(DateTime, nullable=True)
    idempotency_key = Column(String(128), nullable=False)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    # Ảnh chụp lúc ghi sổ: đổi tên/SĐT hoặc ngừng dùng hồ sơ khách sau này không
    # được làm lịch sử cũ mất khả năng đọc và đối chiếu.
    customer_name = Column(String(255), nullable=True)
    customer_phone = Column(String(64), nullable=True)
    note = Column(String(500), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)


__all__ = ["LoyaltyProgram", "LoyaltyPointEntry"]
