"""Trả hàng: khách mang hàng đã mua quay lại, shop hoàn tiền.

Khác hẳn ba thứ dễ nhầm với nó:

- **Hủy đơn** (`order_service.cancel_order`) chỉ áp dụng cho đơn CHƯA thanh
  toán. Hàng chưa ra khỏi cửa, tiền chưa vào.
- **Hoàn khoản chuyển thừa** (`order_service.complete_refund`) là trả lại phần
  tiền khách chuyển dư, hàng vẫn thuộc về khách. Chỉ xảy ra một lần cho một đơn.
- **Trả hàng** là hàng quay về, tiền đi ra, và xảy ra được NHIỀU LẦN trên cùng
  một đơn (khách mua 5 món, hôm nay trả 1, tuần sau trả thêm 2).

Đơn giữ nguyên trạng thái `PAID`. Hóa đơn đã xuất là sự thật lịch sử; việc trả
là sự kiện xảy ra sau đó, nằm ở bảng `order_returns` chứ không xóa lần bán.
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models
from ..core.i18n import tr
from ..dependencies import (
    PERMISSION_SALE,
    require_shop_access,
    require_staff_permission,
)
from ..schemas.order import OrderReturnCreate
from . import order_service

ENTRY_RETURN_CASH = "RETURN_CASH"
ENTRY_RETURN_TRANSFER = "RETURN_TRANSFER"

MONEY_EPSILON = order_service.MONEY_EPSILON

_RESTOCK = text(
    "UPDATE products SET stock = stock + :quantity WHERE id = :product_id"
)


def _khoa_thao_tac(operation_id: str) -> str:
    """Khóa chống bấm lặp. Tiền tố `return:` tách hẳn khỏi `refund:` của chu kỳ
    hoàn tiền chuyển thừa, nên hai nghiệp vụ không bao giờ nhận nhầm thao tác
    của nhau kể cả khi client vô tình dùng lại cùng một operation_id."""
    ma = operation_id.strip()
    if len(ma) < 8:
        raise HTTPException(
            status_code=400,
            detail=tr("Mã thao tác trả hàng không hợp lệ"),
        )
    return "return:" + hashlib.sha256(ma.encode("utf-8")).hexdigest()


def _serialize_return(ban_ghi: models.OrderReturn) -> Dict[str, Any]:
    return {
        "id": ban_ghi.id,
        "order_id": ban_ghi.order_id,
        "refund_amount": ban_ghi.refund_amount,
        "refund_method": ban_ghi.refund_method,
        "reason": ban_ghi.reason,
        "note": ban_ghi.note,
        "reference": ban_ghi.reference,
        "created_by_user_id": ban_ghi.created_by_user_id,
        "shift_id": ban_ghi.shift_id,
        "created_at": ban_ghi.created_at,
        "items": [
            {
                "order_item_id": d.order_item_id,
                "product_id": d.product_id,
                "product_name": d.product_name,
                "quantity": d.quantity,
                "unit_price": d.unit_price,
                "refund_amount": d.refund_amount,
                "restocked": bool(d.restocked),
            }
            for d in ban_ghi.items
        ],
    }


def da_tra_theo_dong(db: Session, order_id: int) -> Dict[int, int]:
    """Số lượng đã trả của từng dòng đơn, gom từ mọi phiếu trả trước đó."""
    rows = (
        db.query(
            models.OrderReturnItem.order_item_id,
            models.OrderReturnItem.quantity,
        )
        .join(
            models.OrderReturn,
            models.OrderReturn.id == models.OrderReturnItem.return_id,
        )
        .filter(models.OrderReturn.order_id == order_id)
        .all()
    )
    ket_qua: Dict[int, int] = {}
    for order_item_id, quantity in rows:
        ket_qua[order_item_id] = ket_qua.get(order_item_id, 0) + int(quantity or 0)
    return ket_qua


def danh_sach_phieu_tra(db: Session, order_id: int) -> List[Dict[str, Any]]:
    ban_ghi = (
        db.query(models.OrderReturn)
        .filter(models.OrderReturn.order_id == order_id)
        .order_by(models.OrderReturn.id)
        .all()
    )
    return [_serialize_return(r) for r in ban_ghi]


def tong_da_hoan(db: Session, order_id: int) -> float:
    """Tổng tiền đã hoàn cho khách qua MỌI lần trả hàng của đơn."""
    return float(
        db.query(func.coalesce(func.sum(models.OrderReturn.refund_amount), 0))
        .filter(models.OrderReturn.order_id == order_id)
        .scalar()
        or 0
    )


def bo_sung_thong_tin_tra_hang(
    db: Session, chi_tiet: Dict[str, Any]
) -> Dict[str, Any]:
    """Gắn lịch sử trả hàng vào chi tiết đơn do `order_service` dựng.

    Router gọi hai service nối tiếp thay vì để `order_service` import ngược lên
    đây - giữ đúng một chiều phụ thuộc (return_service -> order_service) và
    không sinh vòng import.
    """
    order_id = chi_tiet["id"]
    da_tra = da_tra_theo_dong(db, order_id)
    for dong in chi_tiet.get("items", []):
        so_da_tra = da_tra.get(dong["id"], 0)
        dong["returned_quantity"] = so_da_tra
        dong["returnable_quantity"] = max(int(dong["quantity"] or 0) - so_da_tra, 0)
    chi_tiet["returns"] = danh_sach_phieu_tra(db, order_id)
    chi_tiet["returned_total"] = tong_da_hoan(db, order_id)
    return chi_tiet


def _kiem_yeu_cau(request: OrderReturnCreate) -> None:
    if not request.items:
        raise HTTPException(
            status_code=400,
            detail=tr("Chưa chọn dòng hàng nào để trả"),
        )
    ids = [it.order_item_id for it in request.items]
    if len(set(ids)) != len(ids):
        raise HTTPException(
            status_code=400,
            detail=tr("Một dòng hàng xuất hiện nhiều lần trong phiếu trả"),
        )
    for it in request.items:
        if it.quantity is None or it.quantity <= 0:
            raise HTTPException(
                status_code=400,
                detail=tr("Số lượng trả phải lớn hơn 0"),
            )


def _phieu_da_ghi(
    db: Session, operation_key: str, order_id: int
) -> Optional[models.OrderReturn]:
    """Phiếu trả đã tạo trước đó với đúng mã thao tác này.

    Cùng mã nhưng khác đơn là client đang dùng lại id cho một việc khác - đó là
    lỗi thật, không phải retry, nên phải nổ ra chứ không im lặng.
    """
    truoc = (
        db.query(models.OrderReturn)
        .filter(models.OrderReturn.idempotency_key == operation_key)
        .first()
    )
    if truoc is None:
        return None
    if truoc.order_id != order_id:
        raise HTTPException(
            status_code=409,
            detail=tr("Mã thao tác trả hàng đã được dùng cho một đơn khác"),
        )
    return truoc


def create_return(
    db: Session,
    current_user: models.User,
    order_id: int,
    request: OrderReturnCreate,
) -> Dict[str, Any]:
    """Nhận hàng khách trả, hoàn tiền và (tùy dòng) nhập lại kho."""
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail=tr("Không tìm thấy đơn hàng"))
    require_shop_access(db, order.shop_id, current_user)
    require_staff_permission(current_user, PERMISSION_SALE)

    _kiem_yeu_cau(request)
    operation_key = _khoa_thao_tac(request.operation_id)

    truoc = _phieu_da_ghi(db, operation_key, order_id)
    if truoc is not None:
        return _ket_qua(db, order, truoc, lap_lai=True)

    # Tuần tự hóa với mọi thao tác khác trên cùng shop: hai thu ngân cùng nhận
    # trả một dòng hàng phải nối đuôi nhau, nếu không cả hai đều thấy "còn trả
    # được 1" và cùng cho trả.
    order_service._lock_shop_for_order(db, order.shop_id)
    db.refresh(order)

    # Kiểm lại sau khi có lock: một request song song cùng mã có thể vừa xong.
    truoc = _phieu_da_ghi(db, operation_key, order_id)
    if truoc is not None:
        ket_qua = _ket_qua(db, order, truoc, lap_lai=True)
        db.rollback()
        return ket_qua

    if order.status != order_service.STATUS_PAID:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=tr(
                "Chỉ nhận trả hàng cho đơn đã thanh toán. Đơn chưa thanh toán "
                "thì hủy đơn, đơn đang đối soát thì xử lý đối soát trước."
            ),
        )

    dong_don = {
        it.id: it
        for it in db.query(models.OrderItem)
        .filter(models.OrderItem.order_id == order_id)
        .all()
    }
    da_tra = da_tra_theo_dong(db, order_id)

    tong_tien_hang = sum(
        float(it.price or 0) * int(it.quantity or 0) for it in dong_don.values()
    )
    tong_don = float(order.total_amount or 0)
    # Tỷ lệ thực thu trên giá niêm yết. Đơn có voucher thì < 1: hoàn theo giá
    # niêm yết là shop chịu trọn phần đã giảm cho món khách vẫn giữ.
    ty_le = (tong_don / tong_tien_hang) if tong_tien_hang > MONEY_EPSILON else 0.0

    chi_tiet: List[Dict[str, Any]] = []
    for it in request.items:
        dong = dong_don.get(it.order_item_id)
        if dong is None:
            db.rollback()
            raise HTTPException(
                status_code=400,
                detail=tr("Dòng hàng không thuộc đơn này"),
            )
        con_tra_duoc = int(dong.quantity or 0) - da_tra.get(dong.id, 0)
        if it.quantity > con_tra_duoc:
            db.rollback()
            raise HTTPException(
                status_code=400,
                detail=tr(
                    "'{name}' chỉ còn {remaining} có thể trả (đã bán "
                    "{sold}, đã trả {returned})",
                    name=dong.product_name,
                    remaining=con_tra_duoc,
                    sold=int(dong.quantity or 0),
                    returned=da_tra.get(dong.id, 0),
                ),
            )
        chi_tiet.append({
            "dong": dong,
            "quantity": it.quantity,
            "restock": bool(it.restock),
            "tien_hang": float(dong.price or 0) * it.quantity,
        })

    tien_hoan = _tinh_tien_hoan(db, order, dong_don, da_tra, chi_tiet, ty_le)

    if tien_hoan > MONEY_EPSILON and request.method is None:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail=tr("Phải chọn cách hoàn tiền cho khách"),
        )

    shift = None
    if tien_hoan > MONEY_EPSILON and request.method == "cash":
        # Tiền mặt ra khỏi két phải trừ đúng ca của người đang đứng quầy, nếu
        # không thì cuối ca đếm thiếu mà không ai biết vì sao.
        shift = order_service._current_cash_shift(
            db,
            current_user,
            order.shop_id,
            required_for_everyone=True,
            lock_for_cash_write=True,
        )

    phieu = models.OrderReturn(
        order_id=order_id,
        shop_id=order.shop_id,
        refund_amount=tien_hoan,
        refund_method=request.method if tien_hoan > MONEY_EPSILON else None,
        reason=(request.reason or "").strip()[:200] or None,
        note=(request.note or "").strip()[:500] or None,
        reference=(request.reference or "").strip()[:128] or None,
        created_by_user_id=current_user.id,
        shift_id=shift.id if shift else None,
        idempotency_key=operation_key,
        created_at=datetime.utcnow(),
    )
    db.add(phieu)
    try:
        db.flush()
    except IntegrityError:
        # Unique idempotency_key: một request song song cùng mã đã ghi trước.
        db.rollback()
        truoc = _phieu_da_ghi(db, operation_key, order_id)
        if truoc is not None:
            return _ket_qua(db, order, truoc, lap_lai=True)
        raise

    for d in chi_tiet:
        dong = d["dong"]
        db.add(
            models.OrderReturnItem(
                return_id=phieu.id,
                order_item_id=dong.id,
                product_id=dong.product_id,
                product_name=dong.product_name,
                quantity=d["quantity"],
                unit_price=float(dong.price or 0),
                refund_amount=d["tien_hoan"],
                # Ảnh chụp giá vốn đã chốt lúc bán, KHÔNG tra lại từ sản phẩm:
                # giá vốn hiện hành có thể đã đổi vì các lô nhập sau.
                cost_price=dong.cost_price,
                restocked=1 if d["restock"] else 0,
            )
        )
        if d["restock"] and dong.product_id is not None:
            # Cộng thẳng bằng UPDATE nguyên tử, và CỐ Ý không đụng cost_price:
            # số hàng này ra đi với đúng giá vốn đã chốt nên khi quay về, đơn
            # giá bình quân tự khớp lại. Chạy lại công thức bình quân ở đây mới
            # là cái làm lệch.
            db.execute(
                _RESTOCK,
                {"quantity": d["quantity"], "product_id": dong.product_id},
            )

    if tien_hoan > MONEY_EPSILON:
        db.add(
            models.OrderPayment(
                order_id=order_id,
                entry_type=(
                    ENTRY_RETURN_CASH
                    if request.method == "cash"
                    else ENTRY_RETURN_TRANSFER
                ),
                amount=tien_hoan,
                idempotency_key=operation_key,
                created_by_user_id=current_user.id,
                shift_id=shift.id if shift else None,
                note=phieu.note,
                reference=phieu.reference,
            )
        )

    mo_ta = (
        f"Order {order_id}: nhận trả {sum(d['quantity'] for d in chi_tiet)} món, "
        f"hoàn {tien_hoan:,.0f}đ"
    )
    if tien_hoan > MONEY_EPSILON:
        mo_ta += " bằng " + (
            "tiền mặt" if request.method == "cash" else "chuyển khoản"
        )
    khong_nhap_lai = [d for d in chi_tiet if not d["restock"]]
    if khong_nhap_lai:
        mo_ta += f" - {len(khong_nhap_lai)} dòng KHÔNG nhập lại kho"
    if phieu.reason:
        mo_ta += f" - lý do: {phieu.reason}"
    order_service._them_nhat_ky(db, current_user.id, "ORDER_RETURN", mo_ta)

    db.commit()
    db.refresh(phieu)
    return _ket_qua(db, order, phieu, lap_lai=False)


def _tinh_tien_hoan(
    db: Session,
    order: models.Order,
    dong_don: Dict[int, models.OrderItem],
    da_tra: Dict[int, int],
    chi_tiet: List[Dict[str, Any]],
    ty_le: float,
) -> float:
    """Tiền hoàn của cả phiếu, và điền `tien_hoan` cho từng dòng.

    Giảm giá voucher nằm ở mức ĐƠN nên phải phân bổ xuống dòng theo tỷ trọng
    tiền hàng. Làm tròn tới đồng - tiền Việt không có phần lẻ, và số lẻ thập
    phân đi vào ledger sẽ làm lệch khoản đối chiếu của két.

    Trường hợp trả HẾT mọi thứ còn lại được xử lý riêng: hoàn đúng phần chưa
    hoàn của đơn. Cộng dồn từng dòng đã làm tròn có thể lệch vài đồng so với
    tổng đơn, mà đơn trả hết thì khách phải nhận lại đúng số đã trả, không
    thiếu một đồng nào.
    """
    con_lai_cua_don = max(
        float(order.total_amount or 0) - tong_da_hoan(db, order.id), 0.0
    )

    tra_het = all(
        d_qty(chi_tiet, dong.id) + da_tra.get(dong.id, 0) == int(dong.quantity or 0)
        for dong in dong_don.values()
    )

    tong = 0.0
    for d in chi_tiet:
        d["tien_hoan"] = float(round(d["tien_hang"] * ty_le))
        tong += d["tien_hoan"]

    if tra_het:
        # Dồn phần chênh do làm tròn vào dòng cuối để tổng khớp tuyệt đối.
        chenh = con_lai_cua_don - tong
        if chi_tiet and abs(chenh) > MONEY_EPSILON:
            chi_tiet[-1]["tien_hoan"] += chenh
        tong = con_lai_cua_don

    # Không bao giờ hoàn quá số khách đã trả cho đơn, kể cả khi làm tròn đẩy lên.
    if tong > con_lai_cua_don:
        thua = tong - con_lai_cua_don
        chi_tiet[-1]["tien_hoan"] = max(chi_tiet[-1]["tien_hoan"] - thua, 0.0)
        tong = con_lai_cua_don
    return max(tong, 0.0)


def d_qty(chi_tiet: List[Dict[str, Any]], order_item_id: int) -> int:
    """Số lượng đang trả của một dòng trong phiếu hiện tại (0 nếu không trả)."""
    for d in chi_tiet:
        if d["dong"].id == order_item_id:
            return int(d["quantity"])
    return 0


def _ket_qua(
    db: Session,
    order: models.Order,
    phieu: models.OrderReturn,
    lap_lai: bool,
) -> Dict[str, Any]:
    return {
        "msg": tr(
            "Lần trả hàng này đã được ghi nhận trước đó"
            if lap_lai
            else "Đã ghi nhận trả hàng"
        ),
        "order_id": order.id,
        "order_status": order.status,
        "total_amount": order.total_amount,
        "returned_total": tong_da_hoan(db, order.id),
        "return": _serialize_return(phieu),
    }
