"""Nhà cung cấp, phiếu nhập và sổ công nợ phải trả bất biến.

Số dư công nợ không nằm trên ``Supplier``. Nó luôn được dựng từ các khoản
phải trả trừ các phân bổ thanh toán, để một đường ghi sót không thể làm hai
nguồn số liệu lệch nhau trong im lặng.
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
)
from sqlalchemy.orm import relationship

from ..core.database import Base


class Supplier(Base):
    __tablename__ = "suppliers"
    __table_args__ = (
        Index("ix_suppliers_shop_name", "shop_id", "name"),
        Index(
            "ux_suppliers_create_operation_id",
            "create_operation_id",
            unique=True,
        ),
    )

    id = Column(Integer, primary_key=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False)
    name = Column(String(255), nullable=False)
    phone = Column(String(64), nullable=True)
    tax_code = Column(String(64), nullable=True)
    address = Column(String(500), nullable=True)
    note = Column(String(500), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)

    # Tạo NCC có thể đồng thời ghi số dư đầu kỳ, nên retry phải được chặn ở DB.
    create_operation_id = Column(String(128), nullable=False)
    create_fingerprint = Column(String(64), nullable=False)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(
        DateTime, nullable=False, default=datetime.datetime.utcnow
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
    )

    receipts = relationship("PurchaseReceipt", back_populates="supplier")
    payable_entries = relationship("SupplierPayableEntry", back_populates="supplier")
    payments = relationship("SupplierPayment", back_populates="supplier")


class PurchaseReceipt(Base):
    """Phiếu nhập: DRAFT chưa đụng kho/nợ; POSTED là chứng từ bất biến."""

    __tablename__ = "purchase_receipts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('DRAFT', 'POSTED')",
            name="ck_purchase_receipts_status",
        ),
        CheckConstraint(
            "total_amount >= 0",
            name="ck_purchase_receipts_total_nonnegative",
        ),
        Index("ix_purchase_receipts_shop_created", "shop_id", "created_at"),
        Index(
            "ix_purchase_receipts_supplier_created", "supplier_id", "created_at"
        ),
        Index(
            "ux_purchase_receipts_create_operation_id",
            "create_operation_id",
            unique=True,
        ),
        Index(
            "ux_purchase_receipts_confirm_operation_id",
            "confirm_operation_id",
            unique=True,
        ),
    )

    id = Column(Integer, primary_key=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=False)
    status = Column(String(16), nullable=False, default="DRAFT")
    supplier_invoice_number = Column(String(128), nullable=True)
    # Ngày chứng từ/ngày đến hạn là ngày lịch, lưu YYYY-MM-DD như hạn lô.
    received_date = Column(String(10), nullable=False)
    due_date = Column(String(10), nullable=True)
    note = Column(String(500), nullable=True)
    # Tiền VND mới lưu số nguyên. DRAFT cũng được server tính để người dùng xem.
    total_amount = Column(Integer, nullable=False, default=0)

    create_operation_id = Column(String(128), nullable=False)
    create_fingerprint = Column(String(64), nullable=False)
    confirm_operation_id = Column(String(128), nullable=True)
    confirm_fingerprint = Column(String(64), nullable=True)

    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    updated_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    confirmed_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(
        DateTime, nullable=False, default=datetime.datetime.utcnow
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.datetime.utcnow,
        onupdate=datetime.datetime.utcnow,
    )
    confirmed_at = Column(DateTime, nullable=True)

    supplier = relationship("Supplier", back_populates="receipts")
    items = relationship("PurchaseReceiptItem", back_populates="receipt")
    payable_entry = relationship(
        "SupplierPayableEntry", back_populates="receipt", uselist=False
    )


class PurchaseReceiptItem(Base):
    __tablename__ = "purchase_receipt_items"
    __table_args__ = (
        CheckConstraint(
            "quantity > 0", name="ck_purchase_receipt_items_quantity_positive"
        ),
        CheckConstraint(
            "unit_cost >= 0", name="ck_purchase_receipt_items_cost_nonnegative"
        ),
        Index("ix_purchase_receipt_items_receipt_id", "receipt_id"),
        Index("ix_purchase_receipt_items_product_id", "product_id"),
    )

    id = Column(Integer, primary_key=True)
    receipt_id = Column(
        Integer, ForeignKey("purchase_receipts.id"), nullable=False
    )
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    # Ảnh chụp để sản phẩm đổi tên/xóa sau này không làm phiếu cũ mất nghĩa.
    product_name = Column(String(300), nullable=False)
    quantity = Column(Integer, nullable=False)
    unit_cost = Column(Integer, nullable=False)
    expiry_date = Column(String(10), nullable=True)
    # Chỉ có sau confirm với sản phẩm theo lô.
    batch_id = Column(Integer, ForeignKey("product_batches.id"), nullable=True)

    receipt = relationship("PurchaseReceipt", back_populates="items")


class SupplierPayableEntry(Base):
    """Một khoản phải trả dương: nợ đầu kỳ hoặc một phiếu nhập đã xác nhận."""

    __tablename__ = "supplier_payable_entries"
    __table_args__ = (
        CheckConstraint(
            "entry_type IN ('PURCHASE', 'OPENING')",
            name="ck_supplier_payable_entries_type",
        ),
        CheckConstraint(
            "amount > 0", name="ck_supplier_payable_entries_amount_positive"
        ),
        Index("ix_supplier_payable_entries_supplier_created", "supplier_id", "created_at"),
        # Một phiếu POSTED sinh đúng một khoản phải trả. SQLite cho phép nhiều
        # NULL nên các dòng OPENING không chặn nhau.
        Index(
            "ux_supplier_payable_entries_receipt_id",
            "receipt_id",
            unique=True,
        ),
        Index(
            "ux_supplier_payable_entries_idempotency_key",
            "idempotency_key",
            unique=True,
        ),
    )

    id = Column(Integer, primary_key=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=False)
    receipt_id = Column(Integer, ForeignKey("purchase_receipts.id"), nullable=True)
    entry_type = Column(String(20), nullable=False)
    amount = Column(Integer, nullable=False)
    entry_date = Column(String(10), nullable=False)
    due_date = Column(String(10), nullable=True)
    idempotency_key = Column(String(128), nullable=False)
    note = Column(String(500), nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(
        DateTime, nullable=False, default=datetime.datetime.utcnow
    )

    supplier = relationship("Supplier", back_populates="payable_entries")
    receipt = relationship("PurchaseReceipt", back_populates="payable_entry")
    allocations = relationship(
        "SupplierPaymentAllocation", back_populates="payable_entry"
    )


class SupplierPayment(Base):
    """Một lần trả nhà cung cấp; tiền được phân bổ vào các khoản phải trả."""

    __tablename__ = "supplier_payments"
    __table_args__ = (
        CheckConstraint(
            "method IN ('CASH_SHIFT', 'TRANSFER', 'OUTSIDE')",
            name="ck_supplier_payments_method",
        ),
        CheckConstraint(
            "amount > 0", name="ck_supplier_payments_amount_positive"
        ),
        Index("ix_supplier_payments_supplier_created", "supplier_id", "created_at"),
        Index("ix_supplier_payments_shift_id", "shift_id"),
        Index(
            "ux_supplier_payments_idempotency_key",
            "idempotency_key",
            unique=True,
        ),
    )

    id = Column(Integer, primary_key=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=False)
    amount = Column(Integer, nullable=False)
    method = Column(String(20), nullable=False)
    idempotency_key = Column(String(128), nullable=False)
    operation_fingerprint = Column(String(64), nullable=False)
    shift_id = Column(Integer, ForeignKey("cash_shifts.id"), nullable=True)
    cash_movement_id = Column(Integer, ForeignKey("cash_movements.id"), nullable=True)
    note = Column(String(500), nullable=True)
    reference = Column(String(128), nullable=True)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(
        DateTime, nullable=False, default=datetime.datetime.utcnow
    )

    supplier = relationship("Supplier", back_populates="payments")
    allocations = relationship("SupplierPaymentAllocation", back_populates="payment")


class SupplierPaymentAllocation(Base):
    __tablename__ = "supplier_payment_allocations"
    __table_args__ = (
        CheckConstraint(
            "amount > 0", name="ck_supplier_payment_allocations_amount_positive"
        ),
        Index("ix_supplier_payment_allocations_payment_id", "payment_id"),
        Index("ix_supplier_payment_allocations_payable_id", "payable_entry_id"),
        Index(
            "ux_supplier_payment_allocations_pair",
            "payment_id",
            "payable_entry_id",
            unique=True,
        ),
    )

    id = Column(Integer, primary_key=True)
    payment_id = Column(Integer, ForeignKey("supplier_payments.id"), nullable=False)
    payable_entry_id = Column(
        Integer, ForeignKey("supplier_payable_entries.id"), nullable=False
    )
    amount = Column(Integer, nullable=False)

    payment = relationship("SupplierPayment", back_populates="allocations")
    payable_entry = relationship(
        "SupplierPayableEntry", back_populates="allocations"
    )


__all__ = [
    "Supplier",
    "PurchaseReceipt",
    "PurchaseReceiptItem",
    "SupplierPayableEntry",
    "SupplierPayment",
    "SupplierPaymentAllocation",
]
