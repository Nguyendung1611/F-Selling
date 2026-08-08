"""ORM models. Import tất cả ở đây để SQLAlchemy registry luôn đầy đủ
(quan hệ khai báo bằng chuỗi tên class cần các class đã được nạp)."""
from ..core.database import Base
from .catalog import (
    Category,
    Product,
    ProductBatch,
    StockWriteOff,
    StockWriteOffItem,
    Voucher,
)
from .customer import Customer
from .expense import ExpenseCategory, ExpenseTemplate, OperatingExpense
from .loyalty import LoyaltyPointEntry, LoyaltyProgram
from .order import (
    Order,
    OrderItem,
    OrderItemBatch,
    OrderPayment,
    OrderReturn,
    OrderReturnItem,
)
from .shift import CashMovement, CashShift
from .shop import Shop
from .supplier import (
    PurchaseReceipt,
    PurchaseReceiptItem,
    Supplier,
    SupplierPayableEntry,
    SupplierPayment,
    SupplierPaymentAllocation,
)
from .system_log import SystemLog
from .subscription import (
    ShopSubscription,
    SubscriptionCheckout,
    SubscriptionGrant,
    SubscriptionPayment,
)
from .user import User

__all__ = [
    "Base",
    "User",
    "Shop",
    "Category",
    "Product",
    "ProductBatch",
    "StockWriteOff",
    "StockWriteOffItem",
    "Voucher",
    "Order",
    "OrderItem",
    "OrderItemBatch",
    "OrderPayment",
    "OrderReturn",
    "OrderReturnItem",
    "CashShift",
    "CashMovement",
    "SystemLog",
    "Customer",
    "ExpenseCategory",
    "ExpenseTemplate",
    "OperatingExpense",
    "LoyaltyProgram",
    "LoyaltyPointEntry",
    "Supplier",
    "PurchaseReceipt",
    "PurchaseReceiptItem",
    "SupplierPayableEntry",
    "SupplierPayment",
    "SupplierPaymentAllocation",
    "ShopSubscription",
    "SubscriptionGrant",
    "SubscriptionCheckout",
    "SubscriptionPayment",
]
