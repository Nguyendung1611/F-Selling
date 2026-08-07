from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import models
from ..dependencies import get_current_user, get_db, require_shop_access
from ..schemas.order import (
    CashPayment,
    CashTopup,
    DebtPayment,
    OfflineOrderCreate,
    OrderCreate,
    OrderReturnCreate,
    RefundComplete,
)
from ..services import offline_service, order_service, return_service, subscription_service

router = APIRouter(prefix="/api/orders", tags=["orders"])


@router.post("/{shop_id}")
def create_order(
    shop_id: int,
    order: OrderCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    # Free vẫn bán tiền mặt/VietQR bằng tài khoản chủ shop. Nhân viên là tính
    # năng Pro; bán ghi nợ cũng là nghiệp vụ Pro. Chỉ chặn lúc TẠO đơn mới —
    # các endpoint thu nợ/hoàn tiền/trả hàng/đồng bộ offline phía dưới luôn mở
    # để giải quyết tiền đã phát sinh.
    require_shop_access(db, shop_id, current_user)
    if current_user.role == "STAFF" or order.payment_method == "debt":
        subscription_service.require_pro(db, shop_id)
    return order_service.create_order(db, current_user, shop_id, order)


@router.post("/{shop_id}/offline")
def dong_bo_don_offline(
    shop_id: int,
    phieu: OfflineOrderCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Nhận một phiếu đã bán khi mất mạng.

    Gọi lại cùng `offline_uuid` trả về đúng đơn cũ với `created: false` — máy
    bán mất sóng giữa lúc gửi cứ gửi lại thoải mái, không sinh đơn thứ hai.
    """
    return offline_service.dong_bo_phieu(db, current_user, shop_id, phieu)


@router.get("/{shop_id}/offline-issues")
def don_offline_can_xu_ly(
    shop_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Đơn offline có vướng mắc (tồn âm, ca đã chốt, sản phẩm đã xóa...)."""
    require_shop_access(db, shop_id, current_user)
    return offline_service.danh_sach_can_xu_ly(db, shop_id)


@router.get("/{order_id}")
def get_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return order_service.get_order(db, current_user, order_id)


@router.get("/{order_id}/detail")
def get_order_detail(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    chi_tiet = order_service.get_order_detail(db, current_user, order_id)
    return return_service.bo_sung_thong_tin_tra_hang(db, chi_tiet)


@router.post("/{order_id}/debt-payment")
def debt_payment(
    order_id: int,
    payload: DebtPayment,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return order_service.debt_payment(db, current_user, order_id, payload)


@router.post("/{order_id}/returns")
def create_order_return(
    order_id: int,
    payload: OrderReturnCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return return_service.create_return(db, current_user, order_id, payload)


@router.post("/{order_id}/pay")
def pay_order(
    order_id: int,
    request: CashPayment | None = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return order_service.pay_order(db, current_user, order_id, request)


@router.post("/{order_id}/cash-topup")
def cash_topup(
    order_id: int,
    request: CashTopup,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return order_service.cash_topup(db, current_user, order_id, request)


@router.post("/{order_id}/refund-complete")
def refund_complete(
    order_id: int,
    request: RefundComplete,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return order_service.complete_refund(db, current_user, order_id, request)


@router.post("/{order_id}/cancel")
def cancel_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return order_service.cancel_order(db, current_user, order_id)
