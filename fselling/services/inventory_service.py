"""Kiểm tra và trừ tồn kho. Giá LUÔN lấy từ database, không tin client."""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import models
from ..core.i18n import tr
from ..schemas.order import OrderItemCreate

# Cách định danh một dòng hàng: ("id", 7) hoặc ("name", "Sữa tươi").
# Gom theo khóa này thay vì theo tên trần để hai sản phẩm trùng tên không bị
# cộng dồn vào cùng một dòng.
KhoaSanPham = Tuple[str, Any]


def _khoa_cua(item: OrderItemCreate) -> KhoaSanPham:
    if item.product_id is not None:
        return ("id", item.product_id)
    ten = (item.product_name or "").strip()
    if not ten:
        raise HTTPException(
            status_code=400,
            detail=tr("Dòng hàng phải có product_id hoặc product_name"),
        )
    return ("name", ten)


def collect_quantities(items: Iterable[OrderItemCreate]) -> Dict[KhoaSanPham, int]:
    """Gom số lượng theo từng sản phẩm; từ chối số lượng <= 0."""
    wanted: Dict[KhoaSanPham, int] = {}
    for item in items:
        if item.quantity is None or item.quantity <= 0:
            raise HTTPException(
                status_code=400,
                detail=tr("Số lượng sản phẩm không hợp lệ"),
            )
        khoa = _khoa_cua(item)
        wanted[khoa] = wanted.get(khoa, 0) + item.quantity
    return wanted


def resolve_items(
    db: Session, shop_id: int, wanted: Dict[KhoaSanPham, int]
) -> Tuple[List[Tuple[models.Product, int]], float]:
    """Tra sản phẩm trong DB, kiểm tra tồn kho, tính subtotal theo giá DB.

    Mọi truy vấn đều bị chặn trong `shop_id` của đơn, kể cả khi client gửi
    `product_id`: thiếu điều kiện đó thì đoán id là đặt được hàng của shop khác.
    """
    resolved: List[Tuple[models.Product, int]] = []
    subtotal = 0.0
    for (loai, gia_tri), qty in wanted.items():
        query = db.query(models.Product).filter(
            models.Product.shop_id == shop_id,
            models.Product.is_active == True,  # noqa: E712 - SQLAlchemy cần so sánh ==
        )
        if loai == "id":
            query = query.filter(models.Product.id == gia_tri)
            nhan = f"id={gia_tri}"
        else:
            query = query.filter(models.Product.name == gia_tri)
            nhan = f"'{gia_tri}'"

        prod = query.first()
        if not prod:
            raise HTTPException(
                status_code=404,
                detail=tr(
                    "Sản phẩm {label} không tồn tại hoặc đã ẩn",
                    label=nhan,
                ),
            )
        if prod.stock < qty:
            raise HTTPException(
                status_code=400,
                detail=tr(
                    "Sản phẩm '{name}' không đủ tồn kho",
                    name=prod.name,
                ),
            )
        subtotal += prod.price * qty
        resolved.append((prod, qty))
    return resolved, subtotal


def deduct_stock(resolved_items: Iterable[Tuple[models.Product, int]]) -> None:
    """Trừ tồn kho (tồn kho đã được kiểm tra ở resolve_items).
    Không commit ở đây - caller giữ nguyên một transaction duy nhất."""
    for prod, qty in resolved_items:
        prod.stock -= qty


def restore_stock(db: Session, order_id: int) -> Tuple[int, int]:
    """Hoàn tồn kho cho toàn bộ dòng của một đơn đã hủy.

    Hoàn theo `product_id` chứ không theo tên: sản phẩm có thể đã được đổi tên
    sau khi bán, khớp theo tên sẽ hoàn nhầm hoặc không hoàn được.

    Dòng không có `product_id` (đơn cũ trước migration A1a mà backfill không
    khớp được) hoặc trỏ tới sản phẩm đã bị xóa sẽ được bỏ qua và đếm riêng để
    caller ghi log - không im lặng nuốt mất.

    Không commit - caller giữ nguyên một transaction duy nhất.
    Trả về (số dòng đã hoàn, số dòng không hoàn được).
    """
    items = (
        db.query(models.OrderItem).filter(models.OrderItem.order_id == order_id).all()
    )
    restored = 0
    unrestored = 0
    for item in items:
        if item.product_id is None:
            unrestored += 1
            continue
        prod = (
            db.query(models.Product).filter(models.Product.id == item.product_id).first()
        )
        if prod is None:
            unrestored += 1
            continue
        prod.stock = (prod.stock or 0) + item.quantity
        restored += 1
    return restored, unrestored
