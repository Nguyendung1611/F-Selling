"""Nghiệp vụ đơn hàng: tạo đơn (giá từ DB), tra cứu, xác nhận thanh toán, webhook."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy import bindparam, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models
from ..core.i18n import tr
from ..dependencies import (
    PERMISSION_RECONCILIATION,
    PERMISSION_SALE,
    STAFF_ROLE_CASHIER,
    effective_staff_role,
    has_shop_operator_access,
    require_shop_access,
    require_staff_permission,
)
from ..schemas.order import (
    CashPayment,
    CashTopup,
    DebtPayment,
    OrderCreate,
    RefundComplete,
)
from . import inventory_service, payment_service, voucher_service
from .log_service import log_system_action


# --- Máy trạng thái đơn hàng ---
# PENDING ------> PAID          (tiền mặt | webhook đủ tiền)
# PENDING ------> CANCELLED     (hủy đơn - A1d)
# DEBT ---------> PAID          (F4: khách trả đủ nợ, có thể qua nhiều lần trả)
# DEBT ---------> CANCELLED     (F4: hủy đơn nợ CHƯA thu đồng nào)
# CANCELLED ----> UNRECONCILED  (CHỈ webhook: tiền về sau khi đơn đã hủy)
# UNRECONCILED -> PAID          (webhook cộng dồn đủ | bù tiền mặt phần thiếu)
# PAID là trạng thái cuối. Mọi đường khác đều bị từ chối.
STATUS_PENDING = "PENDING"
STATUS_PAID = "PAID"
STATUS_CANCELLED = "CANCELLED"
STATUS_UNRECONCILED = "UNRECONCILED"
# F4: bán ghi nợ. CỐ Ý là một trạng thái riêng chứ không dùng lại PENDING, vì
# PENDING đang mang nghĩa "đang chờ khách trả tiền ngay bây giờ" và có hai cỗ
# máy bám vào nghĩa đó:
#   - `cancel_expired_pending_orders` hủy mọi đơn PENDING quá hạn và hoàn tồn
#     kho -> để đơn nợ ở PENDING là một ngày nào đó sổ nợ bị xóa sạch và số hàng
#     khách đã cầm về được cộng trả vào kho.
#   - `close_shift` không cho đóng ca khi còn đơn PENDING tiền mặt -> thu ngân
#     sẽ không bao giờ kết ca được, vì đơn nợ treo hàng tuần là chuyện bình thường.
# Cả hai chỗ đó lọc đúng chuỗi "PENDING" nên trạng thái riêng tự tránh được.
STATUS_DEBT = "DEBT"

MANUAL_PAY_FROM: Tuple[str, ...] = (STATUS_PENDING,)
WEBHOOK_PAY_FROM: Tuple[str, ...] = (STATUS_PENDING,)
CANCEL_FROM: Tuple[str, ...] = (STATUS_PENDING, STATUS_DEBT)
DEBT_PAY_FROM: Tuple[str, ...] = (STATUS_DEBT,)

PAYMENT_METHOD_TRANSFER = "transfer"
PAYMENT_METHOD_CASH = "cash"
PAYMENT_METHOD_DEBT = "debt"
# Trước F4 trường này KHÔNG được kiểm gì cả: client gửi chuỗi nào cũng lưu
# nguyên vào DB. Giờ có hình thức "ghi nợ" mang hệ quả tài chính thật thì bắt
# buộc phải chốt danh sách, nếu không client tự khai khống được.
PAYMENT_METHODS = frozenset(
    {PAYMENT_METHOD_TRANSFER, PAYMENT_METHOD_CASH, PAYMENT_METHOD_DEBT}
)

ENTRY_DEBT_CASH = "DEBT_CASH"
ENTRY_DEBT_TRANSFER = "DEBT_TRANSFER"

RECON_UNDERPAID = "UNDERPAID"
RECON_OVERPAID = "OVERPAID"
RECON_LATE_PAYMENT = "LATE_PAYMENT"
RECON_LEGACY_REVIEW = "LEGACY_REVIEW"

ENTRY_BANK = "BANK_IN"
ENTRY_CASH = "CASH_TOPUP"
ENTRY_REFUND_CASH = "REFUND_CASH"
ENTRY_REFUND_TRANSFER = "REFUND_TRANSFER"

MONEY_EPSILON = 0.001

_UPDATE_STATUS = (
    text(
        "UPDATE orders SET status = :to_state "
        "WHERE id = :order_id AND status IN :from_states"
    ).bindparams(bindparam("from_states", expanding=True))
)


def _so_tien(value: Any) -> float:
    """Giá trị tiền an toàn cho dữ liệu cũ có thể NULL."""
    return float(value or 0)


def payment_summary(order: models.Order) -> Dict[str, Any]:
    """Một nguồn dữ liệu thống nhất cho polling POS, hóa đơn và dashboard."""
    bank = _so_tien(order.paid_amount)
    cash = _so_tien(order.cash_paid_amount)
    received = bank + cash
    total = _so_tien(order.total_amount)
    late = order.reconciliation_reason == RECON_LATE_PAYMENT
    remaining = 0 if late else max(total - received, 0)
    overpaid = received if late else max(received - total, 0)
    refund_due = max(_so_tien(order.refund_due_amount), 0)
    refund_pending = refund_due > MONEY_EPSILON and order.refund_completed_at is None
    return {
        "bank_paid_amount": bank,
        "cash_paid_amount": cash,
        "received_amount": received,
        "remaining_amount": remaining,
        "overpaid_amount": overpaid,
        "refunded_amount": _so_tien(order.refunded_amount),
        "refund_due_amount": refund_due,
        "refund_pending": refund_pending,
        "refund_completed_at": order.refund_completed_at,
        "refund_completed_by": order.refund_completed_by,
        "refund_method": order.refund_method,
        "refund_note": order.refund_note,
        "refund_reference": order.refund_reference,
        "reconciliation_reason": order.reconciliation_reason,
        "reconciliation_pending": (
            order.status == STATUS_UNRECONCILED or refund_pending
        ),
        "invoice_issued": order.status == STATUS_PAID,
    }


def _them_nhat_ky(
    db: Session, user_id: Optional[int], action: str, details: str
) -> None:
    """Thêm audit vào transaction hiện tại, KHÔNG tự commit."""
    db.add(
        models.SystemLog(
            user_id=user_id,
            action=action,
            details=details,
        )
    )


def _serialize_payment(payment: models.OrderPayment) -> Dict[str, Any]:
    return {
        "id": payment.id,
        "entry_type": payment.entry_type,
        "amount": payment.amount,
        "provider": payment.provider,
        "bank_txn_id": payment.bank_txn_id,
        "account_no": payment.account_no,
        "created_by_user_id": payment.created_by_user_id,
        "shift_id": payment.shift_id,
        "note": payment.note,
        "reference": payment.reference,
        "created_at": payment.created_at,
    }


def _current_cash_shift(
    db: Session,
    current_user: models.User,
    shop_id: int,
    *,
    required_for_cashier: bool = False,
    required_for_everyone: bool = False,
    lock_for_cash_write: bool = False,
) -> Optional[models.CashShift]:
    """Ca OPEN của chính người đang thao tác trong shop.

    `/pay` cũ vẫn cho chủ shop/MANAGER thu tiền không qua ca để không phá
    client cũ; riêng CASHIER luôn phải mở ca. Các nghiệp vụ đối soát tiền mặt
    mới dùng ``required_for_everyone`` để mọi khoản thu/hoàn đều vào đúng két.
    """
    shift = (
        db.query(models.CashShift)
        .filter(
            models.CashShift.shop_id == shop_id,
            models.CashShift.opened_by_user_id == current_user.id,
            models.CashShift.status == "OPEN",
        )
        .order_by(models.CashShift.id.desc())
        .first()
    )
    cashier_must_open = (
        required_for_cashier
        and current_user.role == "STAFF"
        and effective_staff_role(current_user) == STAFF_ROLE_CASHIER
    )
    if shift is None and (required_for_everyone or cashier_must_open):
        raise HTTPException(
            status_code=409,
            detail=tr("Hãy mở ca của bạn tại POS trước khi ghi nhận tiền mặt"),
        )
    if shift is not None and lock_for_cash_write:
        # SQLite không có SELECT FOR UPDATE. No-op UPDATE lấy write lock và
        # đồng thời xác nhận ca vẫn OPEN; close_shift dùng đúng hàng rào này.
        # Nhờ vậy kết ca không thể chụp expected rồi một payment đến muộn lại
        # gắn vào chính ca CLOSED đó.
        locked = db.execute(
            text(
                "UPDATE cash_shifts SET status = status "
                "WHERE id = :shift_id AND status = 'OPEN'"
            ),
            {"shift_id": shift.id},
        )
        if locked.rowcount != 1:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail=tr("Ca vừa được đóng; vui lòng tải lại và mở ca mới"),
            )
    return shift


def read_status(db: Session, order_id: int) -> Optional[str]:
    """Đọc trạng thái hiện tại từ DB. None nếu đơn không tồn tại."""
    return db.execute(
        text("SELECT status FROM orders WHERE id = :order_id"), {"order_id": order_id}
    ).scalar()


def apply_transition(
    db: Session, order_id: int, from_states: Tuple[str, ...], to_state: str
) -> bool:
    """Như `transition_status` nhưng KHÔNG commit.

    Dùng khi việc chuyển trạng thái phải nằm chung một transaction với các
    tác dụng phụ (hoàn kho, hoàn lượt voucher) - hoặc cùng thành công, hoặc
    cùng không có gì xảy ra.
    """
    result = db.execute(
        _UPDATE_STATUS,
        {"to_state": to_state, "order_id": order_id, "from_states": list(from_states)},
    )
    return result.rowcount == 1


def transition_status(
    db: Session, order_id: int, from_states: Tuple[str, ...], to_state: str
) -> bool:
    """Chuyển trạng thái bằng UPDATE có điều kiện.

    Trả True chỉ khi CHÍNH lời gọi này thực hiện được việc chuyển. Đọc-rồi-ghi
    sẽ bị race giữa hủy đơn / xác nhận thủ công / webhook chạy song song; ở đây
    DB tự quyết ai thắng, kẻ thua nhận False và KHÔNG được làm tác dụng phụ
    (hoàn kho, hoàn lượt voucher, ghi log thanh toán).
    """
    changed = apply_transition(db, order_id, from_states, to_state)
    db.commit()
    return changed


def _order_operation_fingerprint(order: OrderCreate) -> str:
    """Dấu vân tay phần request có ý nghĩa nghiệp vụ, bỏ giá client gửi."""
    items = sorted(
        [
            {
                "product_id": item.product_id,
                "product_name": (item.product_name or "").strip() or None,
                "quantity": item.quantity,
            }
            for item in order.items
        ],
        key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True),
    )
    payload = {
        "items": items,
        "voucher_code": (order.voucher_code or "").strip().upper() or None,
        "payment_method": order.payment_method,
        "customer_id": order.customer_id,
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _create_order_response(
    shop: models.Shop, existing: models.Order
) -> Dict[str, Any]:
    discount = _so_tien(existing.discount_amount)
    total = _so_tien(existing.total_amount)
    return {
        "order_id": existing.id,
        "subtotal": total + discount,
        "discount": discount,
        "total": total,
        "qr_url": payment_service.build_qr_url(shop, total, existing.id),
    }


def _existing_operation_order(
    db: Session,
    shop: models.Shop,
    current_user: models.User,
    operation_id: str,
    fingerprint: str,
) -> Optional[Dict[str, Any]]:
    existing = (
        db.query(models.Order)
        .filter(models.Order.operation_id == operation_id)
        .first()
    )
    if existing is None:
        return None
    if (
        existing.shop_id != shop.id
        or existing.created_by_user_id != current_user.id
        or existing.operation_fingerprint != fingerprint
    ):
        raise HTTPException(
            status_code=409,
            detail=tr("Mã retry tạo đơn đã được dùng cho một đơn khác"),
        )
    return _create_order_response(shop, existing)


def cong_no_cua_khach(db: Session, customer_id: int) -> float:
    """Tổng tiền khách còn nợ: phần chưa trả của mọi đơn đang ở trạng thái DEBT.

    Tính từ chính các đơn chứ không giữ một cột "tổng nợ" trên `customers`: cột
    tổng như vậy là nguồn sự thật thứ hai, và chỉ cần một đường ghi quên cập
    nhật là sổ nợ lệch mà không ai biết cho tới lúc đối chiếu với khách.
    """
    don_no = (
        db.query(models.Order)
        .filter(
            models.Order.customer_id == customer_id,
            models.Order.status == STATUS_DEBT,
        )
        .all()
    )
    tong = 0.0
    for o in don_no:
        da_tra = _so_tien(o.paid_amount) + _so_tien(o.cash_paid_amount)
        tong += max(_so_tien(o.total_amount) - da_tra, 0.0)
    return tong


def _kiem_ban_ghi_no(
    db: Session, khach: Optional[models.Customer], tong_don: float
) -> None:
    """Hai điều kiện để được ghi nợ, kiểm ngay trước khi tạo đơn."""
    if khach is None:
        raise HTTPException(
            status_code=400,
            detail=tr("Bán ghi nợ phải chọn khách hàng"),
        )
    if khach.credit_limit is None:
        return
    dang_no = cong_no_cua_khach(db, khach.id)
    if dang_no + tong_don > _so_tien(khach.credit_limit) + MONEY_EPSILON:
        raise HTTPException(
            status_code=400,
            detail=tr(
                "Khách '{name}' đang nợ {current} và hạn mức là {limit}; "
                "đơn này {amount} sẽ vượt hạn mức",
                name=khach.name,
                current=f"{dang_no:,.0f}đ",
                limit=f"{_so_tien(khach.credit_limit):,.0f}đ",
                amount=f"{tong_don:,.0f}đ",
            ),
        )


def _lock_shop_for_order(db: Session, shop_id: int) -> None:
    """Tuần tự hóa phần kiểm tồn/voucher và ghi đơn trong cùng một shop.

    SQLite không có ``SELECT FOR UPDATE``. No-op UPDATE này lấy write lock
    trước khi đọc tồn kho và số lượt voucher; transaction giữ lock tới commit.
    Nếu sau này đổi database có row lock, chính hàng shop này vẫn là hàng rào
    chung cho mọi thu ngân của cùng cửa hàng.
    """
    locked = db.execute(
        text("UPDATE shops SET id = id WHERE id = :shop_id"),
        {"shop_id": shop_id},
    )
    if locked.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=404, detail=tr("Không tìm thấy cửa hàng"))


def create_order(
    db: Session, current_user: models.User, shop_id: int, order: OrderCreate
) -> Dict[str, Any]:
    # Yêu cầu đăng nhập và chỉ chủ shop (hoặc admin) mới được tạo đơn cho shop này.
    shop = require_shop_access(db, shop_id, current_user)
    require_staff_permission(current_user, PERMISSION_SALE)

    if not order.items:
        raise HTTPException(
            status_code=400,
            detail=tr("Đơn hàng không có sản phẩm nào"),
        )
    if order.payment_method not in PAYMENT_METHODS:
        raise HTTPException(
            status_code=400,
            detail=tr(
                "Hình thức thanh toán không hợp lệ",
            ),
        )
    operation_id = (order.operation_id or "").strip() or None
    operation_fingerprint = _order_operation_fingerprint(order)
    if operation_id:
        existing_response = _existing_operation_order(
            db,
            shop,
            current_user,
            operation_id,
            operation_fingerprint,
        )
        if existing_response is not None:
            return existing_response

    # Mọi phép đọc có thể quyết định việc ghi (tồn kho, lượt voucher) phải nằm
    # sau cùng một write lock. Hai cashier có ca khác nhau không thể chỉ dựa
    # vào shift lock vì khi đó cả hai đã kịp đọc cùng snapshot tồn/lượt dùng.
    _lock_shop_for_order(db, shop_id)

    # Một retry có thể đã hoàn tất trong lúc request này chờ shop lock. Kiểm
    # lại ngay sau lock để không resolve/trừ kho/tăng voucher lần thứ hai.
    if operation_id:
        existing_response = _existing_operation_order(
            db,
            shop,
            current_user,
            operation_id,
            operation_fingerprint,
        )
        if existing_response is not None:
            # Chỉ có no-op UPDATE ở transaction này. Response đã là dict nên
            # rollback an toàn và nhả write lock ngay, không chờ dependency
            # đóng Session sau khi FastAPI dựng xong response.
            db.rollback()
            return existing_response

    # Tính tiền TỪ DB, không tin giá client gửi.
    wanted = inventory_service.collect_quantities(order.items)
    resolved_items, subtotal = inventory_service.resolve_items(db, shop_id, wanted)

    applied_voucher, discount_amount = voucher_service.resolve_for_order(
        db, shop_id, order.voucher_code, subtotal
    )

    total = subtotal - discount_amount
    if total < 0:
        total = 0
    current_shift = _current_cash_shift(
        db,
        current_user,
        shop_id,
        lock_for_cash_write=True,
    )

    # Khách hàng gắn vào đơn (tùy chọn, TRỪ đơn ghi nợ). Phải là khách của ĐÚNG
    # shop này - không cho mượn customer_id của shop khác.
    customer_id = None
    khach = None
    if order.customer_id is not None:
        khach = (
            db.query(models.Customer)
            .filter(
                models.Customer.id == order.customer_id,
                models.Customer.shop_id == shop_id,
            )
            .first()
        )
        if not khach:
            raise HTTPException(
                status_code=404,
                detail=tr("Khách hàng không tồn tại trong cửa hàng này"),
            )
        customer_id = khach.id

    ghi_no = order.payment_method == PAYMENT_METHOD_DEBT
    if ghi_no:
        # Nợ mà không biết ai nợ thì không đòi được. Kiểm hạn mức nằm sau
        # `_lock_shop_for_order` nên hai đơn nợ cùng lúc của một khách không thể
        # cùng nhìn thấy một số dư cũ rồi cùng lọt qua.
        _kiem_ban_ghi_no(db, khach, total)

    new_order = models.Order(
        shop_id=shop_id,
        created_by_user_id=current_user.id,
        shift_id=current_shift.id if current_shift else None,
        operation_id=operation_id,
        operation_fingerprint=operation_fingerprint if operation_id else None,
        total_amount=total,
        discount_amount=discount_amount,
        voucher_code=order.voucher_code,
        payment_method=order.payment_method,
        customer_id=customer_id,
        # Đơn được giảm về 0đ không có giao dịch ngân hàng dương để chờ.
        status=(
            STATUS_PAID
            if total <= MONEY_EPSILON
            else (STATUS_DEBT if ghi_no else STATUS_PENDING)
        ),
    )
    db.add(new_order)
    try:
        db.flush()  # lấy id mà chưa commit, cùng một transaction
    except IntegrityError:
        db.rollback()
        if operation_id:
            existing_response = _existing_operation_order(
                db,
                shop,
                current_user,
                operation_id,
                operation_fingerprint,
            )
            if existing_response is not None:
                return existing_response
        raise

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
                # Ảnh chụp giá vốn, cùng lý do với product_name ở trên. Nhập lô
                # hàng giá khác sau này không được phép làm đổi lãi của đơn đã
                # bán - mà tra ngược Product.cost_price lúc làm báo cáo thì đúng
                # là như vậy, và không lấy lại được số cũ nữa.
                # NULL ở đây = chưa khai giá vốn; báo cáo đếm riêng, không tính
                # thành lãi bằng cả giá bán.
                cost_price=prod.cost_price,
                quantity=qty,
            )
        )
    inventory_service.deduct_stock(resolved_items)

    if applied_voucher is not None:
        applied_voucher.usage_count = (applied_voucher.usage_count or 0) + 1

    db.commit()
    db.refresh(new_order)

    return _create_order_response(shop, new_order)


def get_order(db: Session, current_user: models.User, order_id: int) -> Dict[str, Any]:
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail=tr("Không tìm thấy đơn hàng"))
    shop = db.query(models.Shop).filter(models.Shop.id == order.shop_id).first()
    if not shop:
        raise HTTPException(
            status_code=404,
            detail=tr("Không tìm thấy cửa hàng của đơn hàng"),
        )
    if not has_shop_operator_access(shop, current_user):
        raise HTTPException(
            status_code=403,
            detail=tr("Không có quyền truy cập đơn hàng này"),
        )
    require_staff_permission(current_user, PERMISSION_SALE)
    result = {
        "id": order.id,
        "shop_id": order.shop_id,
        "status": order.status,
        "total_amount": order.total_amount,
        "payment_method": order.payment_method,
    }
    result.update(payment_summary(order))
    return result


def pay_order(
    db: Session,
    current_user: models.User,
    order_id: int,
    request: Optional[CashPayment] = None,
) -> Dict[str, str]:
    """Thu tiền mặt cho đơn PENDING.

    Đơn chuyển khoản phải do webhook xác nhận; không còn đường bấm tay biến
    UNDERPAID/LATE_PAYMENT thành PAID.
    """
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail=tr("Không tìm thấy đơn hàng"))
    require_shop_access(db, order.shop_id, current_user)
    require_staff_permission(current_user, PERMISSION_SALE)

    if order.payment_method == PAYMENT_METHOD_DEBT:
        # Nói đúng đường phải đi, thay vì để rơi vào câu "chờ ngân hàng xác
        # nhận" ở dưới - câu đó sai hoàn toàn với đơn ghi nợ.
        raise HTTPException(
            status_code=409,
            detail=tr("Đơn ghi nợ thu tiền qua chức năng thu nợ"),
        )
    if order.payment_method != PAYMENT_METHOD_CASH:
        raise HTTPException(
            status_code=409,
            detail=tr("Đơn chuyển khoản phải chờ ngân hàng xác nhận tự động"),
        )

    if order.status == STATUS_PAID:
        return {"msg": "Paid successfully"}

    total_amount = _so_tien(order.total_amount)
    tendered_amount = (
        total_amount if request is None else float(request.tendered_amount)
    )
    if not math.isfinite(tendered_amount) or tendered_amount < total_amount:
        raise HTTPException(
            status_code=400,
            detail=tr(
                "Tiền khách đưa phải ít nhất {amount}đ",
                amount=f"{total_amount:,.0f}",
            ),
        )
    change_amount = tendered_amount - total_amount
    shift = _current_cash_shift(
        db,
        current_user,
        order.shop_id,
        required_for_cashier=True,
        lock_for_cash_write=True,
    )

    if not apply_transition(db, order_id, MANUAL_PAY_FROM, STATUS_PAID):
        db.rollback()
        current = read_status(db, order_id)
        if current == STATUS_PAID:
            return {"msg": "Paid successfully"}
        raise HTTPException(
            status_code=409,
            detail=tr(
                "Không thể xác nhận thanh toán cho đơn ở trạng thái {status}",
                status=current,
            ),
        )

    db.execute(
        text(
            "UPDATE orders SET cash_paid_amount = :amount, "
            "cash_tendered_amount = :tendered, "
            "cash_change_amount = :change, "
            "shift_id = :shift_id, "
            "reconciliation_reason = NULL, refund_due_amount = 0 "
            "WHERE id = :order_id"
        ),
        {
            "amount": total_amount,
            "tendered": tendered_amount,
            "change": change_amount,
            "shift_id": shift.id if shift else None,
            "order_id": order_id,
        },
    )
    db.add(
        models.OrderPayment(
            order_id=order_id,
            entry_type=ENTRY_CASH,
            amount=total_amount,
            created_by_user_id=current_user.id,
            shift_id=shift.id if shift else None,
            note="Thu tiền mặt khi thanh toán đơn",
        )
    )
    _them_nhat_ky(
        db,
        current_user.id,
        "PAY_ORDER",
        f"Thanh toán tiền mặt đơn #{order_id} - Tổng tiền: {total_amount:,.0f}đ",
    )
    db.commit()
    return {"msg": "Paid successfully"}


def _cash_topup_amount(order: models.Order, request: CashTopup) -> float:
    """Kiểm trạng thái và trả đúng số tiền mặt còn thiếu của đơn."""
    if (
        order.status != STATUS_UNRECONCILED
        or order.reconciliation_reason != RECON_UNDERPAID
    ):
        raise HTTPException(
            status_code=409,
            detail=tr(
                "Chỉ được thu bù tiền mặt cho đơn chuyển thiếu đang chờ đối soát"
            ),
        )

    received = _so_tien(order.paid_amount) + _so_tien(order.cash_paid_amount)
    remaining = max(_so_tien(order.total_amount) - received, 0)
    if remaining <= MONEY_EPSILON:
        raise HTTPException(status_code=409, detail=tr("Đơn không còn thiếu tiền"))
    if request.amount is not None:
        requested_amount = float(request.amount)
        if (
            not math.isfinite(requested_amount)
            or abs(requested_amount - remaining) > MONEY_EPSILON
        ):
            raise HTTPException(
                status_code=400,
                detail=tr(
                    "Tiền mặt phải bù đúng toàn bộ phần còn thiếu là {amount}đ",
                    amount=f"{remaining:,.0f}",
                ),
            )
    amount = remaining
    if not math.isfinite(amount) or amount <= MONEY_EPSILON:
        raise HTTPException(
            status_code=400,
            detail=tr("Số tiền bù phải lớn hơn 0"),
        )
    return amount


def cash_topup(
    db: Session,
    current_user: models.User,
    order_id: int,
    request: CashTopup,
) -> Dict[str, Any]:
    """Ghi nhận tiền mặt bù cho đúng đơn đang thiếu.

    UPDATE có điều kiện bảo đảm webhook và hai cú bấm thu bù không thể cùng
    thắng dựa trên một số dư cũ. Nếu bỏ amount, thu đúng toàn bộ phần còn thiếu.
    Mọi vai trò đều phải có ca OPEN của chính mình để khoản tiền vào đúng két.
    """
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail=tr("Không tìm thấy đơn hàng"))
    require_shop_access(db, order.shop_id, current_user)
    require_staff_permission(current_user, PERMISSION_SALE)

    # Trả lỗi trạng thái/số tiền rõ ràng trước; request hợp lệ mới yêu cầu ca.
    amount = _cash_topup_amount(order, request)
    shift = _current_cash_shift(
        db,
        current_user,
        order.shop_id,
        required_for_everyone=True,
        lock_for_cash_write=True,
    )
    assert shift is not None
    # Có thể đã chờ một cash write khác. Đọc lại sau lock để không thu theo số
    # dư cũ; câu UPDATE có điều kiện bên dưới vẫn là hàng rào cuối cùng.
    db.refresh(order)
    amount = _cash_topup_amount(order, request)

    result = db.execute(
        text(
            """
            UPDATE orders
            SET cash_paid_amount = COALESCE(cash_paid_amount, 0) + :amount,
                status = CASE
                    WHEN COALESCE(paid_amount, 0)
                       + COALESCE(cash_paid_amount, 0) + :amount
                         >= total_amount - :epsilon
                    THEN :paid ELSE :unreconciled END,
                reconciliation_reason = CASE
                    WHEN COALESCE(paid_amount, 0)
                       + COALESCE(cash_paid_amount, 0) + :amount
                         >= total_amount - :epsilon
                    THEN NULL ELSE :underpaid END
            WHERE id = :order_id
              AND status = :unreconciled
              AND reconciliation_reason = :underpaid
              AND COALESCE(paid_amount, 0)
                + COALESCE(cash_paid_amount, 0) + :amount
                  <= total_amount + :epsilon
            """
        ),
        {
            "amount": amount,
            "epsilon": MONEY_EPSILON,
            "paid": STATUS_PAID,
            "unreconciled": STATUS_UNRECONCILED,
            "underpaid": RECON_UNDERPAID,
            "order_id": order_id,
        },
    )
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=tr(
                "Số tiền của đơn vừa thay đổi; vui lòng tải lại trước khi thu bù"
            ),
        )

    note = (request.note or "").strip()[:500] or None
    db.add(
        models.OrderPayment(
            order_id=order_id,
            entry_type=ENTRY_CASH,
            amount=amount,
            created_by_user_id=current_user.id,
            shift_id=shift.id if shift else None,
            note=note or "Thu bù phần thiếu bằng tiền mặt",
        )
    )
    _them_nhat_ky(
        db,
        current_user.id,
        "CASH_TOPUP",
        f"Order {order_id}: thu bù tiền mặt {amount:,.0f}đ"
        + (f" - {note}" if note else ""),
    )
    db.commit()
    db.refresh(order)
    response = {
        "msg": (
            tr("Đã thu đủ và hoàn tất đơn hàng")
            if order.status == STATUS_PAID
            else tr("Đã ghi nhận khoản tiền mặt bù thiếu")
        ),
        "id": order.id,
        "status": order.status,
        "total_amount": order.total_amount,
    }
    response.update(payment_summary(order))
    return response


def debt_payment(
    db: Session,
    current_user: models.User,
    order_id: int,
    request: DebtPayment,
) -> Dict[str, Any]:
    """Khách trả bớt nợ. Trả bao nhiêu cũng được, trả nhiều lần cũng được.

    Đủ tiền thì đơn tự chuyển sang `PAID` - và chỉ khi đó doanh thu mới ghi
    nhận, đúng nguyên tắc thực thu đang dùng cho cả app.
    """
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail=tr("Không tìm thấy đơn hàng"))
    require_shop_access(db, order.shop_id, current_user)
    require_staff_permission(current_user, PERMISSION_SALE)

    operation_id = (request.operation_id or "").strip()
    if len(operation_id) < 8:
        raise HTTPException(
            status_code=400,
            detail=tr("Mã thao tác thu nợ không hợp lệ"),
        )
    operation_key = (
        "debt:" + hashlib.sha256(operation_id.encode("utf-8")).hexdigest()
    )

    so_tien = float(request.amount or 0)
    if not math.isfinite(so_tien) or so_tien <= MONEY_EPSILON:
        raise HTTPException(
            status_code=400,
            detail=tr("Số tiền thu phải lớn hơn 0"),
        )

    da_ghi = (
        db.query(models.OrderPayment)
        .filter(models.OrderPayment.idempotency_key == operation_key)
        .first()
    )
    if da_ghi is not None:
        if da_ghi.order_id == order_id and da_ghi.entry_type in (
            ENTRY_DEBT_CASH,
            ENTRY_DEBT_TRANSFER,
        ):
            return _ket_qua_thu_no(order, lap_lai=True)
        raise HTTPException(
            status_code=409,
            detail=tr("Mã thao tác thu nợ đã được dùng cho một giao dịch khác"),
        )

    shift = None
    if request.method == "cash":
        # Tiền mặt vào két phải thuộc về ca của người đang đứng quầy, giống hệt
        # mọi khoản tiền mặt khác. Ghi ENTRY_DEBT_CASH và `shift_id` là đủ để
        # `_expected_cash` của shift_service tự cộng vào.
        shift = _current_cash_shift(
            db,
            current_user,
            order.shop_id,
            required_for_everyone=True,
            lock_for_cash_write=True,
        )
        db.refresh(order)

    if order.status != STATUS_DEBT:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=tr("Chỉ thu nợ được cho đơn đang ghi nợ"),
        )

    da_tra = _so_tien(order.paid_amount) + _so_tien(order.cash_paid_amount)
    con_thieu = max(_so_tien(order.total_amount) - da_tra, 0.0)
    if con_thieu <= MONEY_EPSILON:
        db.rollback()
        raise HTTPException(status_code=409, detail=tr("Đơn này không còn nợ"))
    if so_tien > con_thieu + MONEY_EPSILON:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail=tr(
                "Khách chỉ còn nợ {amount}; không thu quá số đó",
                amount=f"{con_thieu:,.0f}",
            ),
        )

    tien_mat = request.method == "cash"
    db.add(
        models.OrderPayment(
            order_id=order_id,
            entry_type=ENTRY_DEBT_CASH if tien_mat else ENTRY_DEBT_TRANSFER,
            amount=so_tien,
            idempotency_key=operation_key,
            created_by_user_id=current_user.id,
            shift_id=shift.id if shift else None,
            note=(request.note or "").strip()[:500] or None,
            reference=(request.reference or "").strip()[:128] or None,
        )
    )
    try:
        db.flush()
    except IntegrityError:
        # Unique idempotency_key: một request song song cùng mã đã ghi trước.
        db.rollback()
        fresh = db.query(models.Order).filter(models.Order.id == order_id).first()
        da_ghi = (
            db.query(models.OrderPayment)
            .filter(models.OrderPayment.idempotency_key == operation_key)
            .first()
        )
        if fresh and da_ghi and da_ghi.order_id == order_id:
            return _ket_qua_thu_no(fresh, lap_lai=True)
        raise

    # Cộng dồn vào đúng cột mà `payment_summary` đang đọc, thay vì dựng thêm một
    # bộ đếm riêng: hai nguồn số liệu về cùng một khoản tiền là chỉ chờ ngày lệch.
    cot = "cash_paid_amount" if tien_mat else "paid_amount"
    ket_qua = db.execute(
        text(
            f"UPDATE orders SET {cot} = COALESCE({cot}, 0) + :so_tien "
            "WHERE id = :order_id AND status = :dang_no "
            f"AND COALESCE(paid_amount, 0) + COALESCE(cash_paid_amount, 0) "
            "+ :so_tien <= total_amount + :epsilon"
        ),
        {
            "so_tien": so_tien,
            "order_id": order_id,
            "dang_no": STATUS_DEBT,
            "epsilon": MONEY_EPSILON,
        },
    )
    if ket_qua.rowcount != 1:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=tr("Số nợ vừa thay đổi; vui lòng tải lại rồi thu lại"),
        )

    db.refresh(order)
    con_thieu_moi = max(
        _so_tien(order.total_amount)
        - _so_tien(order.paid_amount)
        - _so_tien(order.cash_paid_amount),
        0.0,
    )
    tra_het = con_thieu_moi <= MONEY_EPSILON
    if tra_het and not apply_transition(db, order_id, DEBT_PAY_FROM, STATUS_PAID):
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=tr("Trạng thái đơn vừa thay đổi; vui lòng tải lại"),
        )

    _them_nhat_ky(
        db,
        current_user.id,
        "DEBT_PAYMENT",
        f"Order {order_id}: thu nợ {so_tien:,.0f}đ bằng "
        f"{'tiền mặt' if tien_mat else 'chuyển khoản'}"
        f", còn nợ {con_thieu_moi:,.0f}đ"
        + (" - ĐÃ TRẢ HẾT" if tra_het else ""),
    )
    db.commit()
    db.refresh(order)
    return _ket_qua_thu_no(order, lap_lai=False)


def _ket_qua_thu_no(order: models.Order, lap_lai: bool) -> Dict[str, Any]:
    ket_qua = {
        "msg": tr(
            "Lần thu nợ này đã được ghi nhận trước đó"
            if lap_lai
            else "Đã ghi nhận thu nợ"
        ),
        "id": order.id,
        "status": order.status,
        "total_amount": order.total_amount,
    }
    ket_qua.update(payment_summary(order))
    return ket_qua


def complete_refund(
    db: Session,
    current_user: models.User,
    order_id: int,
    request: RefundComplete,
) -> Dict[str, Any]:
    """Ghi nhận đã hoàn toàn bộ khoản đang chờ, không tự chuyển tiền."""
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail=tr("Không tìm thấy đơn hàng"))
    require_shop_access(db, order.shop_id, current_user)
    require_staff_permission(current_user, PERMISSION_RECONCILIATION)

    operation_id = request.operation_id.strip()
    if len(operation_id) < 8:
        raise HTTPException(
            status_code=400,
            detail=tr("Mã thao tác hoàn tiền không hợp lệ"),
        )
    operation_key = (
        "refund:"
        + hashlib.sha256(operation_id.encode("utf-8")).hexdigest()
    )
    previous_operation = (
        db.query(models.OrderPayment)
        .filter(models.OrderPayment.idempotency_key == operation_key)
        .first()
    )
    if previous_operation:
        if (
            previous_operation.order_id == order_id
            and previous_operation.entry_type
            in (ENTRY_REFUND_CASH, ENTRY_REFUND_TRANSFER)
        ):
            response = {
                "msg": tr("Lần hoàn tiền này đã được ghi nhận trước đó"),
                "id": order.id,
                "status": order.status,
                "total_amount": order.total_amount,
            }
            response.update(payment_summary(order))
            return response
        raise HTTPException(
            status_code=409,
            detail=tr("Mã thao tác hoàn tiền đã được dùng cho một giao dịch khác"),
        )

    due = max(_so_tien(order.refund_due_amount), 0)
    if due <= MONEY_EPSILON:
        if order.refund_completed_at is not None:
            # Bấm lặp: trả cùng kết quả nhưng tuyệt đối không ghi thêm lần hoàn.
            response = {
                "msg": tr("Khoản hoàn tiền này đã được ghi nhận trước đó"),
                "id": order.id,
                "status": order.status,
                "total_amount": order.total_amount,
            }
            response.update(payment_summary(order))
            return response
        raise HTTPException(
            status_code=409,
            detail=tr("Đơn hàng không có khoản tiền cần hoàn"),
        )

    if order.reconciliation_reason not in (RECON_OVERPAID, RECON_LATE_PAYMENT):
        raise HTTPException(
            status_code=409,
            detail=tr(
                "Trạng thái đối soát của đơn không cho phép ghi nhận hoàn tiền"
            ),
        )

    refund_shift = None
    if request.method == "cash":
        # Hoàn bằng tiền mặt phải trừ đúng ca/két của người thao tác. Kiểm
        # idempotency ở trên trước để một retry đã thành công vẫn đọc được sau
        # khi ca cũ đã đóng.
        refund_shift = _current_cash_shift(
            db,
            current_user,
            order.shop_id,
            required_for_everyone=True,
            lock_for_cash_write=True,
        )
        assert refund_shift is not None
        # Request cùng operation_id có thể hoàn tất trong lúc chờ shift lock.
        previous_operation = (
            db.query(models.OrderPayment)
            .filter(models.OrderPayment.idempotency_key == operation_key)
            .first()
        )
        if previous_operation:
            db.refresh(order)
            if (
                previous_operation.order_id == order_id
                and previous_operation.entry_type
                in (ENTRY_REFUND_CASH, ENTRY_REFUND_TRANSFER)
            ):
                response = {
                    "msg": tr("Lần hoàn tiền này đã được ghi nhận trước đó"),
                    "id": order.id,
                    "status": order.status,
                    "total_amount": order.total_amount,
                }
                response.update(payment_summary(order))
                db.rollback()
                return response
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail=tr(
                    "Mã thao tác hoàn tiền đã được dùng cho một giao dịch khác"
                ),
            )

        db.refresh(order)
        due = max(_so_tien(order.refund_due_amount), 0)
        if due <= MONEY_EPSILON:
            db.rollback()
            if order.refund_completed_at is not None:
                response = {
                    "msg": tr("Khoản hoàn tiền này đã được ghi nhận trước đó"),
                    "id": order.id,
                    "status": order.status,
                    "total_amount": order.total_amount,
                }
                response.update(payment_summary(order))
                return response
            raise HTTPException(
                status_code=409,
                detail=tr("Đơn hàng không có khoản tiền cần hoàn"),
            )
        if order.reconciliation_reason not in (
            RECON_OVERPAID,
            RECON_LATE_PAYMENT,
        ):
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail=tr(
                    "Trạng thái đối soát của đơn không cho phép ghi nhận hoàn tiền"
                ),
            )

    completed_at = datetime.utcnow()
    target_status = (
        STATUS_CANCELLED
        if order.reconciliation_reason == RECON_LATE_PAYMENT
        else STATUS_PAID
    )
    note = (request.note or "").strip()[:500] or None
    reference = (request.reference or "").strip()[:128] or None
    refund_payment = models.OrderPayment(
        order_id=order_id,
        entry_type=(
            ENTRY_REFUND_CASH
            if request.method == "cash"
            else ENTRY_REFUND_TRANSFER
        ),
        amount=due,
        idempotency_key=operation_key,
        created_by_user_id=current_user.id,
        shift_id=refund_shift.id if refund_shift else None,
        note=note,
        reference=reference,
    )
    db.add(refund_payment)
    try:
        # Unique operation key chặn cả retry đồng thời lẫn retry tới muộn sau
        # khi một chu kỳ hoàn mới đã mở.
        db.flush()
    except IntegrityError:
        db.rollback()
        previous_operation = (
            db.query(models.OrderPayment)
            .filter(models.OrderPayment.idempotency_key == operation_key)
            .first()
        )
        fresh = db.query(models.Order).filter(models.Order.id == order_id).first()
        if (
            previous_operation
            and fresh
            and previous_operation.order_id == order_id
            and previous_operation.entry_type
            in (ENTRY_REFUND_CASH, ENTRY_REFUND_TRANSFER)
        ):
            response = {
                "msg": tr("Lần hoàn tiền này đã được ghi nhận trước đó"),
                "id": fresh.id,
                "status": fresh.status,
                "total_amount": fresh.total_amount,
            }
            response.update(payment_summary(fresh))
            return response
        raise HTTPException(
            status_code=409,
            detail=tr("Mã thao tác hoàn tiền đã được dùng cho một giao dịch khác"),
        )

    result = db.execute(
        text(
            """
            UPDATE orders
            SET refunded_amount = COALESCE(refunded_amount, 0) + :due,
                refund_due_amount = 0,
                refund_completed_at = :completed_at,
                refund_completed_by = :user_id,
                refund_method = :method,
                refund_note = :note,
                refund_reference = :reference,
                status = :target_status
            WHERE id = :order_id
              AND refund_due_amount > :epsilon
              AND ABS(refund_due_amount - :due) <= :epsilon
              AND refund_completed_at IS NULL
              AND reconciliation_reason IN (:overpaid, :late_payment)
            """
        ),
        {
            "due": due,
            "completed_at": completed_at,
            "user_id": current_user.id,
            "method": request.method,
            "note": note,
            "reference": reference,
            "target_status": target_status,
            "order_id": order_id,
            "epsilon": MONEY_EPSILON,
            "overpaid": RECON_OVERPAID,
            "late_payment": RECON_LATE_PAYMENT,
        },
    )
    if result.rowcount != 1:
        db.rollback()
        fresh = db.query(models.Order).filter(models.Order.id == order_id).first()
        if fresh and fresh.refund_completed_at is not None:
            response = {
                "msg": tr("Khoản hoàn tiền này đã được ghi nhận trước đó"),
                "id": fresh.id,
                "status": fresh.status,
                "total_amount": fresh.total_amount,
            }
            response.update(payment_summary(fresh))
            return response
        raise HTTPException(
            status_code=409,
            detail=tr(
                "Khoản cần hoàn vừa thay đổi; vui lòng tải lại trước khi xác nhận"
            ),
        )

    detail = (
        f"Order {order_id}: đã hoàn {due:,.0f}đ bằng "
        f"{'tiền mặt' if request.method == 'cash' else 'chuyển khoản'}"
    )
    if reference:
        detail += f" - mã tham chiếu {reference}"
    if note:
        detail += f" - {note}"
    _them_nhat_ky(db, current_user.id, "REFUND_COMPLETE", detail)
    db.commit()
    db.refresh(order)
    response = {
        "msg": tr("Đã ghi nhận hoàn tiền thành công"),
        "id": order.id,
        "status": order.status,
        "total_amount": order.total_amount,
    }
    response.update(payment_summary(order))
    return response


def get_order_detail(db: Session, current_user: models.User, order_id: int) -> Dict[str, Any]:
    """Chi tiết đơn kèm từng dòng hàng, để seller đối chiếu với khách.

    Giá và tên sản phẩm lấy từ chính order_items (ảnh chụp lúc bán), không tra
    lại bảng products - nên đơn cũ vẫn hiển thị đúng giá đã bán dù sau này
    sản phẩm có đổi giá hoặc bị xóa.
    """
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail=tr("Không tìm thấy đơn hàng"))
    if current_user.role != "ADMIN":
        require_shop_access(db, order.shop_id, current_user)
    require_staff_permission(current_user, PERMISSION_SALE)

    shop = db.query(models.Shop).filter(models.Shop.id == order.shop_id).first()
    cashier_username = None
    if order.created_by_user_id is not None:
        cashier_username = (
            db.query(models.User.username)
            .filter(models.User.id == order.created_by_user_id)
            .scalar()
        )
    items = (
        db.query(models.OrderItem)
        .filter(models.OrderItem.order_id == order_id)
        .order_by(models.OrderItem.id)
        .all()
    )

    customer = None
    if order.customer_id is not None:
        kh = db.query(models.Customer).filter(models.Customer.id == order.customer_id).first()
        if kh:
            customer = {"id": kh.id, "name": kh.name, "phone": kh.phone}

    result = {
        "id": order.id,
        "shop_id": order.shop_id,
        "shop_name": shop.name if shop else None,
        "status": order.status,
        "created_at": order.created_at,
        "created_by_user_id": order.created_by_user_id,
        "cashier_username": cashier_username,
        "shift_id": order.shift_id,
        "payment_method": order.payment_method,
        "cash_tendered_amount": order.cash_tendered_amount,
        "cash_change_amount": order.cash_change_amount,
        "voucher_code": order.voucher_code,
        "discount_amount": order.discount_amount or 0,
        "total_amount": order.total_amount,
        "customer": customer,
        "subtotal": sum((i.price or 0) * (i.quantity or 0) for i in items),
        "items": [
            {
                # `id` của dòng đơn: phiếu trả hàng định danh theo dòng chứ
                # không theo sản phẩm, vì dòng mới là nơi giữ giá bán và giá vốn
                # đã chốt lúc bán.
                "id": i.id,
                "product_id": i.product_id,
                "product_name": i.product_name,
                "price": i.price,
                "quantity": i.quantity,
                "line_total": (i.price or 0) * (i.quantity or 0),
            }
            for i in items
        ],
        "payments": [
            _serialize_payment(p)
            for p in (
                db.query(models.OrderPayment)
                .filter(models.OrderPayment.order_id == order_id)
                .order_by(models.OrderPayment.created_at, models.OrderPayment.id)
                .all()
            )
        ],
    }
    result.update(payment_summary(order))
    return result


def cancel_order(db: Session, current_user: models.User, order_id: int) -> Dict[str, Any]:
    """Hủy đơn PENDING và hoàn lại tồn kho + lượt voucher.

    Toàn bộ nằm trong MỘT transaction: chuyển trạng thái, hoàn kho và hoàn
    lượt voucher cùng thành công hoặc cùng không xảy ra. Chỉ lời gọi thắng
    được UPDATE có điều kiện mới chạy phần hoàn - nên hủy hai lần (hoặc hủy
    đua với webhook) không bao giờ hoàn kho hai lần.

    Đơn đã CANCELLED: trả 200 im lặng (bấm trùng).
    Đơn PAID / UNRECONCILED: từ chối 409 - tiền đã về, phải đối soát chứ
    không được hủy để hoàn kho.
    """
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail=tr("Không tìm thấy đơn hàng"))
    # Dữ liệu legacy có thể còn đơn hàng sau khi shop đã bị xóa. Admin vẫn cần
    # hủy được các đơn mồ côi này để giải phóng tồn kho; seller không được phép
    # đi vòng qua kiểm tra quyền sở hữu shop.
    if current_user.role != "ADMIN":
        require_shop_access(db, order.shop_id, current_user)
    require_staff_permission(current_user, PERMISSION_SALE)

    if order.status == STATUS_CANCELLED:
        return _ket_qua_huy(order_id, restored=0, unrestored=0, voucher_released=False)

    # Đơn ghi nợ đã thu được một phần thì KHÔNG hủy được: hủy sẽ hoàn tồn kho
    # cho số hàng khách đã cầm về, và biến khoản tiền đã thu thành tiền vô chủ -
    # nằm trong két nhưng không thuộc đơn nào. Trả lại tiền cho khách trước, rồi
    # mới xử lý đơn.
    if order.status == STATUS_DEBT:
        da_thu = _so_tien(order.paid_amount) + _so_tien(order.cash_paid_amount)
        if da_thu > MONEY_EPSILON:
            raise HTTPException(
                status_code=409,
                detail=tr(
                    "Đơn nợ này đã thu {amount}; không hủy được. "
                    "Hoàn tiền cho khách trước rồi mới xử lý đơn.",
                    amount=f"{da_thu:,.0f}đ",
                ),
            )

    # Giữ lại trước khi commit vì commit sẽ expire ORM object.
    shop_id = order.shop_id
    voucher_code = order.voucher_code
    discount_amount = order.discount_amount

    if not apply_transition(db, order_id, CANCEL_FROM, STATUS_CANCELLED):
        db.rollback()
        current = read_status(db, order_id)
        if current == STATUS_CANCELLED:
            return _ket_qua_huy(order_id, restored=0, unrestored=0, voucher_released=False)
        raise HTTPException(
            status_code=409,
            detail=tr(
                "Không thể hủy đơn ở trạng thái {status}",
                status=current,
            ),
        )

    restored, unrestored, voucher_released = _hoan_lai(
        db, order_id, shop_id, voucher_code, discount_amount
    )
    log_system_action(
        db,
        current_user.id,
        "CANCEL_ORDER",
        _mo_ta_huy(order_id, restored, unrestored, voucher_code, voucher_released),
    )
    return _ket_qua_huy(order_id, restored, unrestored, voucher_released)


def _hoan_lai(
    db: Session,
    order_id: int,
    shop_id: int,
    voucher_code: Optional[str],
    discount_amount: Optional[float],
) -> Tuple[int, int, bool]:
    """Hoàn kho + trả lượt voucher rồi commit. Chỉ gọi sau khi apply_transition thắng."""
    restored, unrestored = inventory_service.restore_stock(db, order_id)
    voucher_released = voucher_service.release_usage(
        db, shop_id, voucher_code, discount_amount
    )
    db.commit()
    return restored, unrestored, voucher_released


def _mo_ta_huy(
    order_id: int,
    restored: int,
    unrestored: int,
    voucher_code: Optional[str],
    voucher_released: bool,
) -> str:
    chi_tiet = f"Hủy đơn #{order_id} - hoàn kho {restored} dòng"
    if unrestored:
        chi_tiet += f", KHÔNG hoàn được {unrestored} dòng (thiếu product_id hoặc SP đã xóa)"
    if voucher_released:
        chi_tiet += f", trả lại 1 lượt voucher '{voucher_code}'"
    return chi_tiet


def cancel_expired_order(db: Session, order: models.Order) -> bool:
    """Hủy một đơn PENDING quá hạn do hệ thống tự động (không có người dùng).

    Dùng chung đúng cơ chế với hủy thủ công: UPDATE có điều kiện thắng thì mới
    hoàn kho, nên job chạy trùng lúc khách vừa thanh toán sẽ thua và không
    hoàn kho cho đơn đã PAID.
    """
    order_id = order.id
    shop_id = order.shop_id
    voucher_code = order.voucher_code
    discount_amount = order.discount_amount

    if not apply_transition(db, order_id, CANCEL_FROM, STATUS_CANCELLED):
        db.rollback()
        return False

    restored, unrestored, voucher_released = _hoan_lai(
        db, order_id, shop_id, voucher_code, discount_amount
    )
    log_system_action(
        db,
        None,  # hệ thống, không phải người dùng
        "AUTO_CANCEL_ORDER",
        "Tự động "
        + _mo_ta_huy(order_id, restored, unrestored, voucher_code, voucher_released)
        + " (quá hạn thanh toán)",
    )
    return True


def _ket_qua_huy(
    order_id: int, restored: int, unrestored: int, voucher_released: bool
) -> Dict[str, Any]:
    return {
        "msg": "Cancelled successfully",
        "order_id": order_id,
        "restored_items": restored,
        "unrestored_items": unrestored,
        "voucher_released": voucher_released,
    }


def apply_webhook_payment(db: Session, request_data: Dict[str, Any]) -> Dict[str, List[int]]:
    """Cộng dồn mọi giao dịch ngân hàng hợp lệ, idempotent theo từng giao dịch.

    Mỗi ledger row, tổng tiền, trạng thái và audit được commit cùng một
    transaction. Gửi lại cùng giao dịch chỉ trả lại trạng thái hiện tại; không
    cộng tiền, không ghi log và không làm frontend phát tiếng lần nữa.
    """
    transactions = payment_service.extract_transactions(request_data)
    if not transactions:
        raise HTTPException(
            status_code=400,
            detail=tr(
                "Không tìm thấy mã đơn hàng ORDERxxx trong thông tin thanh toán"
            ),
        )

    paid: set[int] = set()
    unreconciled: set[int] = set()
    rejected: set[int] = set()
    found_any = False

    # Không gộp theo order_id: một payload Casso có thể chứa 40k + 60k cho cùng
    # đơn, và cả hai khoản đều phải được ghi nhận.
    for gd in transactions:
        order = db.query(models.Order).filter(models.Order.id == gd.order_id).first()
        if order is None:
            continue
        found_any = True

        if gd.direction == "out":
            _ghi_tu_choi(
                db, gd.order_id, "giao dịch là tiền RA, không phải tiền vào"
            )
            rejected.add(gd.order_id)
            continue
        if gd.amount is None:
            _ghi_tu_choi(
                db,
                gd.order_id,
                "payload không có số tiền nên không xác nhận được đã thu đủ",
            )
            rejected.add(gd.order_id)
            continue
        amount = float(gd.amount)
        if not math.isfinite(amount) or amount <= 0:
            _ghi_tu_choi(
                db,
                gd.order_id,
                "số tiền giao dịch phải lớn hơn 0 (khác với payload thiếu số tiền)",
            )
            rejected.add(gd.order_id)
            continue

        result = _apply_bank_transaction(db, order, gd, amount)
        if result == "paid":
            paid.add(gd.order_id)
            unreconciled.discard(gd.order_id)
        elif result == "unreconciled":
            if gd.order_id not in paid:
                unreconciled.add(gd.order_id)
        else:
            rejected.add(gd.order_id)

    if not found_any:
        raise HTTPException(
            status_code=404,
            detail=tr("Không tìm thấy đơn hàng tương ứng"),
        )
    return {
        "paid": sorted(paid),
        "unreconciled": sorted(unreconciled),
        "rejected": sorted(rejected),
    }


def _bank_idempotency_key(gd: Any, fallback_account: Optional[str] = None) -> str:
    """Khóa retry riêng; không biến bank_txn_id thành ràng buộc unique."""
    provider = str(gd.provider or "unknown").strip().lower()
    account = "".join(
        c
        for c in str(gd.account_no or fallback_account or "unknown").strip().upper()
        if c.isalnum()
    )
    account = account.lstrip("0") or "0"
    if gd.txn_id and str(gd.txn_id).strip():
        raw = f"txn|{provider}|{account}|{str(gd.txn_id).strip()}"
    else:
        # fingerprint là hash canonical của đúng mục giao dịch từ provider.
        raw = (
            f"payload|{provider}|{account}|"
            + str(gd.payload_fingerprint or "")
        )
    return "bank:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _classify_existing(order: models.Order) -> str:
    if order.status == STATUS_PAID:
        return "paid"
    if order.status in (STATUS_UNRECONCILED, STATUS_CANCELLED):
        return "unreconciled"
    return "rejected"


def _same_payment(existing: models.OrderPayment, order_id: int, gd: Any, amount: float) -> bool:
    if existing.order_id != order_id:
        return False
    if abs(_so_tien(existing.amount) - amount) > MONEY_EPSILON:
        return False
    if existing.bank_txn_id and gd.txn_id:
        return existing.bank_txn_id == str(gd.txn_id)
    return True


def _duplicate_or_collision(
    db: Session,
    order: models.Order,
    gd: Any,
    amount: float,
    existing: models.OrderPayment,
) -> str:
    if _same_payment(existing, order.id, gd, amount):
        return _classify_existing(order)
    _them_nhat_ky(
        db,
        None,
        "WEBHOOK_XUNG_DOT_IDEMPOTENCY",
        f"Order {order.id}: khóa giao dịch đã tồn tại nhưng payload mới không khớp; "
        "đã từ chối để tránh cộng sai tiền",
    )
    db.commit()
    return "rejected"


def _apply_bank_transaction(
    db: Session, order: models.Order, gd: Any, amount: float
) -> str:
    """Ghi một giao dịch vào ledger rồi suy ra trạng thái từ tổng lũy kế."""
    order_id = order.id
    configured_account = (
        db.query(models.Shop.bank_account_no)
        .filter(models.Shop.id == order.shop_id)
        .scalar()
    )
    key = _bank_idempotency_key(gd, configured_account)
    # Cùng mã thô trên CÙNG đơn vẫn là retry kể cả provider lúc retry làm rơi
    # mất account/provider. Cột này non-unique ở DB; đây chỉ là lớp tương thích.
    if gd.txn_id:
        existing_raw = (
            db.query(models.OrderPayment)
            .filter(
                models.OrderPayment.order_id == order_id,
                models.OrderPayment.bank_txn_id == str(gd.txn_id),
                models.OrderPayment.entry_type == ENTRY_BANK,
            )
            .order_by(models.OrderPayment.id)
            .first()
        )
        if existing_raw:
            return _duplicate_or_collision(db, order, gd, amount, existing_raw)

    existing = (
        db.query(models.OrderPayment)
        .filter(models.OrderPayment.idempotency_key == key)
        .first()
    )
    if existing:
        return _duplicate_or_collision(db, order, gd, amount, existing)

    # Tương thích dữ liệu trước khi có ledger: retry đúng mã giao dịch đã lưu
    # trên orders không được biến thành một khoản tiền mới.
    if (
        gd.txn_id
        and order.bank_txn_id
        and str(gd.txn_id) == order.bank_txn_id
        and order.paid_amount is not None
        and order.status != STATUS_PENDING
    ):
        return _classify_existing(order)

    payment = models.OrderPayment(
        order_id=order_id,
        entry_type=ENTRY_BANK,
        amount=amount,
        idempotency_key=key,
        provider=str(gd.provider) if gd.provider else None,
        bank_txn_id=str(gd.txn_id) if gd.txn_id else None,
        account_no=str(gd.account_no) if gd.account_no else None,
    )
    db.add(payment)
    try:
        db.flush()
    except IntegrityError:
        # Hai webhook giống nhau có thể cùng vượt qua query phía trên; unique
        # index là hàng rào cuối. Rollback rồi phân loại như một retry.
        db.rollback()
        fresh_order = (
            db.query(models.Order).filter(models.Order.id == order_id).first()
        )
        existing = (
            db.query(models.OrderPayment)
            .filter(models.OrderPayment.idempotency_key == key)
            .first()
        )
        if fresh_order is not None and existing is not None:
            return _duplicate_or_collision(
                db, fresh_order, gd, amount, existing
            )
        raise

    # INSERT ledger đã lấy write lock của SQLite. Phải đọc lại trạng thái SAU
    # thời điểm này: cancel có thể đã thắng giữa SELECT đầu hàm và INSERT.
    db.expire(order)
    db.refresh(order)
    previous_status = order.status
    previous_reason = order.reconciliation_reason
    previous_txn = order.bank_txn_id

    # Cộng bằng SQL để hai giao dịch khác nhau không ghi đè tổng của nhau.
    db.execute(
        text(
            """
            UPDATE orders
            SET paid_amount = COALESCE(paid_amount, 0) + :amount,
                bank_txn_id = CASE
                    WHEN :txn IS NULL THEN bank_txn_id ELSE :txn END
            WHERE id = :order_id
            """
        ),
        {
            "amount": amount,
            "txn": str(gd.txn_id) if gd.txn_id else None,
            "order_id": order_id,
        },
    )
    db.expire(order)
    db.refresh(order)

    received = _so_tien(order.paid_amount) + _so_tien(order.cash_paid_amount)
    total = _so_tien(order.total_amount)
    refunded = _so_tien(order.refunded_amount)

    if previous_status == STATUS_CANCELLED or previous_reason == RECON_LATE_PAYMENT:
        order.status = STATUS_UNRECONCILED
        order.reconciliation_reason = RECON_LATE_PAYMENT
        order.refund_due_amount = max(received - refunded, 0)
        _reset_refund_completion(order)
        _them_nhat_ky(
            db,
            None,
            "WEBHOOK_UNRECONCILED",
            f"Order {order_id}: nhận thêm {amount:,.0f}đ sau khi đơn đã hủy; "
            f"tổng cần hoàn {order.refund_due_amount:,.0f}đ",
        )
        result = "unreconciled"
    elif previous_reason == RECON_LEGACY_REVIEW:
        # Không thể biết UNRECONCILED cũ do thiếu tiền hay do đơn từng hủy.
        # Ghi tiền nhưng tuyệt đối không tự hồi sinh.
        order.status = STATUS_UNRECONCILED
        order.reconciliation_reason = RECON_LEGACY_REVIEW
        _them_nhat_ky(
            db,
            None,
            "WEBHOOK_UNRECONCILED",
            f"Order {order_id}: nhận thêm {amount:,.0f}đ nhưng đơn đối soát cũ "
            "không đủ dữ liệu để tự kết luận",
        )
        result = "unreconciled"
    elif received < total - MONEY_EPSILON:
        order.status = STATUS_UNRECONCILED
        order.reconciliation_reason = RECON_UNDERPAID
        order.refund_due_amount = 0
        remaining = total - received
        _them_nhat_ky(
            db,
            None,
            "WEBHOOK_THIEU_TIEN",
            f"Order {order_id}: vừa nhận {amount:,.0f}đ, tổng đã nhận "
            f"{received:,.0f}đ nhưng cần {total:,.0f}đ "
            f"(thiếu {remaining:,.0f}đ) - cần đối soát",
        )
        result = "unreconciled"
    else:
        order.status = STATUS_PAID
        excess_due = max(received - total - refunded, 0)
        order.refund_due_amount = excess_due
        if excess_due > MONEY_EPSILON:
            order.reconciliation_reason = RECON_OVERPAID
            _reset_refund_completion(order)
        else:
            order.reconciliation_reason = None

        if previous_status == STATUS_PAID:
            _them_nhat_ky(
                db,
                None,
                "WEBHOOK_TRA_TRUNG",
                f"Order {order_id} đã thanh toán"
                + (f" bằng giao dịch {previous_txn}" if previous_txn else "")
                + f", nay nhận thêm giao dịch {gd.txn_id or '(không mã)'} "
                f"({amount:,.0f}đ) - cần hoàn {excess_due:,.0f}đ",
            )
        else:
            detail = (
                f"Order {order_id} marked PAID via webhook "
                f"(tổng nhận {received:,.0f}đ)"
            )
            if excess_due > MONEY_EPSILON:
                detail += f", khách chuyển DƯ {excess_due:,.0f}đ - cần trả lại"
            _them_nhat_ky(db, None, "WEBHOOK_PAYMENT", detail)
        result = "paid"

    _add_account_warning(db, order, gd)
    db.commit()
    return result


def _reset_refund_completion(order: models.Order) -> None:
    """Một khoản dư mới mở chu kỳ hoàn mới; lịch sử cũ vẫn còn trong ledger."""
    order.refund_completed_at = None
    order.refund_completed_by = None
    order.refund_method = None
    order.refund_note = None
    order.refund_reference = None


def _ghi_tu_choi(db: Session, order_id: int, ly_do: str) -> None:
    log_system_action(db, None, "WEBHOOK_TU_CHOI", f"Order {order_id}: {ly_do}")


def _add_account_warning(
    db: Session, order: models.Order, gd: Any
) -> None:
    """Sai tài khoản chỉ cảnh báo trong cùng transaction, không chặn tiền."""
    if not gd.account_no:
        return
    shop = db.query(models.Shop).filter(models.Shop.id == order.shop_id).first()
    shop_account = (shop.bank_account_no or "") if shop else ""
    if not shop_account:
        return
    if str(gd.account_no).lstrip("0") != shop_account.lstrip("0"):
        _them_nhat_ky(
            db,
            None,
            "WEBHOOK_KHAC_TAI_KHOAN",
            f"Order {order.id}: tiền vào tài khoản {gd.account_no} nhưng shop khai "
            f"{shop_account} - kiểm tra lại cấu hình",
        )
