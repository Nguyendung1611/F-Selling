"""Pydantic schemas (tách khỏi ORM models)."""
from .auth import (
    ChangePasswordRequest,
    EmailVerify,
    ForgotPasswordRequest,
    ForgotPasswordReset,
    Login,
    ResendCodeRequest,
    Token,
    UserCreate,
)
from .catalog import CategoryUpdate, ProductCreate, VoucherCreate
from .expense import (
    ExpenseCategoryCreate,
    ExpenseCategoryUpdate,
    ExpenseCreate,
    ExpenseTemplateCreate,
    ExpenseTemplateUpdate,
)
from .order import CashTopup, OrderCreate, OrderItemCreate, PaymentWebhook, RefundComplete
from .shop import ShopCreate
from .supplier import (
    PurchaseReceiptConfirm,
    PurchaseReceiptCreate,
    PurchaseReceiptItemInput,
    PurchaseReceiptUpdate,
    SupplierCreate,
    SupplierPaymentCreate,
    SupplierStatusUpdate,
    SupplierUpdate,
)

__all__ = [
    "UserCreate",
    "EmailVerify",
    "ResendCodeRequest",
    "ForgotPasswordRequest",
    "ForgotPasswordReset",
    "ChangePasswordRequest",
    "Login",
    "Token",
    "ShopCreate",
    "ProductCreate",
    "CategoryUpdate",
    "VoucherCreate",
    "OrderItemCreate",
    "OrderCreate",
    "PaymentWebhook",
    "CashTopup",
    "RefundComplete",
    "SupplierCreate",
    "SupplierUpdate",
    "SupplierStatusUpdate",
    "SupplierPaymentCreate",
    "PurchaseReceiptItemInput",
    "PurchaseReceiptCreate",
    "PurchaseReceiptUpdate",
    "PurchaseReceiptConfirm",
    "ExpenseCategoryCreate",
    "ExpenseCategoryUpdate",
    "ExpenseTemplateCreate",
    "ExpenseTemplateUpdate",
    "ExpenseCreate",
]
