"""Nhận phiếu bán hàng đã bán khi mất mạng.

**Đây KHÔNG phải `create_order` với tham số khác.** Hai nghiệp vụ ngược chiều
nhau, và ép chung một cửa là đẻ ra lỗi tiền im lặng:

|                | `create_order`                | ở đây                          |
|----------------|-------------------------------|--------------------------------|
| Giao dịch      | đang xảy ra, trên server      | **đã xảy ra rồi**, ở máy bán   |
| Giá            | tính lại từ DB, bỏ giá client | **lấy giá trên phiếu**         |
| Hết hàng       | từ chối đơn                   | vẫn ghi, cho tồn âm, báo chủ   |
| Ca thu ngân    | ca đang mở lúc gọi hàm        | **ca đang mở lúc BÁN**         |
| Thanh toán     | chuyển khoản / mặt / nợ       | **chỉ tiền mặt**               |

Ba lý do cho ba dòng in đậm:

1. **Giá phải lấy từ phiếu.** Bán lúc 9h giá 100k, chủ shop đổi 120k lúc 11h,
   sync lúc 14h. Tính lại theo giá hôm nay là ghi 120k trong khi khách đã đưa
   100k — két lệch 20k và không ai tra ra vì sao.
2. **Hết hàng vẫn phải ghi.** Hàng đã ra khỏi cửa thật. Từ chối đơn thì tiền
   trong két thừa so với sổ, và cửa hàng mất luôn dấu vết giao dịch. Cho tồn âm
   rồi báo chủ shop đi kiểm kê là cách duy nhất giữ được cả doanh thu lẫn két.
3. **Ca theo giờ bán.** Bán 14h ca sáng, sync 18h. Gắn vào ca chiều là ca sáng
   đã chốt quỹ xong mà doanh thu lại rơi sang ca sau — sổ ca sai vĩnh viễn.

Chỉ tiền mặt vì voucher cần đếm lượt dùng trên server và ghi nợ cần kiểm hạn
mức trên server. Offline không kiểm được, mà đoán bừa thì hậu quả là tiền.

Chống ghi hai lần dựa vào unique index `ux_orders_offline_uuid`. Nó nằm trong
`financial_indexes` của bootstrap: thiếu index đó thì app KHÔNG khởi động, vì
máy bán gửi lại phiếu là chuyện bình thường và mỗi lần gửi lại sẽ là một đơn
mới — doanh thu và tồn kho cùng nhân đôi.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .. import models
from ..core.i18n import tr
from ..dependencies import (
    PERMISSION_SALE,
    require_shop_access,
    require_staff_permission,
)
from ..schemas.order import OfflineOrderCreate
from . import inventory_service, order_service

# Vướng mắc lúc ghi phiếu. Nối bằng dấu phẩy vào `orders.offline_issue` để nổi
# lên màn Đối Soát. Đơn KHÔNG bị chặn vì lý do nào trong số này.
ISSUE_TON_AM = "TON_AM"              # kho không đủ hàng lúc sync
ISSUE_CA_DA_CHOT = "CA_DA_CHOT"      # ca lúc bán nay đã kết ca
ISSUE_KHONG_CO_CA = "KHONG_CO_CA"    # không ca nào phủ giờ bán
ISSUE_SP_KHONG_CON = "SP_KHONG_CON"  # sản phẩm đã bị xóa giữa bán và sync
ISSUE_GIA_DOI = "GIA_DOI"            # giá trên phiếu khác giá hiện tại

# Đã nằm trong `CASH_PAYMENT_IN_TYPES` của shift_service nên tự được tính vào
# két của ca. ĐỪNG thêm `CashMovement` kèm theo — sẽ cộng két hai lần.
ENTRY_SALE_CASH = "SALE_CASH"

MONEY_EPSILON = 0.01


def _tien(x: Any) -> float:
    return float(x or 0)


def _phan_hoi(order: models.Order, moi: bool) -> Dict[str, Any]:
    return {
        "order_id": order.id,
        "offline_uuid": order.offline_uuid,
        "total": _tien(order.total_amount),
        "shift_id": order.shift_id,
        "issues": [x for x in (order.offline_issue or "").split(",") if x],
        # `False` = phiếu này đã được ghi trước đó, lần gửi này không tạo gì mới.
        # Máy bán dựa vào đây để xóa phiếu khỏi hàng chờ mà không sợ mất đơn.
        "created": moi,
    }


def _tim_theo_uuid(
    db: Session, shop_id: int, current_user: models.User, uuid: str
) -> Optional[models.Order]:
    don = (
        db.query(models.Order)
        .filter(models.Order.offline_uuid == uuid)
        .first()
    )
    if don is None:
        return None
    # UUID do máy sinh nhưng vẫn phải kiểm: một máy không được dùng uuid để đọc
    # hay ghi đè đơn của shop khác.
    if don.shop_id != shop_id:
        raise HTTPException(
            status_code=409,
            detail=tr("Mã phiếu offline đã được dùng cho một cửa hàng khác"),
        )
    return don


def _ca_phu_gio_ban(
    db: Session, shop_id: int, user_id: int, luc_ban: datetime
) -> Optional[models.CashShift]:
    """Ca của chính người bán, đang mở vào ĐÚNG thời điểm bán.

    Lấy cả ca đã đóng: doanh thu phải nằm đúng kỳ của nó. Ca đã đóng thì gắn cờ
    `CA_DA_CHOT` để chủ shop biết con số chốt ca cũ không còn khớp.
    """
    return (
        db.query(models.CashShift)
        .filter(
            models.CashShift.shop_id == shop_id,
            models.CashShift.opened_by_user_id == user_id,
            models.CashShift.opened_at <= luc_ban,
            or_(
                models.CashShift.closed_at.is_(None),
                models.CashShift.closed_at >= luc_ban,
            ),
        )
        .order_by(models.CashShift.opened_at.desc())
        .first()
    )


def _tru_ton_chiu_thieu(
    db: Session, prod: models.Product, so_luong: int
) -> Tuple[List[Tuple[models.ProductBatch, int]], int]:
    """Trừ tồn kho, KHÔNG chặn khi thiếu. Trả về (lô đã lấy, số còn thiếu).

    Khác `inventory_service.deduct_stock` ở đúng một điểm: hàm kia ném 400 khi
    lô không đủ, còn ở đây hàng đã ra khỏi cửa nên phải ghi.

    `Product.stock` bị trừ ĐỦ số lượng đã bán, kể cả khi lô không phủ hết. Với
    hàng theo lô, điều đó tạm phá bất biến "stock = tổng mọi lô" (bẫy 21) — và
    đó là **có chủ ý**: chính khoảng lệch ấy là bằng chứng có hàng ra khỏi kho mà
    không có lô nào chịu. Cờ `TON_AM` bảo chủ shop đi kiểm kê, và kiểm kê theo lô
    (bẫy 24) dựng lại `stock` bằng tổng mọi lô — đúng cách chữa.
    """
    if not prod.track_batches:
        con_truoc = int(prod.stock or 0)
        prod.stock = con_truoc - so_luong
        return [], max(so_luong - max(con_truoc, 0), 0)

    con_lai = so_luong
    da_lay: List[Tuple[models.ProductBatch, int]] = []
    for lo in inventory_service.lo_con_ban_duoc(db, prod.id):
        if con_lai <= 0:
            break
        lay = min(int(lo.quantity or 0), con_lai)
        if lay <= 0:
            continue
        lo.quantity = int(lo.quantity or 0) - lay
        con_lai -= lay
        da_lay.append((lo, lay))
    prod.stock = int(prod.stock or 0) - so_luong
    return da_lay, con_lai


def dong_bo_phieu(
    db: Session,
    current_user: models.User,
    shop_id: int,
    phieu: OfflineOrderCreate,
) -> Dict[str, Any]:
    """Ghi một phiếu bán offline vào sổ. Gọi lại cùng `offline_uuid` là no-op."""
    require_shop_access(db, shop_id, current_user)
    require_staff_permission(current_user, PERMISSION_SALE)

    uuid = phieu.offline_uuid.strip()
    if not uuid:
        raise HTTPException(status_code=400, detail=tr("Thiếu mã phiếu offline"))

    da_co = _tim_theo_uuid(db, shop_id, current_user, uuid)
    if da_co is not None:
        return _phan_hoi(da_co, moi=False)

    # Cùng hàng rào với `create_order`: mọi phép đọc quyết định việc ghi (tồn
    # kho) phải nằm sau một write lock của shop.
    order_service._lock_shop_for_order(db, shop_id)

    # Một lần sync song song có thể đã ghi xong trong lúc request này chờ lock.
    da_co = _tim_theo_uuid(db, shop_id, current_user, uuid)
    if da_co is not None:
        db.rollback()
        return _phan_hoi(da_co, moi=False)

    luc_ban = phieu.sold_at.replace(tzinfo=None) if phieu.sold_at.tzinfo else phieu.sold_at
    if luc_ban > datetime.utcnow():
        # Đồng hồ máy bán chạy nhanh. Nhận giờ tương lai thì đơn rơi ra ngoài mọi
        # báo cáo theo ngày và không ca nào phủ được nó.
        raise HTTPException(
            status_code=400,
            detail=tr("Giờ bán nằm ở tương lai; kiểm lại đồng hồ máy bán"),
        )

    van_de: List[str] = []

    # ---- Dựng các dòng hàng theo GIÁ TRÊN PHIẾU ----
    tong = 0.0
    dong_hang: List[Dict[str, Any]] = []
    for mh in phieu.items:
        # Lọc kèm shop_id: thiếu điều kiện đó thì đoán product_id là bán được
        # hàng của shop khác (bẫy 22).
        prod = (
            db.query(models.Product)
            .filter(
                models.Product.id == mh.product_id,
                models.Product.shop_id == shop_id,
            )
            .first()
        )
        tien_dong = _tien(mh.unit_price) * mh.quantity
        tong += tien_dong
        dong_hang.append({"prod": prod, "mh": mh})

        if prod is None:
            # Sản phẩm bị xóa giữa lúc bán và lúc sync. Vẫn ghi dòng tiền bằng
            # tên đã chụp, để khoản tiền trong két còn tra được về đâu.
            if ISSUE_SP_KHONG_CON not in van_de:
                van_de.append(ISSUE_SP_KHONG_CON)
        elif abs(_tien(prod.price) - _tien(mh.unit_price)) > MONEY_EPSILON:
            if ISSUE_GIA_DOI not in van_de:
                van_de.append(ISSUE_GIA_DOI)

    if _tien(phieu.cash_tendered) + MONEY_EPSILON < tong:
        # Tiền khách đưa ít hơn tổng đơn là phiếu sai, không phải xung đột dữ
        # liệu. Nhận vào là ghi một khoản thu không có thật.
        raise HTTPException(
            status_code=400,
            detail=tr(
                "Tiền khách đưa ({tendered}) nhỏ hơn tổng đơn ({total})",
                tendered=f"{_tien(phieu.cash_tendered):,.0f}đ",
                total=f"{tong:,.0f}đ",
            ),
        )

    # ---- Ca thu ngân theo GIỜ BÁN ----
    ca = _ca_phu_gio_ban(db, shop_id, current_user.id, luc_ban)
    if ca is None:
        van_de.append(ISSUE_KHONG_CO_CA)
    elif ca.status != "OPEN":
        van_de.append(ISSUE_CA_DA_CHOT)

    # ---- Ghi đơn ----
    don = models.Order(
        shop_id=shop_id,
        created_by_user_id=current_user.id,
        shift_id=ca.id if ca else None,
        total_amount=tong,
        discount_amount=0,
        payment_method=order_service.PAYMENT_METHOD_CASH,
        status=order_service.STATUS_PAID,
        cash_paid_amount=tong,
        cash_tendered_amount=_tien(phieu.cash_tendered),
        cash_change_amount=max(_tien(phieu.cash_tendered) - tong, 0.0),
        # created_at = GIỜ BÁN. Báo cáo theo ngày phải xếp đơn vào ngày nó được
        # bán, không phải ngày máy tình cờ có mạng trở lại.
        created_at=luc_ban,
        sold_offline_at=luc_ban,
        offline_uuid=uuid,
        offline_device=(phieu.device_label or "").strip() or None,
    )
    db.add(don)
    db.flush()  # cần id để gắn dòng hàng và bút toán

    for cap in dong_hang:
        prod: Optional[models.Product] = cap["prod"]
        mh = cap["mh"]

        gia_von: Optional[float] = None
        # Khởi tạo ngay ở đầu vòng lặp: để nó chỉ được gán trong nhánh
        # `prod is not None` thì một dòng sản phẩm-đã-xóa đứng giữa hai dòng
        # bình thường sẽ khiến biến này mang giá trị của dòng TRƯỚC.
        da_lay: List[Tuple[models.ProductBatch, int]] = []
        if prod is not None:
            da_lay, thieu = _tru_ton_chiu_thieu(db, prod, mh.quantity)
            if thieu > 0 and ISSUE_TON_AM not in van_de:
                van_de.append(ISSUE_TON_AM)
            gia_von = (
                inventory_service.gia_von_binh_quan_da_lay(da_lay)
                if prod.track_batches
                else (None if prod.cost_price is None else _tien(prod.cost_price))
            )

        dong = models.OrderItem(
            order_id=don.id,
            product_id=prod.id if prod else None,
            product_name=mh.product_name.strip(),
            price=_tien(mh.unit_price),
            quantity=mh.quantity,
            cost_price=gia_von,
        )
        db.add(dong)
        db.flush()

        if prod is not None and prod.track_batches:
            for lo, sl in da_lay:
                db.add(
                    models.OrderItemBatch(
                        order_item_id=dong.id,
                        batch_id=lo.id,
                        quantity=sl,
                        # Chốt giá vốn của ĐÚNG lô đã xuất: lúc khách trả hàng
                        # phải hoàn về đúng lô với đúng giá vốn đó (bẫy 21).
                        cost_price=lo.cost_price,
                    )
                )

    if van_de:
        don.offline_issue = ",".join(van_de)

    # ---- Bút toán tiền mặt vào két của ca ----
    # `idempotency_key` là lớp chặn thứ hai sau `ux_orders_offline_uuid`: hai
    # request song song lọt qua cùng lúc thì unique index của ledger vẫn chặn.
    db.add(
        models.OrderPayment(
            order_id=don.id,
            entry_type=ENTRY_SALE_CASH,
            amount=tong,
            idempotency_key=f"offline:{uuid}",
            created_by_user_id=current_user.id,
            shift_id=ca.id if ca else None,
            note="Bán tiền mặt khi mất mạng",
            created_at=luc_ban,
        )
    )

    order_service._them_nhat_ky(
        db,
        current_user.id,
        "OFFLINE_SALE",
        (
            f"Đơn #{don.id} bán offline lúc {luc_ban:%Y-%m-%d %H:%M} "
            f"- {tong:,.0f}đ - máy: {don.offline_device or 'không rõ'}"
            + (f" - vướng: {don.offline_issue}" if don.offline_issue else "")
        ),
    )
    db.commit()
    db.refresh(don)
    return _phan_hoi(don, moi=True)


def danh_sach_can_xu_ly(db: Session, shop_id: int) -> List[Dict[str, Any]]:
    """Đơn offline có vướng mắc, để chủ shop xử lý. Mới nhất trước."""
    don = (
        db.query(models.Order)
        .filter(
            models.Order.shop_id == shop_id,
            models.Order.offline_issue.isnot(None),
        )
        .order_by(models.Order.sold_offline_at.desc())
        .all()
    )
    return [
        {
            "order_id": o.id,
            "sold_at": o.sold_offline_at,
            "total": _tien(o.total_amount),
            "device": o.offline_device,
            "shift_id": o.shift_id,
            "issues": [x for x in (o.offline_issue or "").split(",") if x],
        }
        for o in don
    ]
