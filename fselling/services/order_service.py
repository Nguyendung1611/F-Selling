"""Nghiệp vụ đơn hàng: tạo đơn (giá từ DB), tra cứu, xác nhận thanh toán, webhook."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from .. import models
from ..dependencies import require_shop_access
from ..schemas.order import OrderCreate
from . import inventory_service, payment_service, voucher_service
from .log_service import log_system_action


# --- Máy trạng thái đơn hàng ---
# PENDING ------> PAID          (xác nhận thủ công | webhook)
# PENDING ------> CANCELLED     (hủy đơn - A1d)
# CANCELLED ----> UNRECONCILED  (CHỈ webhook: tiền về sau khi đơn đã hủy)
# UNRECONCILED -> PAID          (CHỈ thủ công: seller đã đối soát xong)
# PAID là trạng thái cuối. Mọi đường khác đều bị từ chối.
STATUS_PENDING = "PENDING"
STATUS_PAID = "PAID"
STATUS_CANCELLED = "CANCELLED"
STATUS_UNRECONCILED = "UNRECONCILED"

MANUAL_PAY_FROM: Tuple[str, ...] = (STATUS_PENDING, STATUS_UNRECONCILED)
WEBHOOK_PAY_FROM: Tuple[str, ...] = (STATUS_PENDING,)
CANCEL_FROM: Tuple[str, ...] = (STATUS_PENDING,)

_UPDATE_STATUS = (
    text(
        "UPDATE orders SET status = :to_state "
        "WHERE id = :order_id AND status IN :from_states"
    ).bindparams(bindparam("from_states", expanding=True))
)


def read_status(db: Session, order_id: int) -> Optional[str]:
    """Đọc trạng thái hiện tại từ DB. None nếu đơn không tồn tại."""
    return db.execute(
        text("SELECT status FROM orders WHERE id = :order_id"), {"order_id": order_id}
    ).scalar()


def transition_status(
    db: Session, order_id: int, from_states: Tuple[str, ...], to_state: str
) -> bool:
    """Chuyển trạng thái bằng UPDATE có điều kiện.

    Trả True chỉ khi CHÍNH lời gọi này thực hiện được việc chuyển. Đọc-rồi-ghi
    sẽ bị race giữa hủy đơn / xác nhận thủ công / webhook chạy song song; ở đây
    DB tự quyết ai thắng, kẻ thua nhận False và KHÔNG được làm tác dụng phụ
    (hoàn kho, hoàn lượt voucher, ghi log thanh toán).
    """
    result = db.execute(
        _UPDATE_STATUS,
        {"to_state": to_state, "order_id": order_id, "from_states": list(from_states)},
    )
    db.commit()
    return result.rowcount == 1


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
    """Xác nhận thủ công tại POS (đã nhận tiền mặt / đã thấy tiền về).

    Cho phép PENDING -> PAID và UNRECONCILED -> PAID (seller đã đối soát xong).
    Đơn đã PAID: trả 200 im lặng (bấm trùng ở POS là chuyện thường).
    Đơn đã CANCELLED: từ chối 409 - kho đã được hoàn, không được hồi sinh.
    """
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    require_shop_access(db, order.shop_id, current_user)

    if order.status == STATUS_PAID:
        return {"msg": "Paid successfully"}

    # Giữ lại trước khi commit vì commit sẽ expire ORM object.
    total_amount = order.total_amount

    if not transition_status(db, order_id, MANUAL_PAY_FROM, STATUS_PAID):
        current = read_status(db, order_id)
        if current == STATUS_PAID:
            # Đường khác vừa thanh toán xong ngay trước ta -> coi như thành công.
            return {"msg": "Paid successfully"}
        raise HTTPException(
            status_code=409,
            detail=f"Không thể xác nhận thanh toán cho đơn ở trạng thái {current}",
        )

    log_system_action(
        db,
        current_user.id,
        "PAY_ORDER",
        f"Thanh toán thành công đơn #{order_id} - Tổng tiền: {total_amount:,.0f}đ",
    )
    return {"msg": "Paid successfully"}


def apply_webhook_payment(db: Session, request_data: Dict[str, Any]) -> Dict[str, List[int]]:
    """Xử lý biến động số dư từ ngân hàng.

    - PENDING -> PAID.
    - PAID: bỏ qua (webhook gửi lặp), vẫn báo thành công.
    - CANCELLED/UNRECONCILED: tiền về cho đơn đã hủy -> đánh dấu UNRECONCILED
      để người đối soát xử lý, KHÔNG tự động PAID.

    Không bao giờ raise lỗi cho các tình huống trạng thái: ngân hàng sẽ retry
    vô hạn nếu nhận 4xx/5xx. Bất thường được đẩy vào SystemLog.
    """
    order_ids = payment_service.extract_order_ids(request_data)
    if not order_ids:
        raise HTTPException(
            status_code=400,
            detail="Không tìm thấy mã đơn hàng ORDERxxx trong thông tin thanh toán",
        )

    paid: List[int] = []
    unreconciled: List[int] = []
    found_any = False

    for oid in sorted(set(order_ids)):
        if read_status(db, oid) is None:
            continue
        found_any = True

        if transition_status(db, oid, WEBHOOK_PAY_FROM, STATUS_PAID):
            log_system_action(db, None, "WEBHOOK_PAYMENT", f"Order {oid} marked PAID via webhook")
            paid.append(oid)
            continue

        current = read_status(db, oid)
        if current == STATUS_PAID:
            paid.append(oid)  # webhook gửi lặp
        elif current == STATUS_CANCELLED:
            if transition_status(db, oid, (STATUS_CANCELLED,), STATUS_UNRECONCILED):
                log_system_action(
                    db,
                    None,
                    "WEBHOOK_UNRECONCILED",
                    f"Order {oid}: tiền về sau khi đơn đã hủy - cần đối soát thủ công",
                )
            unreconciled.append(oid)
        elif current == STATUS_UNRECONCILED:
            unreconciled.append(oid)

    if not found_any:
        raise HTTPException(status_code=404, detail="Không tìm thấy đơn hàng tương ứng")
    return {"paid": paid, "unreconciled": unreconciled}
