"""Shim tương thích: models đã chuyển sang fselling/models/.

Giữ file này để các script/import cũ (`import models`) vẫn chạy.
"""
from fselling.models import (  # noqa: F401
    Base,
    Category,
    Order,
    OrderItem,
    Product,
    Shop,
    SystemLog,
    User,
    Voucher,
)

__all__ = [
    "Base",
    "User",
    "Shop",
    "Category",
    "Product",
    "Voucher",
    "Order",
    "OrderItem",
    "SystemLog",
]
