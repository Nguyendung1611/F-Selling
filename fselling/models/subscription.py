"""Gói Free/Pro theo từng cửa hàng và sổ tiền thuê bao riêng.

Tiền mua gói tuyệt đối không đi vào ``Order``/``OrderPayment`` của cửa hàng.
``SubscriptionPayment`` là ledger tiền nền tảng nhận; ``SubscriptionCheckout``
chụp giá + số ngày tại lúc tạo để đổi bảng giá sau này không sửa lịch sử cũ.
"""
import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)

from ..core.database import Base


class ShopSubscription(Base):
    """Trạng thái trial/paid cô đọng để kiểm quyền nhanh trên mọi request."""

    __tablename__ = "shop_subscriptions"
    __table_args__ = (
        Index("ux_shop_subscriptions_shop_id", "shop_id", unique=True),
    )

    shop_id = Column(Integer, ForeignKey("shops.id"), primary_key=True)
    trial_started_at = Column(DateTime, nullable=False)
    trial_ends_at = Column(DateTime, nullable=False)
    # Cache mốc cuối của các segment đã trả tiền. Quyền thật được suy từ từng
    # checkout đã kích hoạt; cột này giữ tương thích DB legacy và tra nhanh.
    paid_until = Column(DateTime, nullable=True)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
    )


class SubscriptionGrant(Base):
    """Một lần ADMIN tặng Pro có hạn; thu hồi chỉ được áp lên chính quà tặng."""

    __tablename__ = "subscription_grants"
    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="ck_subscription_grants_time"),
        Index("ix_subscription_grants_shop_ends", "shop_id", "ends_at"),
        Index(
            "ux_subscription_grants_operation_id",
            "operation_id",
            unique=True,
        ),
        Index(
            "ux_subscription_grants_revoke_operation_id",
            "revoke_operation_id",
            unique=True,
        ),
    )

    id = Column(Integer, primary_key=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False)
    starts_at = Column(DateTime, nullable=False)
    # Mốc độc quyền UTC: UI "dùng đến hết ngày D" được đổi thành 00:00 ngày
    # D+1 theo Asia/Ho_Chi_Minh rồi mới lưu UTC-naive.
    ends_at = Column(DateTime, nullable=False)
    expires_on = Column(String(10), nullable=False)
    reason = Column(String(500), nullable=False)
    operation_id = Column(String(128), nullable=False)
    operation_fingerprint = Column(String(64), nullable=False)
    granted_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)

    revoked_at = Column(DateTime, nullable=True)
    revoked_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    revoke_reason = Column(String(500), nullable=True)
    revoke_operation_id = Column(String(128), nullable=True)
    revoke_fingerprint = Column(String(64), nullable=True)


class SubscriptionCheckout(Base):
    """Yêu cầu thanh toán Pro, sống 24 giờ và chụp giá/kỳ hạn tại lúc tạo."""

    __tablename__ = "subscription_checkouts"
    __table_args__ = (
        CheckConstraint(
            "cycle IN ('MONTHLY', 'YEARLY')",
            name="ck_subscription_checkouts_cycle",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'UNDERPAID', 'PAID', 'OVERPAID', 'EXPIRED')",
            name="ck_subscription_checkouts_status",
        ),
        CheckConstraint(
            "amount_due_vnd > 0",
            name="ck_subscription_checkouts_amount_positive",
        ),
        CheckConstraint(
            "duration_days > 0",
            name="ck_subscription_checkouts_duration_positive",
        ),
        CheckConstraint(
            "received_amount_vnd >= 0",
            name="ck_subscription_checkouts_received_nonnegative",
        ),
        CheckConstraint(
            "refund_due_amount_vnd >= 0",
            name="ck_subscription_checkouts_refund_nonnegative",
        ),
        CheckConstraint(
            "(entitlement_starts_at IS NULL AND entitlement_ends_at IS NULL) "
            "OR (entitlement_starts_at IS NOT NULL "
            "AND entitlement_ends_at IS NOT NULL "
            "AND entitlement_ends_at > entitlement_starts_at)",
            name="ck_subscription_checkouts_entitlement_time",
        ),
        Index("ix_subscription_checkouts_shop_created", "shop_id", "created_at"),
        Index(
            "ix_subscription_checkouts_shop_entitlement",
            "shop_id",
            "entitlement_starts_at",
            "entitlement_ends_at",
        ),
        Index(
            "ux_subscription_checkouts_reference_code",
            "reference_code",
            unique=True,
        ),
        Index(
            "ux_subscription_checkouts_operation_id",
            "operation_id",
            unique=True,
        ),
        # Một shop chỉ có đúng một QR còn mở. Điều kiện nằm ở DB để hai tab hay
        # hai worker không thể cùng tạo hai mã rồi khiến khách trả hai lần.
        Index(
            "ux_subscription_checkouts_one_open_per_shop",
            "shop_id",
            unique=True,
            sqlite_where=text("status IN ('PENDING', 'UNDERPAID')"),
        ),
    )

    id = Column(Integer, primary_key=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False)
    reference_code = Column(String(32), nullable=False)
    cycle = Column(String(16), nullable=False)
    amount_due_vnd = Column(Integer, nullable=False)
    duration_days = Column(Integer, nullable=False)
    status = Column(String(16), nullable=False, default="PENDING")
    received_amount_vnd = Column(Integer, nullable=False, default=0)
    refund_due_amount_vnd = Column(Integer, nullable=False, default=0)

    operation_id = Column(String(128), nullable=False)
    operation_fingerprint = Column(String(64), nullable=False)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    activated_at = Column(DateTime, nullable=True)
    # Mỗi checkout đã trả đủ sở hữu đúng một segment 30/365 ngày. Hai cột này
    # cho phép kéo segment chưa bắt đầu khi quà bị thu hồi mà không cắt ngày mua.
    entitlement_starts_at = Column(DateTime, nullable=True)
    entitlement_ends_at = Column(DateTime, nullable=True)
    paid_until_after = Column(DateTime, nullable=True)


class SubscriptionPayment(Base):
    """Ledger bất biến của tiền vào tài khoản nền tảng.

    ``checkout_id``/``shop_id`` được phép NULL để tiền chuyển sai hoặc thiếu mã
    vẫn nổi lên màn Admin, thay vì biến mất chỉ vì chưa tự đối chiếu được.
    """

    __tablename__ = "subscription_payments"
    __table_args__ = (
        CheckConstraint(
            "amount_vnd > 0", name="ck_subscription_payments_amount_positive"
        ),
        Index("ix_subscription_payments_checkout_id", "checkout_id"),
        Index("ix_subscription_payments_shop_created", "shop_id", "created_at"),
        Index("ix_subscription_payments_needs_review", "needs_review"),
        # Mã thô của ngân hàng CỐ Ý non-unique; khóa chuẩn hóa dưới đây mới là
        # hàng rào retry, giống sổ thanh toán đơn hàng hiện có.
        Index("ix_subscription_payments_bank_txn_id", "bank_txn_id"),
        Index(
            "ux_subscription_payments_idempotency_key",
            "idempotency_key",
            unique=True,
        ),
    )

    id = Column(Integer, primary_key=True)
    checkout_id = Column(
        Integer, ForeignKey("subscription_checkouts.id"), nullable=True
    )
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=True)
    reference_code = Column(String(64), nullable=True)
    amount_vnd = Column(Integer, nullable=False)
    idempotency_key = Column(String(128), nullable=False)
    provider = Column(String(32), nullable=True)
    bank_txn_id = Column(String(128), nullable=True)
    account_no = Column(String(128), nullable=True)
    payload_fingerprint = Column(String(64), nullable=True)
    needs_review = Column(Boolean, nullable=False, default=False)
    review_reason = Column(String(64), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)


__all__ = [
    "ShopSubscription",
    "SubscriptionGrant",
    "SubscriptionCheckout",
    "SubscriptionPayment",
]
