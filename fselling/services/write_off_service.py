"""F6: phiếu hủy hàng - hàng ra khỏi kho mà không sinh doanh thu.

Trước bản này, hàng hết hạn hoặc vỡ chỉ có một đường duy nhất là xuất kho
(`adjust_stock` với delta âm). Đường đó không ghi lý do và không chốt giá vốn ở
đâu cả, nên số hàng đó **biến mất khỏi báo cáo**: tồn kho giảm, doanh thu không
đổi, và lãi gộp bị thổi lên đúng bằng phần vốn vừa mất. Chủ shop nhìn con số đó
tin là thật - cùng một kiểu sai với bẫy 13 (giá vốn NULL bị đọc thành 0), lặp
lại ở một chỗ khác.

Phiếu hủy sửa đúng chỗ đó: chốt `cost_price` xuống từng dòng ngay lúc hủy, và
`report_service._huy_hang_anh_huong_lai` trừ khoản đó ra khỏi lãi.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models
from ..core.i18n import tr
from ..dependencies import require_cost_visibility, require_shop_access
from ..schemas.catalog import WriteOffCreate
from .log_service import log_system_action

# Chốt danh sách như `PAYMENT_METHODS` ở F4. Trường này mang hệ quả tài chính
# thật (nó là lý do một khoản lỗ được ghi nhận) nên không để client gửi chuỗi
# tùy ý vào DB - báo cáo gom nhóm theo lý do sẽ vỡ ngay từ dòng đầu tiên gõ sai
# chính tả.
REASON_EXPIRED = "EXPIRED"
REASON_DAMAGED = "DAMAGED"
REASON_LOST = "LOST"
WRITE_OFF_REASONS = (REASON_EXPIRED, REASON_DAMAGED, REASON_LOST)

_MO_TA_LY_DO = {
    REASON_EXPIRED: "hết hạn",
    REASON_DAMAGED: "hỏng/vỡ",
    REASON_LOST: "thất thoát",
}


def _phieu_da_ghi(
    db: Session, operation_key: str, shop_id: int
) -> Optional[models.StockWriteOff]:
    """Phiếu đã ghi với đúng mã thao tác này, nếu có.

    Mã đã dùng cho shop KHÁC là lỗi lập trình phía client (dùng lại mã cũ khi
    đổi shop), không phải một lần bấm lặp - trả 409 chứ đừng trả về phiếu của
    shop kia.
    """
    truoc = (
        db.query(models.StockWriteOff)
        .filter(models.StockWriteOff.idempotency_key == operation_key)
        .first()
    )
    if truoc is None:
        return None
    if truoc.shop_id != shop_id:
        raise HTTPException(
            status_code=409,
            detail=tr("Mã thao tác hủy hàng đã được dùng cho một cửa hàng khác"),
        )
    return truoc


def _ket_qua(
    db: Session, phieu: models.StockWriteOff, lap_lai: bool = False
) -> Dict[str, Any]:
    dong = (
        db.query(models.StockWriteOffItem)
        .filter(models.StockWriteOffItem.write_off_id == phieu.id)
        .order_by(models.StockWriteOffItem.id)
        .all()
    )
    # Ai bấm hủy là thông tin BẮT BUỘC của một màn kiểm toán: hủy hàng là đường
    # duy nhất làm tồn giảm mà không sinh doanh thu, nên "ai làm" quan trọng
    # ngang "mất bao nhiêu". Tài khoản bị xóa sau đó thì trả None chứ không bịa.
    nguoi_tao = None
    if phieu.created_by_user_id:
        nguoi_tao = (
            db.query(models.User.username)
            .filter(models.User.id == phieu.created_by_user_id)
            .scalar()
        )
    return {
        "write_off_id": phieu.id,
        "reason": phieu.reason,
        "note": phieu.note,
        "total_quantity": phieu.total_quantity,
        "created_at": phieu.created_at,
        "created_by": nguoi_tao,
        # Có dòng nào chưa khai giá vốn thì NÓI RA, đừng cộng phần biết được rồi
        # trình bày như tổng thiệt hại - con số đó thấp hơn sự thật.
        "total_cost": (
            None
            if any(d.cost_price is None for d in dong)
            else sum(float(d.cost_price) * d.quantity for d in dong)
        ),
        "items": [
            {
                "product_id": d.product_id,
                "product_name": d.product_name,
                "batch_id": d.batch_id,
                "expiry_date": d.expiry_date,
                "quantity": d.quantity,
                "cost_price": d.cost_price,
            }
            for d in dong
        ],
        "repeated": lap_lai,
    }


def _gom_dong(request: WriteOffCreate) -> List[Any]:
    """Kiểm dòng gửi lên và chặn khai trùng.

    Cùng một lô xuất hiện hai dòng trong một phiếu là lỗi nhập liệu, và nếu để
    lọt thì phép kiểm "đủ hàng để hủy" ở dưới xét từng dòng riêng lẻ sẽ cho qua
    cả hai trong khi tổng vượt quá số đang có.
    """
    if not request.items:
        raise HTTPException(
            status_code=400, detail=tr("Phiếu hủy chưa có dòng nào")
        )
    da_gap = set()
    for it in request.items:
        if it.quantity <= 0:
            raise HTTPException(
                status_code=400,
                detail=tr("Số lượng hủy phải lớn hơn 0"),
            )
        khoa = (it.product_id, it.batch_id)
        if khoa in da_gap:
            raise HTTPException(
                status_code=400,
                detail=tr("Một lô xuất hiện nhiều lần trong phiếu hủy"),
            )
        da_gap.add(khoa)
    return list(request.items)


def create_write_off(
    db: Session, current_user: models.User, shop_id: int, request: WriteOffCreate
) -> Dict[str, Any]:
    """Hủy hàng khỏi kho và ghi nhận khoản lỗ tương ứng.

    CHỈ chủ shop và ADMIN (`require_cost_visibility`) - hẹp hơn hẳn quyền kho.
    Hủy hàng là đường duy nhất làm tồn kho giảm mà không sinh doanh thu, nên nó
    cũng chính là đường thuận tiện nhất để che hàng thất thoát. Nới quyền ra sau
    này thì dễ; thu lại thì hàng đã đi rồi.
    """
    shop = require_shop_access(db, shop_id, current_user)
    require_cost_visibility(shop, current_user)

    if request.reason not in WRITE_OFF_REASONS:
        raise HTTPException(
            status_code=400,
            detail=tr(
                "Lý do hủy không hợp lệ. Chọn một trong: {reasons}",
                reasons=", ".join(WRITE_OFF_REASONS),
            ),
        )

    dong_gui = _gom_dong(request)
    operation_key = (request.operation_id or "").strip() or uuid.uuid4().hex
    truoc = _phieu_da_ghi(db, operation_key, shop_id)
    if truoc is not None:
        return _ket_qua(db, truoc, lap_lai=True)

    san_pham = {
        p.id: p
        for p in db.query(models.Product)
        .filter(
            models.Product.shop_id == shop_id,
            models.Product.id.in_([d.product_id for d in dong_gui]),
        )
        .all()
    }

    chuan_bi: List[Dict[str, Any]] = []
    for it in dong_gui:
        prod = san_pham.get(it.product_id)
        # Lọc kèm `shop_id` ở câu query trên nên id của shop khác rơi vào đây -
        # cùng lý do với `resolve_items` (bẫy 11): thiếu điều kiện đó thì đoán
        # id là hủy được hàng của cửa hàng khác.
        if prod is None:
            raise HTTPException(
                status_code=404,
                detail=tr(
                    "Sản phẩm #{id} không thuộc cửa hàng này", id=str(it.product_id)
                ),
            )

        if prod.track_batches:
            if it.batch_id is None:
                raise HTTPException(
                    status_code=400,
                    detail=tr(
                        "Sản phẩm '{name}' theo dõi hạn sử dụng; phải chọn lô "
                        "cần hủy",
                        name=prod.name,
                    ),
                )
            lo = (
                db.query(models.ProductBatch)
                .filter(
                    models.ProductBatch.id == it.batch_id,
                    models.ProductBatch.product_id == prod.id,
                )
                .first()
            )
            if lo is None:
                raise HTTPException(
                    status_code=404,
                    detail=tr(
                        "Lô #{id} không thuộc sản phẩm '{name}'",
                        id=str(it.batch_id),
                        name=prod.name,
                    ),
                )
            if lo.quantity < it.quantity:
                raise HTTPException(
                    status_code=400,
                    detail=tr(
                        "Lô HSD {expiry} của '{name}' chỉ còn {available}, "
                        "không hủy được {quantity}",
                        expiry=lo.expiry_date or "-",
                        name=prod.name,
                        available=str(lo.quantity),
                        quantity=str(it.quantity),
                    ),
                )
            chuan_bi.append({
                "prod": prod,
                "lo": lo,
                "quantity": it.quantity,
                # Giá vốn của ĐÚNG lô bị hủy, không phải bình quân của sản phẩm:
                # lô nhập đắt hỏng trên kệ là mất đúng số tiền của lô đó.
                "cost_price": lo.cost_price,
                "expiry_date": lo.expiry_date,
            })
            continue

        if it.batch_id is not None:
            raise HTTPException(
                status_code=400,
                detail=tr(
                    "Sản phẩm '{name}' không theo dõi lô, không chọn lô được",
                    name=prod.name,
                ),
            )
        if int(prod.stock or 0) < it.quantity:
            raise HTTPException(
                status_code=400,
                detail=tr(
                    "Sản phẩm '{name}' chỉ còn {available}, không hủy được "
                    "{quantity}",
                    name=prod.name,
                    available=str(int(prod.stock or 0)),
                    quantity=str(it.quantity),
                ),
            )
        chuan_bi.append({
            "prod": prod,
            "lo": None,
            "quantity": it.quantity,
            "cost_price": prod.cost_price,
            "expiry_date": None,
        })

    phieu = models.StockWriteOff(
        shop_id=shop_id,
        reason=request.reason,
        note=(request.note or "").strip()[:200] or None,
        total_quantity=sum(d["quantity"] for d in chuan_bi),
        created_by_user_id=current_user.id,
        idempotency_key=operation_key,
        created_at=datetime.utcnow(),
    )
    db.add(phieu)
    try:
        db.flush()
    except IntegrityError:
        # Unique idempotency_key: một request song song cùng mã đã ghi trước.
        db.rollback()
        lap = _phieu_da_ghi(db, operation_key, shop_id)
        if lap is not None:
            return _ket_qua(db, lap, lap_lai=True)
        raise

    for d in chuan_bi:
        prod = d["prod"]
        so_luong = d["quantity"]
        if d["lo"] is not None:
            # Lô về 0 thì GIỮ dòng lô lại chứ không xóa: đó là lịch sử, và
            # `order_item_batches` của các đơn cũ còn trỏ vào nó.
            d["lo"].quantity -= so_luong
        # `Product.stock` là bản sao của tổng lô (bẫy 21), ghi trong CÙNG
        # transaction với lô. Đây cũng là đường ghi duy nhất cho hàng không lô.
        prod.stock = int(prod.stock or 0) - so_luong
        db.add(
            models.StockWriteOffItem(
                write_off_id=phieu.id,
                product_id=prod.id,
                product_name=prod.name,
                batch_id=d["lo"].id if d["lo"] is not None else None,
                expiry_date=d["expiry_date"],
                quantity=so_luong,
                cost_price=d["cost_price"],
            )
        )

    db.commit()
    db.refresh(phieu)

    chi_tiet = ", ".join(
        f"{d['prod'].name} x{d['quantity']}" for d in chuan_bi[:10]
    )
    if len(chuan_bi) > 10:
        chi_tiet += f" (và {len(chuan_bi) - 10} dòng khác)"
    log_system_action(
        db,
        current_user.id,
        "WRITE_OFF_STOCK",
        f"Hủy hàng shop {shop_id} ({_MO_TA_LY_DO.get(request.reason, request.reason)}): "
        f"{phieu.total_quantity} đơn vị. {chi_tiet}",
    )
    db.refresh(phieu)
    return _ket_qua(db, phieu)


def de_xuat_huy_het_han(
    db: Session, current_user: models.User, shop_id: int
) -> Dict[str, Any]:
    """Các lô ĐÃ quá hạn còn hàng, dựng sẵn thành dòng của một phiếu hủy.

    Chỉ ĐỀ XUẤT, không tự hủy. Hàng quá hạn vẫn phải qua mắt người trước khi bị
    xóa khỏi kho: hạn nhập sai một chữ số là cả lô còn tốt bị bỏ đi, mà thao tác
    hủy thì không có đường lùi.
    """
    shop = require_shop_access(db, shop_id, current_user)
    require_cost_visibility(shop, current_user)

    hom_nay = datetime.utcnow().strftime("%Y-%m-%d")
    lo = (
        db.query(models.ProductBatch)
        .filter(
            models.ProductBatch.shop_id == shop_id,
            models.ProductBatch.quantity > 0,
            models.ProductBatch.expiry_date.isnot(None),
            models.ProductBatch.expiry_date < hom_nay,
        )
        .order_by(models.ProductBatch.expiry_date)
        .all()
    )
    ten_sp = {
        p.id: p.name
        for p in db.query(models.Product)
        .filter(models.Product.shop_id == shop_id)
        .all()
    }
    dong = [
        {
            "product_id": b.product_id,
            "product_name": ten_sp.get(b.product_id),
            "batch_id": b.id,
            "expiry_date": b.expiry_date,
            "quantity": b.quantity,
            "cost_price": b.cost_price,
        }
        for b in lo
    ]
    return {
        "items": dong,
        "total_quantity": sum(d["quantity"] for d in dong),
        "total_cost": (
            None
            if any(d["cost_price"] is None for d in dong)
            else sum(float(d["cost_price"]) * d["quantity"] for d in dong)
        ),
    }


def danh_sach_phieu(
    db: Session, current_user: models.User, shop_id: int, limit: int = 50
) -> Dict[str, Any]:
    """Các phiếu hủy gần đây của shop, mới nhất trước."""
    shop = require_shop_access(db, shop_id, current_user)
    require_cost_visibility(shop, current_user)

    phieu = (
        db.query(models.StockWriteOff)
        .filter(models.StockWriteOff.shop_id == shop_id)
        .order_by(models.StockWriteOff.id.desc())
        .limit(max(1, min(limit, 200)))
        .all()
    )
    return {"write_offs": [_ket_qua(db, p) for p in phieu]}
