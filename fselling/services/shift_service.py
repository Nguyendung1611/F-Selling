"""Nghiệp vụ ca thu ngân và thu/chi tiền mặt thủ công.

Mọi số liệu được lưu ở SQLite phía server. Một ca thuộc về người mở, không phụ
thuộc browser, thiết bị hay máy in. Bảng CashMovement chỉ chứa PAY_IN/PAY_OUT;
tiền của đơn được cộng từ OrderPayment.shift_id để không đếm hai lần.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import HTTPException
from sqlalchemy import case, func, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models
from ..dependencies import (
    PERMISSION_SALE,
    STAFF_ROLE_MANAGER,
    effective_staff_role,
    require_shop_access,
    require_staff_permission,
)
from ..schemas.shift import CashMovementCreate, ShiftClose, ShiftOpen

STATUS_OPEN = "OPEN"
STATUS_CLOSED = "CLOSED"

MOVEMENT_PAY_IN = "PAY_IN"
MOVEMENT_PAY_OUT = "PAY_OUT"
DIRECTION_IN = "IN"
DIRECTION_OUT = "OUT"

# order_service hiện dùng CASH_TOPUP cho cả lần thu tiền mặt đủ của đơn và lần
# bù thiếu. Giữ thêm hai tên tường minh để ledger vẫn đúng khi tách loại sau.
CASH_PAYMENT_IN_TYPES = ("CASH_TOPUP", "CASH_IN", "SALE_CASH")
CASH_PAYMENT_OUT_TYPES = ("REFUND_CASH",)

MONEY_EPSILON = 0.001
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


def _note(value: Optional[str], *, required: bool = False) -> Optional[str]:
    cleaned = (value or "").strip()[:500]
    if required and not cleaned:
        raise HTTPException(status_code=400, detail="Vui lòng nhập lý do thu/chi")
    return cleaned or None


def _add_audit(
    db: Session, user_id: int, action: str, details: str
) -> None:
    """Thêm log vào transaction hiện tại, không gọi log_system_action()."""
    db.add(
        models.SystemLog(
            user_id=user_id,
            action=action,
            details=details,
        )
    )


def _is_manager(shop: models.Shop, current_user: models.User) -> bool:
    return (
        current_user.role == "ADMIN"
        or shop.owner_id == current_user.id
        or (
            current_user.role == "STAFF"
            and effective_staff_role(current_user) == STAFF_ROLE_MANAGER
        )
    )


def _get_shift(db: Session, shift_id: int) -> models.CashShift:
    shift = (
        db.query(models.CashShift)
        .filter(models.CashShift.id == shift_id)
        .first()
    )
    if not shift:
        raise HTTPException(status_code=404, detail="Không tìm thấy ca làm việc")
    return shift


def _authorize_shift(
    db: Session,
    shift: models.CashShift,
    current_user: models.User,
    *,
    allow_manager: bool = True,
) -> models.Shop:
    shop = require_shop_access(db, shift.shop_id, current_user)
    require_staff_permission(current_user, PERMISSION_SALE)
    if shift.opened_by_user_id == current_user.id:
        return shop
    if allow_manager and _is_manager(shop, current_user):
        return shop
    raise HTTPException(status_code=403, detail="Bạn không có quyền thao tác ca này")


def _cash_totals(db: Session, shift_id: int) -> Dict[str, float]:
    """Tổng hợp tiền theo đúng nguồn, không dựa vào trạng thái trên client."""
    pay_in, pay_out = (
        db.query(
            func.coalesce(
                func.sum(
                    case(
                        (
                            models.CashMovement.direction == DIRECTION_IN,
                            models.CashMovement.amount,
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (
                            models.CashMovement.direction == DIRECTION_OUT,
                            models.CashMovement.amount,
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
        )
        .filter(models.CashMovement.shift_id == shift_id)
        .one()
    )

    cash_in, cash_refund = (
        db.query(
            func.coalesce(
                func.sum(
                    case(
                        (
                            models.OrderPayment.entry_type.in_(
                                CASH_PAYMENT_IN_TYPES
                            ),
                            models.OrderPayment.amount,
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (
                            models.OrderPayment.entry_type.in_(
                                CASH_PAYMENT_OUT_TYPES
                            ),
                            models.OrderPayment.amount,
                        ),
                        else_=0,
                    )
                ),
                0,
            ),
        )
        .filter(models.OrderPayment.shift_id == shift_id)
        .one()
    )
    return {
        "cash_payment_in_amount": float(cash_in or 0),
        "cash_refund_amount": float(cash_refund or 0),
        "pay_in_amount": float(pay_in or 0),
        "pay_out_amount": float(pay_out or 0),
    }


def _expected_cash(
    shift: models.CashShift, totals: Dict[str, float]
) -> float:
    return (
        float(shift.opening_cash_amount or 0)
        + totals["cash_payment_in_amount"]
        + totals["pay_in_amount"]
        - totals["cash_refund_amount"]
        - totals["pay_out_amount"]
    )


def _serialize_shift(db: Session, shift: models.CashShift) -> Dict[str, Any]:
    totals = _cash_totals(db, shift.id)
    calculated_expected = _expected_cash(shift, totals)
    # Khi đã đóng, giữ snapshot bất biến tại thời điểm chốt. Với ca đang mở,
    # expected được tính trực tiếp từ hai ledger durable.
    expected = (
        float(shift.expected_cash_amount)
        if shift.status == STATUS_CLOSED and shift.expected_cash_amount is not None
        else calculated_expected
    )
    result = {
        "id": shift.id,
        "shop_id": shift.shop_id,
        "status": shift.status,
        "opened_by_user_id": shift.opened_by_user_id,
        "opened_by_username": shift.opened_by.username if shift.opened_by else None,
        "opened_at": shift.opened_at,
        "opening_cash_amount": float(shift.opening_cash_amount or 0),
        "opening_note": shift.opening_note,
        "closed_by_user_id": shift.closed_by_user_id,
        "closed_by_username": shift.closed_by.username if shift.closed_by else None,
        "closed_at": shift.closed_at,
        "counted_cash_amount": shift.counted_cash_amount,
        "expected_cash_amount": expected,
        "variance_amount": shift.variance_amount,
        "closing_note": shift.closing_note,
    }
    result.update(totals)
    return result


def _serialize_movement(movement: models.CashMovement) -> Dict[str, Any]:
    return {
        "id": movement.id,
        "shift_id": movement.shift_id,
        "order_id": movement.order_id,
        "movement_type": movement.movement_type,
        "direction": movement.direction,
        "amount": movement.amount,
        "operation_id": movement.operation_id,
        "note": movement.note,
        "created_by_user_id": movement.created_by_user_id,
        "created_at": movement.created_at,
    }


def _lock_open_shift(db: Session, shift_id: int) -> bool:
    """Lấy write lock SQLite và đồng thời xác nhận ca vẫn OPEN.

    No-op UPDATE là có chủ ý: SQLite không có SELECT FOR UPDATE. Cùng transaction
    này sẽ giữ quyền ghi cho tới commit, nên đóng ca và thêm chuyển động tiền
    không thể lách qua nhau.
    """
    result = db.execute(
        text(
            "UPDATE cash_shifts SET status = status "
            "WHERE id = :shift_id AND status = :open_status"
        ),
        {"shift_id": shift_id, "open_status": STATUS_OPEN},
    )
    return result.rowcount == 1


def get_current_shift(
    db: Session, current_user: models.User, shop_id: int
) -> Dict[str, Any]:
    require_shop_access(db, shop_id, current_user)
    require_staff_permission(current_user, PERMISSION_SALE)
    shift = (
        db.query(models.CashShift)
        .filter(
            models.CashShift.shop_id == shop_id,
            models.CashShift.opened_by_user_id == current_user.id,
            models.CashShift.status == STATUS_OPEN,
        )
        .first()
    )
    return {"shift": _serialize_shift(db, shift) if shift else None}


def open_shift(
    db: Session,
    current_user: models.User,
    shop_id: int,
    request: ShiftOpen,
) -> Dict[str, Any]:
    require_shop_access(db, shop_id, current_user)
    require_staff_permission(current_user, PERMISSION_SALE)
    opening_amount = float(request.opening_cash_amount)
    if not math.isfinite(opening_amount) or opening_amount < 0:
        raise HTTPException(status_code=400, detail="Tiền đầu ca không hợp lệ")

    existing = (
        db.query(models.CashShift)
        .filter(
            models.CashShift.shop_id == shop_id,
            models.CashShift.opened_by_user_id == current_user.id,
            models.CashShift.status == STATUS_OPEN,
        )
        .first()
    )
    # Retry/double-click trả lại đúng ca đã mở, không sinh ca thứ hai.
    if existing:
        return _serialize_shift(db, existing)

    shift = models.CashShift(
        shop_id=shop_id,
        status=STATUS_OPEN,
        opening_cash_amount=opening_amount,
        opening_note=_note(request.note),
        opened_by_user_id=current_user.id,
    )
    db.add(shift)
    try:
        db.flush()
        _add_audit(
            db,
            current_user.id,
            "OPEN_CASH_SHIFT",
            f"Mở ca #{shift.id} tại shop #{shop_id}, tiền đầu ca {opening_amount:,.0f}đ",
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        # Unique partial index giải quyết hai request mở ca chạy đồng thời.
        existing = (
            db.query(models.CashShift)
            .filter(
                models.CashShift.shop_id == shop_id,
                models.CashShift.opened_by_user_id == current_user.id,
                models.CashShift.status == STATUS_OPEN,
            )
            .first()
        )
        if existing:
            return _serialize_shift(db, existing)
        raise

    db.refresh(shift)
    return _serialize_shift(db, shift)


def list_shift_history(
    db: Session,
    current_user: models.User,
    shop_id: int,
    page: int = 1,
    per_page: int = DEFAULT_PAGE_SIZE,
) -> Dict[str, Any]:
    shop = require_shop_access(db, shop_id, current_user)
    require_staff_permission(current_user, PERMISSION_SALE)
    if page < 1:
        raise HTTPException(status_code=400, detail="page phải >= 1")
    if per_page < 1 or per_page > MAX_PAGE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"per_page phải từ 1 đến {MAX_PAGE_SIZE}",
        )

    query = db.query(models.CashShift).filter(models.CashShift.shop_id == shop_id)
    # Nhân viên chỉ xem lịch sử của mình; chủ shop/admin xem được mọi thu ngân.
    if not _is_manager(shop, current_user):
        query = query.filter(models.CashShift.opened_by_user_id == current_user.id)

    total = query.count()
    shifts = (
        query.order_by(models.CashShift.opened_at.desc(), models.CashShift.id.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    return {
        "items": [_serialize_shift(db, shift) for shift in shifts],
        "page": page,
        "per_page": per_page,
        "total": total,
        "has_more": page * per_page < total,
    }


def get_shift_detail(
    db: Session, current_user: models.User, shift_id: int
) -> Dict[str, Any]:
    shift = _get_shift(db, shift_id)
    _authorize_shift(db, shift, current_user)
    result = _serialize_shift(db, shift)
    movements = (
        db.query(models.CashMovement)
        .filter(models.CashMovement.shift_id == shift_id)
        .order_by(models.CashMovement.created_at, models.CashMovement.id)
        .all()
    )
    result["movements"] = [_serialize_movement(m) for m in movements]
    return result


def _same_movement(
    movement: models.CashMovement,
    shift_id: int,
    movement_type: str,
    amount: float,
    note: str,
) -> bool:
    return (
        movement.shift_id == shift_id
        and movement.movement_type == movement_type
        and abs(float(movement.amount) - amount) <= MONEY_EPSILON
        and movement.note == note
    )


def create_movement(
    db: Session,
    current_user: models.User,
    shift_id: int,
    request: CashMovementCreate,
) -> Dict[str, Any]:
    shift = _get_shift(db, shift_id)
    _authorize_shift(db, shift, current_user)

    amount = float(request.amount)
    if not math.isfinite(amount) or amount <= MONEY_EPSILON:
        raise HTTPException(status_code=400, detail="Số tiền thu/chi phải lớn hơn 0")
    note = _note(request.note, required=True)
    assert note is not None
    operation_id = request.operation_id.strip()
    if len(operation_id) < 8:
        raise HTTPException(status_code=400, detail="Mã thao tác không hợp lệ")

    existing = (
        db.query(models.CashMovement)
        .filter(models.CashMovement.operation_id == operation_id)
        .first()
    )
    if existing:
        if not _same_movement(
            existing, shift_id, request.movement_type, amount, note
        ):
            raise HTTPException(
                status_code=409,
                detail="Mã thao tác đã được dùng cho một khoản thu/chi khác",
            )
        return {
            "movement": _serialize_movement(existing),
            "shift": _serialize_shift(db, shift),
        }

    if not _lock_open_shift(db, shift_id):
        db.rollback()
        raise HTTPException(status_code=409, detail="Ca làm việc đã đóng")

    direction = (
        DIRECTION_IN
        if request.movement_type == MOVEMENT_PAY_IN
        else DIRECTION_OUT
    )
    if direction == DIRECTION_OUT:
        totals = _cash_totals(db, shift_id)
        expected = _expected_cash(shift, totals)
        if amount > expected + MONEY_EPSILON:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail=f"Tiền chi không được vượt tiền dự kiến trong ca ({expected:,.0f}đ)",
            )

    movement = models.CashMovement(
        shift_id=shift_id,
        movement_type=request.movement_type,
        direction=direction,
        amount=amount,
        operation_id=operation_id,
        note=note,
        created_by_user_id=current_user.id,
    )
    db.add(movement)
    try:
        db.flush()
        _add_audit(
            db,
            current_user.id,
            f"CASH_{request.movement_type}",
            f"Ca #{shift_id}: {request.movement_type} {amount:,.0f}đ - {note}",
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        concurrent = (
            db.query(models.CashMovement)
            .filter(models.CashMovement.operation_id == operation_id)
            .first()
        )
        if concurrent and _same_movement(
            concurrent, shift_id, request.movement_type, amount, note
        ):
            return {
                "movement": _serialize_movement(concurrent),
                "shift": _serialize_shift(db, _get_shift(db, shift_id)),
            }
        raise HTTPException(
            status_code=409,
            detail="Mã thao tác đã được dùng cho một khoản thu/chi khác",
        )

    db.refresh(movement)
    db.refresh(shift)
    return {
        "movement": _serialize_movement(movement),
        "shift": _serialize_shift(db, shift),
    }


def close_shift(
    db: Session,
    current_user: models.User,
    shift_id: int,
    request: ShiftClose,
) -> Dict[str, Any]:
    shift = _get_shift(db, shift_id)
    _authorize_shift(db, shift, current_user)
    if shift.status == STATUS_CLOSED:
        return _serialize_shift(db, shift)

    counted = float(request.counted_cash_amount)
    if not math.isfinite(counted) or counted < 0:
        raise HTTPException(status_code=400, detail="Tiền thực đếm không hợp lệ")

    if not _lock_open_shift(db, shift_id):
        db.rollback()
        refreshed = _get_shift(db, shift_id)
        if refreshed.status == STATUS_CLOSED:
            return _serialize_shift(db, refreshed)
        raise HTTPException(status_code=409, detail="Không thể đóng ca ở trạng thái hiện tại")

    # Không chốt khi còn đơn tiền mặt chưa xác nhận: nếu đóng trước rồi mới thu,
    # khoản tiền sẽ không thuộc một ca OPEN nào.
    pending_cash_orders = (
        db.query(models.Order)
        .filter(
            models.Order.shift_id == shift_id,
            models.Order.payment_method == "cash",
            models.Order.status == "PENDING",
        )
        .count()
    )
    if pending_cash_orders:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=(
                f"Ca còn {pending_cash_orders} đơn tiền mặt chưa thanh toán; "
                "hãy thanh toán hoặc hủy trước khi đóng ca"
            ),
        )

    totals = _cash_totals(db, shift_id)
    expected = _expected_cash(shift, totals)
    variance = counted - expected
    closing_note = _note(request.note)
    if abs(variance) > MONEY_EPSILON and closing_note is None:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Ca lệch tiền; vui lòng nhập ghi chú giải trình",
        )
    closed_at = datetime.utcnow()
    shift.status = STATUS_CLOSED
    shift.counted_cash_amount = counted
    shift.expected_cash_amount = expected
    shift.variance_amount = variance
    shift.closing_note = closing_note
    shift.closed_by_user_id = current_user.id
    shift.closed_at = closed_at
    _add_audit(
        db,
        current_user.id,
        "CLOSE_CASH_SHIFT",
        (
            f"Đóng ca #{shift_id}: dự kiến {expected:,.0f}đ, "
            f"thực đếm {counted:,.0f}đ, chênh lệch {variance:,.0f}đ"
        ),
    )
    db.commit()
    db.refresh(shift)
    return _serialize_shift(db, shift)
