"""Dự báo nhập hàng: tính bằng CÔNG THỨC, không gọi mô hình ngôn ngữ.

Cố ý không dùng LLM. Con số ở đây đi thẳng vào quyết định chi tiền nhập hàng,
mà một mô hình ngôn ngữ thì không có gì bảo đảm phép nhân của nó đúng - sai một
lần là chủ shop ôm một kho hàng không bán được. Toàn bộ file này chỉ là cộng,
chia và độ lệch chuẩn, chạy ngay trong máy chủ: không gọi mạng, không tốn tiền,
không phụ thuộc dịch vụ ngoài.

Bốn con số trả về cho mỗi sản phẩm:

    tốc độ bán  v   = (số đã bán trong kỳ - số khách trả về kệ) / số ngày trong kỳ
    còn bán được    = tồn khả dụng / v
    đệm dự phòng    = 1.65 x độ lệch chuẩn ngày x căn(thời gian đặt hàng)
    cần nhập        = v x (thời gian đặt hàng + muốn đủ cho) + đệm - tồn khả dụng

Đệm dự phòng dùng độ lệch chuẩn chứ không dùng một tỷ lệ phần trăm cố định:
hàng bán đều mỗi ngày thì gần như không cần đệm, hàng lúc bán 1 lúc bán 50 mới
cần. Hệ số 1.65 tương ứng mức phục vụ 95% (cứ 20 chu kỳ nhập hàng thì chấp nhận
cháy hàng 1 lần) - nới lên 2.33 là 99% nhưng vốn nằm trong kho tăng theo.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models
from ..dependencies import (
    PERMISSION_INVENTORY,
    PERMISSION_REPORT,
    has_cost_visibility,
    require_any_staff_permission,
    require_shop_access,
)
from . import inventory_service, order_service

# Kỳ phân tích. 30 ngày là thỏa hiệp: ngắn hơn thì một tuần lễ tết cũng đủ làm
# lệch, dài hơn thì hàng theo mùa bị san phẳng mất.
SO_NGAY_PHAN_TICH = 30

# Bao lâu kể từ lúc gọi nhà cung cấp thì hàng về tới kệ. 3 ngày là mặc định cho
# tạp hóa nhỏ ở thành phố; chủ shop chỉnh được qua tham số.
THOI_GIAN_DAT_HANG_MAC_DINH = 3

# Nhập một lần thì muốn đủ bán bao nhiêu ngày nữa.
MUON_DU_CHO_MAC_DINH = 7

# Mức phục vụ 95%.
HE_SO_AN_TOAN = 1.65

# Dưới ngần này ngày có phát sinh bán thì con số chỉ là gợi ý, không phải dự
# báo - giao diện phải nói ra điều đó thay vì để chủ shop tin là chắc chắn.
NGUONG_DU_LIEU_YEU = 5

# Trạng thái, xếp theo mức gấp giảm dần.
TT_HET_HANG = "HET_HANG"        # tồn 0 mà vẫn đang bán được
TT_NGUY_CAP = "NGUY_CAP"        # hết trước khi hàng mới kịp về
TT_CAN_NHAP = "CAN_NHAP"        # đủ qua thời gian đặt hàng, chưa đủ tới đích
TT_ON_DINH = "ON_DINH"
TT_KHONG_BAN = "KHONG_BAN"      # kỳ vừa rồi không bán được món nào

_VIETNAM_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

# Đơn ĐÃ HỦY là đơn duy nhất được hoàn tồn kho, nên cũng là đơn duy nhất không
# tính vào tốc độ bán. CỐ Ý khác báo cáo doanh thu (chỉ đếm PAID): ở đây câu hỏi
# là "hàng rời kệ nhanh cỡ nào", mà hàng bán ghi nợ (DEBT) hay đơn chờ chuyển
# khoản (PENDING) thì khách đã cầm về rồi - kệ trống y như đơn đã trả tiền.
# Đừng "sửa" thành PAID-only: làm vậy là dự báo thiếu đúng bằng phần bán nợ.
_TRANG_THAI_KHONG_TINH = (order_service.STATUS_CANCELLED,)


def _hom_nay_vn() -> date:
    return datetime.now(_VIETNAM_TZ).date()


def _dau_ngay_vn_sang_utc(ngay: date) -> datetime:
    """00:00 ngày Việt Nam -> UTC-naive, cùng chuẩn lưu ``created_at``.

    Cùng quy ước với ``report_service._dau_ngay_viet_nam_sang_utc``. Hai chỗ
    PHẢI cho ra cùng một kết quả, nếu không màn Dự Báo và màn Thống Kê sẽ đếm
    hai khoảng thời gian khác nhau rồi cãi nhau về cùng một ngày. Có
    ``test_moc_gio_khop_voi_report_service`` giữ điều đó.
    """
    local = datetime.combine(ngay, datetime.min.time(), tzinfo=_VIETNAM_TZ)
    return local.astimezone(timezone.utc).replace(tzinfo=None)


def _ngay_vn(cot):
    """Cột datetime UTC -> ngày lịch Việt Nam (xem report_service._ngay_vn)."""
    return func.date(cot, "+7 hours")


def _da_ban_theo_ngay(
    db: Session, shop_id: int, moc_dau: datetime, moc_cuoi: datetime
) -> Dict[int, Dict[str, int]]:
    """{product_id: {ngày: số lượng}} - số hàng RỜI KỆ trong kỳ.

    Đã trừ phần khách trả và được xếp lại lên kệ. Hàng trả về mà hỏng
    (``restocked=False``) thì vẫn tính là đã bán: nó rời kệ thật và không quay
    lại bán cho người khác được, nên vẫn phải nhập bù.
    """
    ket_qua: Dict[int, Dict[str, int]] = {}

    ngay_ban = _ngay_vn(models.Order.created_at)
    ban = (
        db.query(
            models.OrderItem.product_id,
            ngay_ban,
            func.sum(models.OrderItem.quantity),
        )
        .join(models.Order, models.Order.id == models.OrderItem.order_id)
        .filter(
            models.Order.shop_id == shop_id,
            models.Order.status.notin_(_TRANG_THAI_KHONG_TINH),
            models.Order.created_at >= moc_dau,
            models.Order.created_at < moc_cuoi,
            models.OrderItem.product_id.isnot(None),
        )
        .group_by(models.OrderItem.product_id, ngay_ban)
        .all()
    )
    for product_id, ngay, so_luong in ban:
        if not ngay:
            continue
        ket_qua.setdefault(product_id, {})
        ket_qua[product_id][ngay] = ket_qua[product_id].get(ngay, 0) + int(so_luong or 0)

    # Trả hàng tính theo NGÀY TRẢ chứ không phải ngày bán, cùng lý do với
    # `report_service._loc_khoang_ngay`: hàng quay lại kệ hôm nay thì hôm nay
    # mới có hàng để bán, không phải tháng trước.
    ngay_tra = _ngay_vn(models.OrderReturn.created_at)
    tra = (
        db.query(
            models.OrderReturnItem.product_id,
            ngay_tra,
            func.sum(models.OrderReturnItem.quantity),
        )
        .join(
            models.OrderReturn,
            models.OrderReturn.id == models.OrderReturnItem.return_id,
        )
        .filter(
            models.OrderReturn.shop_id == shop_id,
            models.OrderReturnItem.restocked.is_(True),
            models.OrderReturn.created_at >= moc_dau,
            models.OrderReturn.created_at < moc_cuoi,
            models.OrderReturnItem.product_id.isnot(None),
        )
        .group_by(models.OrderReturnItem.product_id, ngay_tra)
        .all()
    )
    for product_id, ngay, so_luong in tra:
        if not ngay or product_id not in ket_qua:
            continue
        ket_qua[product_id][ngay] = ket_qua[product_id].get(ngay, 0) - int(so_luong or 0)

    return ket_qua


def _nha_cung_cap_gan_nhat(db: Session, shop_id: int) -> Dict[int, Dict[str, Any]]:
    """{product_id: nhà cung cấp của phiếu nhập ĐÃ XÁC NHẬN gần nhất}.

    Chỉ đếm phiếu ``POSTED``: phiếu nháp chưa vào kho, chưa sinh công nợ, và có
    thể bị sửa hoặc bỏ - gợi ý theo nó là gợi ý theo một thứ chưa xảy ra.
    """
    hang = (
        db.query(
            models.PurchaseReceiptItem.product_id,
            models.Supplier.id,
            models.Supplier.name,
            models.Supplier.phone,
            models.PurchaseReceiptItem.unit_cost,
            models.PurchaseReceipt.received_date,
        )
        .join(
            models.PurchaseReceipt,
            models.PurchaseReceipt.id == models.PurchaseReceiptItem.receipt_id,
        )
        .join(
            models.Supplier,
            models.Supplier.id == models.PurchaseReceipt.supplier_id,
        )
        .filter(
            models.PurchaseReceipt.shop_id == shop_id,
            models.PurchaseReceipt.status == "POSTED",
        )
        .order_by(
            models.PurchaseReceipt.received_date.desc(),
            models.PurchaseReceipt.id.desc(),
        )
        .all()
    )
    gan_nhat: Dict[int, Dict[str, Any]] = {}
    for product_id, ncc_id, ten, dien_thoai, don_gia, ngay_nhan in hang:
        # Đã sắp xếp mới nhất trước nên dòng đầu tiên gặp là dòng cần giữ.
        if product_id in gan_nhat:
            continue
        gan_nhat[product_id] = {
            "id": ncc_id,
            "ten": ten,
            "dien_thoai": dien_thoai,
            "don_gia_lan_truoc": int(don_gia or 0),
            "ngay_nhap_gan_nhat": ngay_nhan,
        }
    return gan_nhat


def _do_lech_chuan(so_lieu: List[float]) -> float:
    """Độ lệch chuẩn của mẫu. Dưới 2 điểm dữ liệu thì coi như không dao động."""
    if len(so_lieu) < 2:
        return 0.0
    trung_binh = sum(so_lieu) / len(so_lieu)
    phuong_sai = sum((x - trung_binh) ** 2 for x in so_lieu) / (len(so_lieu) - 1)
    return math.sqrt(phuong_sai)


def _phan_loai(
    ton: int, van_toc: float, con_ban_duoc_ngay: Optional[float], thoi_gian_dat_hang: int
) -> str:
    if van_toc <= 0:
        return TT_KHONG_BAN
    if ton <= 0:
        return TT_HET_HANG
    if con_ban_duoc_ngay is not None and con_ban_duoc_ngay < thoi_gian_dat_hang:
        return TT_NGUY_CAP
    if con_ban_duoc_ngay is not None and con_ban_duoc_ngay < thoi_gian_dat_hang + 7:
        return TT_CAN_NHAP
    return TT_ON_DINH


def du_bao_nhap_hang(
    db: Session,
    current_user: models.User,
    shop_id: int,
    *,
    thoi_gian_dat_hang: int = THOI_GIAN_DAT_HANG_MAC_DINH,
    muon_du_cho: int = MUON_DU_CHO_MAC_DINH,
    so_ngay_phan_tich: int = SO_NGAY_PHAN_TICH,
) -> Dict[str, Any]:
    """Danh sách sản phẩm cần nhập, xếp gấp nhất lên đầu.

    Giá vốn và tổng tiền phải bỏ ra chỉ có mặt khi người xem được phép thấy giá
    vốn (`has_cost_visibility`). Không có quyền thì các khóa đó **bị bỏ hẳn**
    khỏi phản hồi chứ không trả 0 - trả 0 là nói dối, còn thiếu khóa là giấu
    (bẫy 13 trong KIEN_TRUC.md).
    """
    shop = require_shop_access(db, shop_id, current_user)
    # Dự báo nhập hàng là việc của kho. MANAGER có sẵn cả hai quyền; thu ngân
    # (chỉ có PERMISSION_SALE) không cần và không được xem.
    require_any_staff_permission(current_user, PERMISSION_INVENTORY, PERMISSION_REPORT)

    xem_duoc_gia_von = has_cost_visibility(shop, current_user)

    den_ngay = _hom_nay_vn()
    tu_ngay = den_ngay - timedelta(days=so_ngay_phan_tich - 1)
    moc_dau = _dau_ngay_vn_sang_utc(tu_ngay)
    moc_cuoi = _dau_ngay_vn_sang_utc(den_ngay + timedelta(days=1))

    ban_theo_ngay = _da_ban_theo_ngay(db, shop_id, moc_dau, moc_cuoi)
    ncc_theo_sp = _nha_cung_cap_gan_nhat(db, shop_id)

    san_pham = (
        db.query(models.Product)
        .filter(
            models.Product.shop_id == shop_id,
            models.Product.is_active.is_(True),
        )
        .all()
    )

    danh_sach: List[Dict[str, Any]] = []
    tong_tien = 0
    for prod in san_pham:
        theo_ngay = ban_theo_ngay.get(prod.id, {})
        # Chuỗi ngày phải điền đủ số 0 cho ngày không bán: bỏ qua chúng là chia
        # cho số ngày có bán, và mọi sản phẩm bỗng thành bán chạy.
        chuoi = [float(theo_ngay.get(str(tu_ngay + timedelta(days=i)), 0))
                 for i in range(so_ngay_phan_tich)]
        da_ban = int(sum(chuoi))
        so_ngay_co_ban = sum(1 for x in chuoi if x > 0)
        van_toc = max(0.0, da_ban / so_ngay_phan_tich)

        # Tồn KHẢ DỤNG, đã loại phần quá hạn với hàng theo lô (bẫy 21). Dùng
        # `prod.stock` ở đây là tính cả hàng hết hạn vào số bán được, rồi báo
        # "còn nhiều, khỏi nhập" trong khi kệ toàn hàng phải hủy.
        ton = inventory_service.ton_kha_dung(db, prod)

        con_ban_duoc_ngay = round(ton / van_toc, 1) if van_toc > 0 else None
        dem_du_phong = (
            math.ceil(HE_SO_AN_TOAN * _do_lech_chuan(chuoi) * math.sqrt(thoi_gian_dat_hang))
            if van_toc > 0
            else 0
        )
        can_nhap = 0
        if van_toc > 0:
            can_nhap = math.ceil(
                van_toc * (thoi_gian_dat_hang + muon_du_cho) + dem_du_phong - ton
            )
            can_nhap = max(0, can_nhap)

        dong: Dict[str, Any] = {
            "product_id": prod.id,
            "ten": prod.name,
            "ma": prod.code,
            "ton_kho": ton,
            "ton_tong": int(prod.stock or 0),
            "theo_lo": bool(prod.track_batches),
            "da_ban_trong_ky": da_ban,
            "ban_moi_ngay": round(van_toc, 2),
            "con_ban_duoc_ngay": con_ban_duoc_ngay,
            "dem_du_phong": dem_du_phong,
            "can_nhap": can_nhap,
            "so_ngay_co_ban": so_ngay_co_ban,
            "du_lieu_yeu": 0 < so_ngay_co_ban < NGUONG_DU_LIEU_YEU,
            "trang_thai": _phan_loai(ton, van_toc, con_ban_duoc_ngay, thoi_gian_dat_hang),
            "nha_cung_cap": ncc_theo_sp.get(prod.id),
        }

        if xem_duoc_gia_von:
            # Giá vốn NULL là "chưa ai khai", không phải 0 (bẫy 13): không có
            # thì không đoán ra tiền, để None và giao diện nói "chưa khai".
            don_gia = prod.cost_price
            ncc = ncc_theo_sp.get(prod.id)
            if don_gia is None and ncc:
                don_gia = ncc["don_gia_lan_truoc"] or None
            dong["gia_von"] = don_gia
            dong["tien_can_bo_ra"] = (
                int(round(don_gia * can_nhap)) if don_gia is not None else None
            )
            if dong["tien_can_bo_ra"]:
                tong_tien += dong["tien_can_bo_ra"]

        danh_sach.append(dong)

    # Gấp nhất lên đầu: hết hàng trước, rồi tới số ngày còn bán được ít nhất.
    # Hàng không bán được món nào xếp cuối - nó là bài toán xả hàng, không phải
    # bài toán nhập hàng.
    thu_tu = {
        TT_HET_HANG: 0, TT_NGUY_CAP: 1, TT_CAN_NHAP: 2,
        TT_ON_DINH: 3, TT_KHONG_BAN: 4,
    }
    danh_sach.sort(
        key=lambda d: (
            thu_tu[d["trang_thai"]],
            d["con_ban_duoc_ngay"] if d["con_ban_duoc_ngay"] is not None else 1e9,
            -d["da_ban_trong_ky"],
        )
    )

    ket_qua: Dict[str, Any] = {
        "shop_id": shop_id,
        "tu_ngay": tu_ngay.isoformat(),
        "den_ngay": den_ngay.isoformat(),
        "so_ngay_phan_tich": so_ngay_phan_tich,
        "thoi_gian_dat_hang": thoi_gian_dat_hang,
        "muon_du_cho": muon_du_cho,
        "xem_duoc_gia_von": xem_duoc_gia_von,
        "so_mat_hang_can_nhap": sum(1 for d in danh_sach if d["can_nhap"] > 0),
        "danh_sach": danh_sach,
    }
    if xem_duoc_gia_von:
        ket_qua["tong_tien_can_nhap"] = tong_tien
        ket_qua["so_mat_hang_chua_khai_gia_von"] = sum(
            1 for d in danh_sach if d["can_nhap"] > 0 and d.get("gia_von") is None
        )
    return ket_qua
