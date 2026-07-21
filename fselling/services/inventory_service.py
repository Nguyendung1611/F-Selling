"""Kiểm tra và trừ tồn kho. Giá LUÔN lấy từ database, không tin client."""
from __future__ import annotations

from typing import Dict, Iterable, List, Tuple

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import models
from ..schemas.order import OrderItemCreate


def collect_quantities(items: Iterable[OrderItemCreate]) -> Dict[str, int]:
    """Gom số lượng theo tên sản phẩm; từ chối số lượng <= 0."""
    wanted: Dict[str, int] = {}
    for item in items:
        if item.quantity is None or item.quantity <= 0:
            raise HTTPException(status_code=400, detail="Số lượng sản phẩm không hợp lệ")
        wanted[item.product_name] = wanted.get(item.product_name, 0) + item.quantity
    return wanted


def resolve_items(
    db: Session, shop_id: int, wanted: Dict[str, int]
) -> Tuple[List[Tuple[models.Product, int]], float]:
    """Tra sản phẩm trong DB, kiểm tra tồn kho, tính subtotal theo giá DB."""
    resolved: List[Tuple[models.Product, int]] = []
    subtotal = 0.0
    for product_name, qty in wanted.items():
        prod = (
            db.query(models.Product)
            .filter(
                models.Product.name == product_name,
                models.Product.shop_id == shop_id,
                models.Product.is_active == True,  # noqa: E712 - SQLAlchemy cần so sánh ==
            )
            .first()
        )
        if not prod:
            raise HTTPException(
                status_code=404, detail=f"Sản phẩm '{product_name}' không tồn tại hoặc đã ẩn"
            )
        if prod.stock < qty:
            raise HTTPException(
                status_code=400, detail=f"Sản phẩm '{product_name}' không đủ tồn kho"
            )
        subtotal += prod.price * qty
        resolved.append((prod, qty))
    return resolved, subtotal


def deduct_stock(resolved_items: Iterable[Tuple[models.Product, int]]) -> None:
    """Trừ tồn kho (tồn kho đã được kiểm tra ở resolve_items).
    Không commit ở đây - caller giữ nguyên một transaction duy nhất."""
    for prod, qty in resolved_items:
        prod.stock -= qty
