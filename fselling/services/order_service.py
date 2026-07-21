"""Nghiệp vụ đơn hàng: tạo đơn (giá từ DB), tra cứu, xác nhận thanh toán, webhook."""
from __future__ import annotations

from typing import Any, Dict, List

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import models
from ..dependencies import require_shop_access
from ..schemas.order import OrderCreate
from . import inventory_service, payment_service, voucher_service
from .log_service import log_system_action


def create_order(
    db: Session, current_user: models.User, shop_id: int, order: OrderCreate
) -> Dict[str, Any]:
    # Yêu cầu đăng nhập và chỉ chủ shop (hoặc admin) mới được tạo đơn cho shop này.
    shop = require_shop_access(db, shop_id, current_user)

    if not order.items:
        raise HTTPException(status_code=400, detail="Đơn hàng không có sản phẩm nào")

    # Tính tiền TỪ DB, không tin giá client gửi.
    wanted = inventory_service.collect_quantities(order.items)
    resolved_items, subtotal = inventory_service.resolve_items(db, shop_id, wanted)

    applied_voucher, discount_amount = voucher_service.resolve_for_order(
        db, shop_id, order.voucher_code, subtotal
    )

    total = subtotal - discount_amount
    if total < 0:
        total = 0

    new_order = models.Order(
        shop_id=shop_id,
        total_amount=total,
        discount_amount=discount_amount,
        voucher_code=order.voucher_code,
        payment_method=order.payment_method,
    )
    db.add(new_order)
    db.flush()  # lấy new_order.id mà chưa commit, cùng một transaction

    for prod, qty in resolved_items:
        db.add(
            models.OrderItem(
                order_id=new_order.id,
                # Ghi kèm product_id để hoàn tồn kho chính xác khi hủy đơn (A1d).
                # product_name vẫn được giữ: nó là ảnh chụp tên tại thời điểm bán,
                # dùng cho hóa đơn và báo cáo kể cả khi sản phẩm sau này bị đổi tên/xóa.
                product_id=prod.id,
                product_name=prod.name,
                price=prod.price,
                quantity=qty,
            )
        )
    inventory_service.deduct_stock(resolved_items)

    if applied_voucher is not None:
        applied_voucher.usage_count = (applied_voucher.usage_count or 0) + 1

    db.commit()
    db.refresh(new_order)

    return {
        "order_id": new_order.id,
        "subtotal": subtotal,
        "discount": discount_amount,
        "total": total,
        "qr_url": payment_service.build_qr_url(shop, total, new_order.id),
    }


def get_order(db: Session, current_user: models.User, order_id: int) -> Dict[str, Any]:
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Không tìm thấy đơn hàng")
    shop = db.query(models.Shop).filter(models.Shop.id == order.shop_id).first()
    if not shop:
        raise HTTPException(status_code=404, detail="Không tìm thấy cửa hàng của đơn hàng")
    if current_user.role != "ADMIN" and shop.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Không có quyền truy cập đơn hàng này")
    return {
        "id": order.id,
        "shop_id": order.shop_id,
        "status": order.status,
        "total_amount": order.total_amount,
        "payment_method": order.payment_method,
    }


def pay_order(db: Session, current_user: models.User, order_id: int) -> Dict[str, str]:
    """Xác nhận thủ công tại POS (đã nhận tiền mặt / đã thấy tiền về)."""
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    require_shop_access(db, order.shop_id, current_user)
    order.status = "PAID"
    db.commit()
    log_system_action(
        db,
        current_user.id,
        "PAY_ORDER",
        f"Thanh toán thành công đơn #{order.id} - Tổng tiền: {order.total_amount:,.0f}đ",
    )
    return {"msg": "Paid successfully"}


def apply_webhook_payment(db: Session, request_data: Dict[str, Any]) -> List[int]:
    """Đánh dấu PAID cho các đơn tìm được trong payload.
    Idempotent: webhook gửi lặp không xử lý lại đơn đã PAID."""
    order_ids = payment_service.extract_order_ids(request_data)
    if not order_ids:
        raise HTTPException(
            status_code=400,
            detail="Không tìm thấy mã đơn hàng ORDERxxx trong thông tin thanh toán",
        )

    updated_orders: List[int] = []
    for oid in set(order_ids):
        order = db.query(models.Order).filter(models.Order.id == oid).first()
        if not order:
            continue
        if order.status != "PAID":
            order.status = "PAID"
            db.commit()
            log_system_action(
                db, None, "WEBHOOK_PAYMENT", f"Order {order.id} marked PAID via webhook"
            )
        updated_orders.append(order.id)

    if not updated_orders:
        raise HTTPException(status_code=404, detail="Không tìm thấy đơn hàng tương ứng")
    return updated_orders
