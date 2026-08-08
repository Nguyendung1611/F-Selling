"""Kiểm tra và trừ tồn kho. Giá LUÔN lấy từ database, không tin client."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from .. import models
from ..core import thoi_gian
from ..core.i18n import tr
from ..schemas.order import OrderItemCreate

# Cách định danh một dòng hàng: ("id", 7) hoặc ("name", "Sữa tươi").
# Gom theo khóa này thay vì theo tên trần để hai sản phẩm trùng tên không bị
# cộng dồn vào cùng một dòng.
KhoaSanPham = Tuple[str, Any]


def lock_shop_for_inventory(db: Session, shop_id: int) -> None:
    """Lấy cùng shop write-lock trước mọi nghiệp vụ đọc-rồi-ghi tồn/lô.

    SQLite không có SELECT FOR UPDATE. No-op UPDATE này khiến bán hàng, nhập
    hàng, điều chỉnh lô, kiểm kê và hủy hàng phải xếp hàng trước khi đọc tồn.
    Nếu một đường đọc trước khóa rồi gán theo số cũ, request chen giữa có thể
    bị nuốt mất dù cả hai transaction đều báo thành công.
    """
    result = db.execute(
        text("UPDATE shops SET id = id WHERE id = :shop_id"),
        {"shop_id": int(shop_id)},
    )
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=404, detail=tr("Không tìm thấy cửa hàng"))


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
        kha_dung = ton_kha_dung(db, prod)
        if kha_dung < qty:
            # Nói rõ vì sao thiếu khi nguyên nhân là hết hạn: "còn 40 hộp mà
            # báo không đủ" là câu thu ngân sẽ hỏi ngay, và câu trả lời "12 hộp
            # trong đó đã quá hạn" phải nằm sẵn trong thông báo.
            if prod.track_batches and (prod.stock or 0) > kha_dung:
                raise HTTPException(
                    status_code=400,
                    detail=tr(
                        "Sản phẩm '{name}' chỉ còn {available} chưa hết hạn "
                        "(tổng tồn {total}); phần quá hạn không bán được",
                        name=prod.name,
                        available=kha_dung,
                        total=prod.stock or 0,
                    ),
                )
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


def _hom_nay() -> str:
    """Ngày nghiệp vụ Việt Nam.

    TRƯỚC ĐÂY dùng `datetime.utcnow()`: từ 0h đến 7h sáng giờ Việt Nam, máy vẫn
    tưởng còn là hôm qua nên hàng đã quá hạn vẫn bán được thêm 7 tiếng. Phải
    dùng chung nguồn với `write_off_service` và `catalog_service`, nếu không sẽ
    có khoảng thời gian một lô vừa không bán được vừa chưa được phép hủy.
    """
    return thoi_gian.hom_nay_vn_str()


def lo_con_ban_duoc(db: Session, product_id: int):
    """Các lô còn hàng và CHƯA hết hạn, xếp theo hạn gần nhất trước (FEFO).

    Lô không có hạn (`expiry_date` NULL) xếp sau cùng: hàng có hạn phải được đẩy
    đi trước, còn hàng không hạn thì để lâu bao nhiêu cũng được.
    """
    hom_nay = _hom_nay()
    lo = (
        db.query(models.ProductBatch)
        .filter(
            models.ProductBatch.product_id == product_id,
            models.ProductBatch.quantity > 0,
        )
        .all()
    )
    con_han = [
        b for b in lo if b.expiry_date is None or b.expiry_date >= hom_nay
    ]
    # None xếp cuối; chuỗi 'YYYY-MM-DD' so sánh trực tiếp là đúng thứ tự ngày.
    con_han.sort(key=lambda b: (b.expiry_date is None, b.expiry_date or "", b.id))
    return con_han


def ton_kha_dung(db: Session, prod: models.Product) -> int:
    """Số lượng THỰC SỰ bán được: đã loại phần quá hạn.

    Sản phẩm không bật `track_batches` thì đây chính là `prod.stock` như cũ.
    """
    if not prod.track_batches:
        return int(prod.stock or 0)
    return sum(b.quantity for b in lo_con_ban_duoc(db, prod.id))


def deduct_stock(
    db: Session,
    resolved_items: Iterable[Tuple[models.Product, int]],
) -> Dict[int, List[Tuple[models.ProductBatch, int]]]:
    """Trừ tồn kho (đã kiểm ở resolve_items). Không commit - caller giữ một
    transaction duy nhất.

    Sản phẩm theo lô bị trừ theo FEFO: lấy hết lô hạn gần nhất rồi mới sang lô
    sau, nên hàng cũ ra khỏi kệ trước. Trả về chi tiết lô đã lấy của từng sản
    phẩm để caller ghi `order_item_batches` — không có vết đó thì lúc trả hàng
    không biết nhập lại vào lô nào.
    """
    chi_tiet: Dict[int, List[Tuple[models.ProductBatch, int]]] = {}
    for prod, qty in resolved_items:
        if not prod.track_batches:
            prod.stock -= qty
            continue

        con_lai = qty
        da_lay: List[Tuple[models.ProductBatch, int]] = []
        for lo in lo_con_ban_duoc(db, prod.id):
            if con_lai <= 0:
                break
            lay = min(lo.quantity, con_lai)
            lo.quantity -= lay
            con_lai -= lay
            da_lay.append((lo, lay))
        if con_lai > 0:
            # resolve_items đã kiểm nên tới đây là có ai đó vừa bán chen vào.
            raise HTTPException(
                status_code=400,
                detail=tr(
                    "Sản phẩm '{name}' vừa hết hàng còn hạn; vui lòng thử lại",
                    name=prod.name,
                ),
            )
        prod.stock -= qty      # bản sao tổng, cập nhật cùng transaction với lô
        chi_tiet[prod.id] = da_lay
    return chi_tiet


def gia_von_binh_quan_da_lay(
    da_lay: List[Tuple[models.ProductBatch, int]]
) -> Optional[float]:
    """Giá vốn chốt vào dòng đơn khi một dòng ăn qua nhiều lô.

    Trả None nếu có lô nào chưa khai giá vốn - `None` nghĩa là "chưa biết", và
    trộn nó với 0 là biến hàng chưa khai giá thành lãi bằng cả giá bán
    (xem bẫy 13 trong KIEN_TRUC.md).
    """
    if not da_lay:
        return None
    tong_tien = 0.0
    tong_sl = 0
    for lo, sl in da_lay:
        if lo.cost_price is None:
            return None
        tong_tien += float(lo.cost_price) * sl
        tong_sl += sl
    return (tong_tien / tong_sl) if tong_sl else None


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
        hoan_lai_lo(db, item.id, item.quantity)
        prod.stock = (prod.stock or 0) + item.quantity
        restored += 1
    return restored, unrestored


def hoan_lai_lo(db: Session, order_item_id: int, so_luong: int) -> int:
    """Trả số lượng về ĐÚNG các lô đã xuất cho dòng đơn này.

    Trả về lô cũ chứ không tạo lô mới, vì hàng quay về vẫn mang đúng hạn sử
    dụng và đúng giá vốn của lúc nó ra đi. Tạo lô mới là bịa ra một hạn không
    có thật; dồn vào lô bất kỳ là làm sai cả hạn lẫn giá vốn.

    Hoàn theo thứ tự NGƯỢC với lúc xuất (lô hạn xa trả trước) để phần trả một
    phần không đẩy hàng cận hạn quay lại kệ trước hàng còn dài hạn.

    Trả về số lượng thực sự hoàn được vào lô.
    """
    ve_lo = (
        db.query(models.OrderItemBatch)
        .filter(models.OrderItemBatch.order_item_id == order_item_id)
        .all()
    )
    if not ve_lo:
        return 0      # dòng của sản phẩm không theo lô

    ids = [v.batch_id for v in ve_lo]
    lo_theo_id = {
        b.id: b
        for b in db.query(models.ProductBatch)
        .filter(models.ProductBatch.id.in_(ids))
        .all()
    }
    ve_lo.sort(
        key=lambda v: (
            (lo_theo_id[v.batch_id].expiry_date is None)
            if v.batch_id in lo_theo_id
            else True,
            (lo_theo_id[v.batch_id].expiry_date or "") if v.batch_id in lo_theo_id else "",
        ),
        reverse=True,
    )

    con_lai = so_luong
    for vet in ve_lo:
        if con_lai <= 0:
            break
        lo = lo_theo_id.get(vet.batch_id)
        if lo is None:
            continue      # lô đã bị xóa; bỏ qua, caller đếm phần không hoàn được
        tra = min(vet.quantity, con_lai)
        lo.quantity += tra
        con_lai -= tra
    return so_luong - con_lai


def doi_chieu_ton_kho(db: Session, shop_id: int) -> List[Dict[str, Any]]:
    """Tìm sản phẩm mà `Product.stock` lệch với tổng số lượng các lô.

    `Product.stock` là BẢN SAO của tổng lô, được ghi cùng transaction ở mọi
    đường. Nhưng "cùng transaction" là lời hứa của code, không phải ràng buộc
    của DB - nên phải có chỗ kiểm lại, y như `verify_required_indexes()` kiểm
    các unique index mà `run_migrations()` có thể đã nuốt lỗi.
    """
    lech: List[Dict[str, Any]] = []
    products = (
        db.query(models.Product)
        .filter(
            models.Product.shop_id == shop_id,
            models.Product.track_batches == True,  # noqa: E712
        )
        .all()
    )
    for prod in products:
        tong_lo = sum(
            b.quantity
            for b in db.query(models.ProductBatch)
            .filter(models.ProductBatch.product_id == prod.id)
            .all()
        )
        if tong_lo != int(prod.stock or 0):
            lech.append({
                "product_id": prod.id,
                "name": prod.name,
                "stock": int(prod.stock or 0),
                "batch_total": tong_lo,
            })
    return lech
