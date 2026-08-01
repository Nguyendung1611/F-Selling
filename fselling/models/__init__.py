"""ORM models. Import tất cả ở đây để SQLAlchemy registry luôn đầy đủ
(quan hệ khai báo bằng chuỗi tên class cần các class đã được nạp)."""
from ..core.database import Base
from .catalog import Category, Product, Voucher
from .customer import Customer
from .order import Order, OrderItem, OrderPayment, OrderReturn, OrderReturnItem
from .shift import CashMovement, CashShift
from .shop import Shop
from .system_log import SystemLog
from .user import User

__all__ = [
    "Base",
    "User",
    "Shop",
    "Category",
    "Product",
    "Voucher",
    "Order",
    "OrderItem",
    "OrderPayment",
    "OrderReturn",
    "OrderReturnItem",
    "CashShift",
    "CashMovement",
    "SystemLog",
    "Customer",
]
