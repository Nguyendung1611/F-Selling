"""Xả hàng tồn: món nào đang chôn vốn, và hạ giá tới đâu thì còn lãi.

Cũng như `forecast_service`, ở đây không có mô hình ngôn ngữ nào. Con số này
quyết định giá bán, mà giá bán sai một lần là lỗ thật.

**Vì sao đề xuất GIÁ BÁN MỚI chứ không tạo voucher.** Voucher của F-Selling
giảm trên TỔNG ĐƠN (`voucher_service.compute_discount(voucher, subtotal)`),
không gắn được vào một sản phẩm. Sinh voucher 40% từ biên lãi của một món áo
2.000đ thì khách mua món lãi 12% cũng được giảm 40% - cái voucher đẻ ra để cứu
một món hàng ế sẽ làm mất tiền triệu ở món khác. Hạ giá đúng món đang ế là việc
tiệm tạp hóa vẫn làm ngoài đời, và nó không đụng vào đường tính tiền của đơn.

**Giá sàn luôn là giá vốn.** Bán dưới giá vốn có khi vẫn đúng (hàng sắp hết hạn
thì thu lại được đồng nào hay đồng đó), nhưng đó là quyết định của chủ shop chứ
không phải của một công thức. Máy dừng ở hòa vốn và nói ra phần còn lại.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models
from ..core import thoi_gian
from ..dependencies import require_cost_visibility, require_shop_access
from . import inventory_service, order_service

# Bao lâu không bán được món nào thì coi là hàng nằm ế. 45 ngày là đủ dài để
# không kết tội oan hàng theo mùa (mắm, bánh trung thu), đủ ngắn để vốn chưa
# chôn quá lâu.
SO_NGAY_COI_LA_E = 45

# Lô còn hạn dưới ngần này ngày thì phải đẩy đi, bất kể đang bán tốt hay không.
SO_NGAY_CANH_BAO_HAN = 30

# Nhường bao nhiêu phần LÃI cho khách. Hàng chỉ nằm ế thì nhường một nửa; càng
# sát hạn càng nhường nhiều, vì quá hạn là mất trắng cả phần vốn.
NHUONG_LAI_IT_NHAT = 0.5
NHUONG_LAI_NHIEU_NHAT = 0.9

# Lý do một món lọt vào danh sách.
LY_DO_E = "NAM_E"
LY_DO_SAP_HET_HAN = "SAP_HET_HAN"
LY_DO_CA_HAI = "CA_HAI"


def _don_vi_lam_tron(gia: float) -> int:
    """Giá lẻ tới từng đồng thì không ai dán lên kệ được.

    Tiệm tạp hóa niêm yết theo trăm hoặc nửa nghìn, hàng giá trị lớn thì theo
    nghìn. Làm tròn theo độ lớn của chính món hàng thay vì một con số cố định.
    """
    if gia < 10_000:
        return 100
    if gia < 100_000:
        return 500
    return 1_000


def _gia_de_xuat(gia_ban: float, gia_von: float, so_ngay_con_han: Optional[int]) -> int:
    """Giá mới: nhường bớt phần lãi, làm tròn, và KHÔNG BAO GIỜ dưới giá vốn."""
    bien_lai = gia_ban - gia_von
    if so_ngay_con_han is None:
        ty_le = NHUONG_LAI_IT_NHAT
    else:
        # Còn đủ 30 ngày -> nhường 50%; hết hạn tới nơi -> nhường 90%.
        con_lai = max(0.0, min(1.0, so_ngay_con_han / SO_NGAY_CANH_BAO_HAN))
        ty_le = NHUONG_LAI_NHIEU_NHAT - (NHUONG_LAI_NHIEU_NHAT - NHUONG_LAI_IT_NHAT) * con_lai

    gia_tho = gia_ban - bien_lai * ty_le
    don_vi = _don_vi_lam_tron(gia_ban)
    gia = round(gia_tho / don_vi) * don_vi

    # Làm tròn xuống có thể chui xuống dưới giá vốn với món biên lãi mỏng.
    if gia < gia_von:
        gia = math.ceil(gia_von / don_vi) * don_vi
    # Và không được vượt quá giá đang bán - "giảm giá" mà đắt lên là vô nghĩa.
    return int(min(gia, gia_ban))


def _gia_von_hien_hanh(db: Session, prod: models.Product) -> Optional[float]:
    """Giá vốn của số hàng ĐANG CÒN trong kho.

    Hàng theo lô KHÔNG giữ giá vốn ở `Product.cost_price` - nó nằm ở từng lô
    (mục 21), vì mỗi lần nhập một giá khác nhau. Đọc `prod.cost_price` cho hàng
    theo lô sẽ ra NULL và cả màn hình báo "chưa khai giá vốn" trong khi phiếu
    nhập ghi giá đầy đủ.

    Lấy bình quân gia quyền của các lô còn bán được: bán hết chỗ hàng đó ở mức
    giá này thì không lỗ. Chỉ cần MỘT lô chưa khai giá là trả None - trộn lô
    chưa khai với lô đã khai là kéo bình quân xuống thấp hơn sự thật, rồi đề
    xuất một mức giá đang lỗ mà nhìn vẫn có lãi (mục 13).
    """
    if not prod.track_batches:
        return prod.cost_price

    lo = inventory_service.lo_con_ban_duoc(db, prod.id)
    if not lo:
        return prod.cost_price
    if any(b.cost_price is None for b in lo):
        return None
    tong_sl = sum(b.quantity for b in lo)
    if tong_sl <= 0:
        return prod.cost_price
    return sum(float(b.cost_price) * b.quantity for b in lo) / tong_sl


def _ngay_ban_gan_nhat(db: Session, shop_id: int) -> Dict[int, datetime]:
    """{product_id: lần cuối món này rời kệ}.

    Cùng bộ lọc với `forecast_service`: mọi đơn TRỪ đơn đã hủy. Đơn hủy được
    hoàn tồn kho nên hàng chưa từng đi đâu cả.
    """
    hang = (
        db.query(
            models.OrderItem.product_id,
            func.max(models.Order.created_at),
        )
        .join(models.Order, models.Order.id == models.OrderItem.order_id)
        .filter(
            models.Order.shop_id == shop_id,
            models.Order.status != order_service.STATUS_CANCELLED,
            models.OrderItem.product_id.isnot(None),
        )
        .group_by(models.OrderItem.product_id)
        .all()
    )
    ket_qua: Dict[int, datetime] = {}
    for product_id, moc in hang:
        if moc is None:
            continue
        if isinstance(moc, str):      # SQLite trả chuỗi khi cột không parse được
            try:
                moc = datetime.fromisoformat(moc)
            except ValueError:
                continue
        ket_qua[product_id] = moc
    return ket_qua


def _thong_tin_lo(db: Session, shop_id: int) -> Dict[int, Dict[str, Any]]:
    """{product_id: {hạn gần nhất còn bán được, số lượng đã quá hạn}}."""
    hom_nay = thoi_gian.hom_nay_vn_str()
    lo = (
        db.query(models.ProductBatch)
        .filter(
            models.ProductBatch.shop_id == shop_id,
            models.ProductBatch.quantity > 0,
            models.ProductBatch.expiry_date.isnot(None),
        )
        .all()
    )
    ket_qua: Dict[int, Dict[str, Any]] = {}
    for b in lo:
        muc = ket_qua.setdefault(
            b.product_id, {"han_gan_nhat": None, "so_luong_da_het_han": 0}
        )
        if b.expiry_date < hom_nay:
            # Hàng đã hỏng thì KHÔNG được đem đi hạ giá bán - nó phải đi qua
            # phiếu hủy. Đếm riêng để giao diện nói ra.
            muc["so_luong_da_het_han"] += b.quantity
            continue
        if muc["han_gan_nhat"] is None or b.expiry_date < muc["han_gan_nhat"]:
            muc["han_gan_nhat"] = b.expiry_date
    return ket_qua


def de_xuat_xa_hang(
    db: Session,
    current_user: models.User,
    shop_id: int,
    *,
    so_ngay_coi_la_e: int = SO_NGAY_COI_LA_E,
    so_ngay_canh_bao_han: int = SO_NGAY_CANH_BAO_HAN,
) -> Dict[str, Any]:
    """Danh sách hàng đang chôn vốn, kèm giá bán mới còn giữ được lãi.

    CHỈ chủ shop và ADMIN. Khác `forecast_service` (nhân viên kho xem được phần
    số lượng): ở đây **mọi con số đều dựng từ giá vốn** - giá sàn, mức giảm, vốn
    đang đọng - nên không có phần nào giấu đi mà màn hình còn nghĩa. Che một
    nửa rồi vẫn cho xem mức giảm là để nhân viên suy ngược ra giá vốn.
    """
    shop = require_shop_access(db, shop_id, current_user)
    require_cost_visibility(shop, current_user)

    hom_nay = thoi_gian.hom_nay_vn()
    ban_gan_nhat = _ngay_ban_gan_nhat(db, shop_id)
    thong_tin_lo = _thong_tin_lo(db, shop_id)

    san_pham = (
        db.query(models.Product)
        .filter(
            models.Product.shop_id == shop_id,
            models.Product.is_active.is_(True),
        )
        .all()
    )

    danh_sach: List[Dict[str, Any]] = []
    tong_von_dong = 0
    for prod in san_pham:
        ton = inventory_service.ton_kha_dung(db, prod)
        lo = thong_tin_lo.get(prod.id, {})
        so_luong_da_het_han = lo.get("so_luong_da_het_han", 0)
        if ton <= 0 and so_luong_da_het_han <= 0:
            continue      # không còn gì trong kho thì không có gì để xả

        moc_ban = ban_gan_nhat.get(prod.id)
        if moc_ban is None:
            so_ngay_khong_ban = None      # chưa bán được lần nào
            dang_e = True
        else:
            # `created_at` lưu theo UTC; đổi sang ngày Việt Nam rồi mới đếm.
            ngay_ban = (moc_ban + timedelta(hours=7)).date()
            so_ngay_khong_ban = (hom_nay - ngay_ban).days
            dang_e = so_ngay_khong_ban >= so_ngay_coi_la_e

        han_gan_nhat = lo.get("han_gan_nhat")
        so_ngay_con_han = None
        sap_het_han = False
        if han_gan_nhat:
            so_ngay_con_han = (date.fromisoformat(han_gan_nhat) - hom_nay).days
            sap_het_han = so_ngay_con_han <= so_ngay_canh_bao_han

        if not dang_e and not sap_het_han and so_luong_da_het_han <= 0:
            continue

        if dang_e and sap_het_han:
            ly_do = LY_DO_CA_HAI
        elif sap_het_han:
            ly_do = LY_DO_SAP_HET_HAN
        else:
            ly_do = LY_DO_E

        gia_ban = float(prod.price or 0)
        gia_von = _gia_von_hien_hanh(db, prod)
        von_dang_dong = (
            int(round(float(gia_von) * ton)) if gia_von is not None else None
        )
        if von_dang_dong:
            tong_von_dong += von_dang_dong

        dong: Dict[str, Any] = {
            "product_id": prod.id,
            "ten": prod.name,
            "ma": prod.code,
            "ton_kho": ton,
            "theo_lo": bool(prod.track_batches),
            "so_luong_da_het_han": so_luong_da_het_han,
            "gia_hien_tai": int(round(gia_ban)),
            "gia_von": int(round(float(gia_von))) if gia_von is not None else None,
            "von_dang_dong": von_dang_dong,
            "so_ngay_khong_ban": so_ngay_khong_ban,
            "ngay_ban_gan_nhat": (
                (moc_ban + timedelta(hours=7)).date().isoformat() if moc_ban else None
            ),
            "han_gan_nhat": han_gan_nhat,
            "so_ngay_con_han": so_ngay_con_han,
            "ly_do": ly_do,
        }

        # Giá vốn NULL là "chưa ai khai", không phải 0 (bẫy 13): không có thì
        # không đoán ra giá sàn, và tuyệt đối không lấy 0 làm giá vốn - làm vậy
        # là bảo chủ shop rằng bán 1 đồng vẫn lãi.
        if gia_von is None:
            dong["gia_de_xuat"] = None
            dong["khong_tinh_duoc"] = "CHUA_KHAI_GIA_VON"
        elif gia_ban <= float(gia_von):
            dong["gia_de_xuat"] = None
            dong["khong_tinh_duoc"] = "DANG_BAN_KHONG_LAI"
        else:
            gia_moi = _gia_de_xuat(gia_ban, float(gia_von), so_ngay_con_han)
            dong["gia_de_xuat"] = gia_moi
            dong["giam_phan_tram"] = round((gia_ban - gia_moi) / gia_ban * 100, 1)
            dong["lai_moi_cai_sau_giam"] = int(round(gia_moi - float(gia_von)))
            dong["tien_thu_ve_du_kien"] = int(round(gia_moi * ton))

        danh_sach.append(dong)

    # Gấp nhất lên đầu: hàng sắp hỏng trước (quá hạn là mất trắng), rồi tới món
    # chôn nhiều vốn nhất.
    thu_tu_ly_do = {LY_DO_CA_HAI: 0, LY_DO_SAP_HET_HAN: 1, LY_DO_E: 2}
    danh_sach.sort(
        key=lambda d: (
            thu_tu_ly_do[d["ly_do"]],
            d["so_ngay_con_han"] if d["so_ngay_con_han"] is not None else 10**6,
            -(d["von_dang_dong"] or 0),
        )
    )

    return {
        "shop_id": shop_id,
        "hom_nay": hom_nay.isoformat(),
        "so_ngay_coi_la_e": so_ngay_coi_la_e,
        "so_ngay_canh_bao_han": so_ngay_canh_bao_han,
        "so_mat_hang": len(danh_sach),
        "tong_von_dang_dong": tong_von_dong,
        "so_mat_hang_chua_khai_gia_von": sum(
            1 for d in danh_sach if d.get("khong_tinh_duoc") == "CHUA_KHAI_GIA_VON"
        ),
        "so_luong_can_huy": sum(d["so_luong_da_het_han"] for d in danh_sach),
        "danh_sach": danh_sach,
    }
