"""Hỏi đáp báo cáo bằng tiếng Việt.

**Máy KHÔNG tự viết câu lệnh lấy dữ liệu.** Nó chỉ làm đúng một việc: đọc câu
hỏi rồi chọn xem nên gọi báo cáo nào trong số các báo cáo đã có sẵn, và điền
khoảng thời gian. Việc chạy số vẫn do `report_service` / `forecast_service` /
`clearance_service` làm.

Vì sao không cho máy tự sinh SQL — cách mà mọi bài viết về "hỏi đáp cơ sở dữ
liệu bằng AI" đều dạy:

1. **App này phục vụ nhiều cửa hàng.** Gần như mọi bảng đều có `shop_id`. Chỉ
   cần một câu lệnh quên điều kiện đó là chủ shop A đọc được doanh thu shop B.
   Sandbox chỉ-đọc chặn được việc GHI, nhưng không chặn được việc ĐỌC NHẦM.
2. **Giá vốn có vòng người xem hẹp hơn doanh thu** (`has_cost_visibility`). Đi
   qua service là đi qua đúng các hàng rào đó; SQL tự sinh thì đi vòng qua hết.
3. **Múi giờ.** `created_at` lưu theo UTC, báo cáo quy đổi bằng
   `date(created_at,'+7 hours')`. Máy không biết luật nội bộ này, và "hôm nay
   bán được bao nhiêu" sẽ lệch 7 tiếng - số của trợ lý khác số của màn Thống Kê,
   rồi không ai tin cái nào nữa.

Đổi lại, bộ hiểu câu hỏi ở đây là **so khớp mẫu chạy ngay trong máy chủ**:
không gọi mạng, không tốn tiền, không gửi dữ liệu cửa hàng đi đâu, và trả lời
dưới 50ms thay vì 1-2 giây. Câu nào không khớp thì nói thẳng là chưa hiểu và
gợi ý các câu hỏi làm được - **không đoán bừa**. Một con số bịa ra trông y hệt
một con số thật.

Chỗ cắm mô hình ngôn ngữ (nếu sau này muốn): `_doan_y_dinh()` trả về None là
lúc duy nhất cần tới nó, và việc của nó cũng chỉ là chọn một `Y_DINH_*` + khoảng
ngày, KHÔNG phải sinh câu lệnh. Mọi thứ sau đó giữ nguyên.
"""
from __future__ import annotations

import re
import time
import unicodedata
from datetime import date, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from .. import models
from ..core import thoi_gian
from ..core.config import GEMINI_TRAN_MOI_NGAY, GEMINI_TRAN_MOI_PHUT, log_to_file
from ..core.i18n import tr
from ..dependencies import require_shop_access
from . import (
    clearance_service,
    forecast_service,
    gemini_service,
    report_service,
    subscription_service,
)

# Ý định: mỗi cái ứng với đúng một báo cáo đã có.
Y_DINH_DOANH_THU = "DOANH_THU"
Y_DINH_SO_DON = "SO_DON"
Y_DINH_SO_SANH_TUAN = "SO_SANH_TUAN"
Y_DINH_BAN_CHAY = "BAN_CHAY"
Y_DINH_SAP_HET_HAN = "SAP_HET_HAN"
Y_DINH_CAN_NHAP = "CAN_NHAP"
Y_DINH_HANG_E = "HANG_E"
Y_DINH_CONG_NO = "CONG_NO"
Y_DINH_LAI = "LAI"

CAU_HOI_TOI_DA = 200


def _bo_dau(chuoi: str) -> str:
    """'Doanh thu hôm nay' -> 'doanh thu hom nay'.

    Người dùng gõ nhanh trên điện thoại thường không bỏ dấu. So khớp trên bản
    không dấu để 'hom nay ban duoc bao nhieu' cũng hiểu được.
    """
    tach = unicodedata.normalize("NFD", chuoi.lower())
    khong_dau = "".join(c for c in tach if unicodedata.category(c) != "Mn")
    khong_dau = khong_dau.replace("đ", "d")
    return re.sub(r"\s+", " ", khong_dau).strip()


# --- Khoảng thời gian ---
# Đặt cụm DÀI trước cụm ngắn: "tuần trước" phải được thử trước "tuần", nếu
# không "tuần trước" sẽ khớp nhầm thành "tuần này".
_MAU_THOI_GIAN: List[Tuple[str, str]] = [
    (r"\bhom qua\b", "HOM_QUA"),
    (r"\bhom nay\b|\bbua nay\b|\bngay hom nay\b", "HOM_NAY"),
    (r"\btuan truoc\b|\btuan roi\b|\btuan vua roi\b", "TUAN_TRUOC"),
    (r"\btuan nay\b|\btrong tuan\b", "TUAN_NAY"),
    (r"\bthang truoc\b", "THANG_TRUOC"),
    (r"\bthang nay\b|\btrong thang\b", "THANG_NAY"),
    (r"\b(\d+)\s*ngay (qua|nay|vua roi|gan day)\b", "N_NGAY"),
]


def _khoang_ngay(cau_khong_dau: str, mac_dinh: str = "HOM_NAY") -> Tuple[str, date, date, str]:
    """Đọc khoảng thời gian trong câu hỏi. Trả (mã, từ ngày, đến ngày, nhãn)."""
    hom_nay = thoi_gian.hom_nay_vn()
    ma = mac_dinh
    so_ngay = 7
    for mau, ten in _MAU_THOI_GIAN:
        khop = re.search(mau, cau_khong_dau)
        if khop:
            ma = ten
            if ten == "N_NGAY":
                so_ngay = max(1, min(365, int(khop.group(1))))
            break

    if ma == "HOM_NAY":
        return ma, hom_nay, hom_nay, "hôm nay"
    if ma == "HOM_QUA":
        h = hom_nay - timedelta(days=1)
        return ma, h, h, "hôm qua"
    if ma == "TUAN_NAY":
        dau = hom_nay - timedelta(days=hom_nay.weekday())
        return ma, dau, hom_nay, "tuần này"
    if ma == "TUAN_TRUOC":
        dau_tuan_nay = hom_nay - timedelta(days=hom_nay.weekday())
        dau = dau_tuan_nay - timedelta(days=7)
        return ma, dau, dau_tuan_nay - timedelta(days=1), "tuần trước"
    if ma == "THANG_NAY":
        return ma, hom_nay.replace(day=1), hom_nay, "tháng này"
    if ma == "THANG_TRUOC":
        dau_thang_nay = hom_nay.replace(day=1)
        cuoi = dau_thang_nay - timedelta(days=1)
        return ma, cuoi.replace(day=1), cuoi, "tháng trước"
    dau = hom_nay - timedelta(days=so_ngay - 1)
    return "N_NGAY", dau, hom_nay, f"{so_ngay} ngày qua"


# --- Ý định ---
# Thứ tự QUAN TRỌNG: câu càng cụ thể càng phải đứng trước. "lãi bao nhiêu" phải
# được thử trước "bao nhiêu tiền", nếu không nó rơi vào doanh thu.
_MAU_Y_DINH: List[Tuple[str, str]] = [
    (r"\bso sanh\b.*\btuan\b|\btuan nay.*tuan truoc\b|\btuan truoc.*tuan nay\b",
     Y_DINH_SO_SANH_TUAN),
    (r"\blai\b|\bloi nhuan\b|\blai gop\b|\blo hay lai\b", Y_DINH_LAI),
    (r"\bsap het han\b|\bhet han\b|\bhan su dung\b|\bcan date\b", Y_DINH_SAP_HET_HAN),
    # `\bsap het\b` đứng SAU mẫu hạn sử dụng ở trên nên "sắp hết hạn" đã được
    # nhận ở đó rồi; ở đây nó bắt các cách nói khác thứ tự như "hàng nào sắp hết".
    (r"\bsap het hang\b|\bsap het\b|\bcan nhap\b|\bnhap hang\b|\bdat hang\b"
     r"|\bhet hang\b|\bnhap gi\b|\bgoi hang\b",
     Y_DINH_CAN_NHAP),
    (r"\bban chay\b|\bban duoc nhieu nhat\b|\bton hang nao chay\b|\btop\b|\bhut hang\b",
     Y_DINH_BAN_CHAY),
    (r"\be\b|\bnam e\b|\bton kho lau\b|\bkhong ai mua\b|\bkhong ban duoc\b|\bchon von\b|\bdong von\b",
     Y_DINH_HANG_E),
    (r"\bno\b|\bcong no\b|\bkhach no\b|\bphai thu\b|\bthu no\b", Y_DINH_CONG_NO),
    (r"\bbao nhieu don\b|\bmay don\b|\bso don\b|\bso luong don\b|\bdon hang\b", Y_DINH_SO_DON),
    (r"\bdoanh thu\b|\bban duoc bao nhieu\b|\bthu ve\b|\bthu (duoc )?bao nhieu\b"
     r"|\bban duoc\b|\bbao nhieu tien\b|\bduoc bao nhieu\b|\bkiem duoc\b|\bthu nhap\b",
     Y_DINH_DOANH_THU),
]


# --- Tầng dự phòng Gemini: bảy lớp chặn, xếp từ rẻ tới đắt ---
# Lớp 1 (mạnh nhất) là chính bộ so khớp ở trên: câu thường gặp không bao giờ
# chạm tới Gemini. Sáu lớp còn lại nằm trong `_thu_hoi_gemini`.

# Cụm chữ ứng với từng mã khoảng thời gian. Gemini trả về MÃ, rồi mã đó được
# ghép vào câu để `_khoang_ngay` đọc lại - CỐ Ý đi qua đúng một bộ đọc ngày
# thay vì viết bộ thứ hai, vì hai bộ rồi sẽ lệch nhau.
_MA_SANG_CHU = {
    "HOM_NAY": "hom nay",
    "HOM_QUA": "hom qua",
    "TUAN_NAY": "tuan nay",
    "TUAN_TRUOC": "tuan truoc",
    "THANG_NAY": "thang nay",
    "THANG_TRUOC": "thang truoc",
    "N_NGAY": "7 ngay qua",
}

# Nhớ câu đã hỏi: Gemini giải được một cách hỏi lạ thì lần sau ai hỏi y hệt là
# dùng lại, không tốn lượt. CHỈ nhớ "câu hỏi -> tên báo cáo", không nhớ dữ liệu
# và không nhớ câu trả lời, nên cache dùng chung được cho mọi shop mà không lộ
# gì. Nằm trong RAM: mất khi restart cũng chỉ là tốn lại vài lượt.
_NHO_CAU_HOI: Dict[str, Tuple[str, str]] = {}
_NHO_TOI_DA = 500

# Chống giữ Enter. CỐ Ý để trong RAM chứ không trong DB, khác với bộ đếm ngày:
# đây là chống bấm dồn trong vài giây, còn hàng rào tiền thật là trần mỗi ngày.
_DAU_VET_PHUT: Dict[Tuple[int, int], List[float]] = {}


def _con_han_muc(db: Session, shop_id: int) -> Tuple[int, int]:
    """(đã dùng, trần) của shop trong ngày nghiệp vụ hôm nay."""
    ngay = thoi_gian.hom_nay_vn_str()
    da_dung = db.execute(
        text(
            "SELECT so_luot FROM assistant_ai_usage "
            "WHERE shop_id = :s AND ngay = :n"
        ),
        {"s": shop_id, "n": ngay},
    ).scalar()
    return int(da_dung or 0), GEMINI_TRAN_MOI_NGAY


def _tru_mot_luot(db: Session, shop_id: int) -> bool:
    """Trừ một lượt, trả False khi đã hết trần.

    Kiểm-rồi-ghi bằng hai câu lệnh riêng thì hai request cùng lúc đều thấy
    "còn 1 lượt" rồi cùng gọi. Ở đây điều kiện `so_luot < :tran` nằm NGAY TRONG
    câu UPDATE nên SQLite chỉ cho đúng một bên thắng.
    """
    ngay = thoi_gian.hom_nay_vn_str()
    db.execute(
        text(
            "INSERT OR IGNORE INTO assistant_ai_usage (shop_id, ngay, so_luot) "
            "VALUES (:s, :n, 0)"
        ),
        {"s": shop_id, "n": ngay},
    )
    ket = db.execute(
        text(
            "UPDATE assistant_ai_usage SET so_luot = so_luot + 1 "
            "WHERE shop_id = :s AND ngay = :n AND so_luot < :tran"
        ),
        {"s": shop_id, "n": ngay, "tran": GEMINI_TRAN_MOI_NGAY},
    )
    db.commit()
    return ket.rowcount > 0


def _qua_nhanh(user_id: int, shop_id: int) -> bool:
    khoa = (user_id, shop_id)
    bay_gio = time.monotonic()
    dau_vet = [t for t in _DAU_VET_PHUT.get(khoa, []) if bay_gio - t < 60]
    if len(dau_vet) >= GEMINI_TRAN_MOI_PHUT:
        _DAU_VET_PHUT[khoa] = dau_vet
        return True
    dau_vet.append(bay_gio)
    _DAU_VET_PHUT[khoa] = dau_vet
    return False


def _dang_rac(cau_khong_dau: str) -> bool:
    """Chuỗi không có lấy một chữ cái thì đừng tốn lượt gọi ra Google."""
    return not re.search(r"[a-z]{2}", cau_khong_dau)


def _thu_hoi_gemini(
    db: Session, current_user: models.User, shop_id: int, cau_khong_dau: str
) -> Optional[Tuple[str, str]]:
    """Sáu lớp chặn trước khi thực sự gọi ra Google. Trả None là bỏ qua."""
    if not gemini_service.dang_bat():
        return None                       # chưa cắm key -> tính năng không tồn tại
    if _dang_rac(cau_khong_dau):
        return None
    if cau_khong_dau in _NHO_CAU_HOI:
        return _NHO_CAU_HOI[cau_khong_dau]
    try:
        subscription_service.require_pro(db, shop_id)
    except HTTPException:
        return None                       # shop Free: im lặng lùi về "chưa hiểu"
    if _qua_nhanh(current_user.id, shop_id):
        return None
    if not _tru_mot_luot(db, shop_id):
        return None                       # hết trần ngày

    ket = gemini_service.phan_loai(
        cau_khong_dau, list(_BANG_XU_LY.keys()), list(_MA_SANG_CHU.keys())
    )
    if ket is None:
        return None
    if len(_NHO_CAU_HOI) < _NHO_TOI_DA:
        _NHO_CAU_HOI[cau_khong_dau] = ket
    return ket


def _doan_y_dinh(cau_khong_dau: str) -> Optional[str]:
    """Câu hỏi -> ý định, hoặc None khi không chắc.

    KHÔNG có nhánh "đoán đại cái gần nhất". Trả lời sai một con số tiền còn tệ
    hơn nói "tôi chưa hiểu": người hỏi không có cách nào biết là nó sai.
    """
    for mau, y_dinh in _MAU_Y_DINH:
        if re.search(mau, cau_khong_dau):
            return y_dinh
    return None


def _tien(so: float) -> str:
    return f"{round(so):,.0f}đ".replace(",", ".")


def _so(so: float) -> str:
    return f"{round(so):,.0f}".replace(",", ".")


# --- Từng ý định ---
def _tra_loi_doanh_thu(db, user, shop_id, cau, chi_dem_don=False) -> Dict[str, Any]:
    _, tu, den, nhan = _khoang_ngay(cau)
    so_lieu = report_service.shop_stats(
        db, user, shop_id, tu_ngay=tu.isoformat(), den_ngay=den.isoformat()
    )
    don = int(so_lieu.get("total_orders") or 0)
    tien = float(so_lieu.get("total_revenue") or 0)
    # `total_orders` đếm MỌI đơn, còn `total_revenue` chỉ đếm đơn ĐÃ THANH TOÁN.
    # Màn Thống Kê để hai con số ở hai ô riêng nên người xem thấy ngay chúng
    # khác nhau; một câu văn dán liền hai số lại thì mất mất điều đó và đọc ra
    # thành vô lý ("bán được 1 đơn, thu về 0đ"). Nên khi hai số không khớp thì
    # phải nói THẲNG lý do.
    if chi_dem_don:
        loi = (
            f"{nhan.capitalize()} có {_so(don)} đơn."
            if don
            else f"{nhan.capitalize()} chưa có đơn nào."
        )
        if don and tien <= 0:
            loi += " Chưa đơn nào thu được tiền (còn chờ thanh toán hoặc ghi nợ)."
    elif don and tien > 0:
        loi = f"{nhan.capitalize()} có {_so(don)} đơn, đã thu về {_tien(tien)}."
    elif don:
        loi = (
            f"{nhan.capitalize()} có {_so(don)} đơn nhưng chưa thu được đồng nào "
            "— các đơn còn chờ thanh toán hoặc đang ghi nợ."
        )
    else:
        loi = f"{nhan.capitalize()} chưa bán được đơn nào."
    return {
        "tra_loi": loi,
        "chi_tiet": {"so_don": don, "doanh_thu": tien, "tu_ngay": tu.isoformat(),
                     "den_ngay": den.isoformat()},
        "nguon": "Thống kê",
    }


def _tra_loi_so_sanh_tuan(db, user, shop_id, cau) -> Dict[str, Any]:
    hom_nay = thoi_gian.hom_nay_vn()
    dau_tuan_nay = hom_nay - timedelta(days=hom_nay.weekday())
    dau_tuan_truoc = dau_tuan_nay - timedelta(days=7)

    nay = report_service.shop_stats(
        db, user, shop_id,
        tu_ngay=dau_tuan_nay.isoformat(), den_ngay=hom_nay.isoformat(),
    )
    truoc = report_service.shop_stats(
        db, user, shop_id,
        tu_ngay=dau_tuan_truoc.isoformat(),
        den_ngay=(dau_tuan_nay - timedelta(days=1)).isoformat(),
    )
    a = float(nay.get("total_revenue") or 0)
    b = float(truoc.get("total_revenue") or 0)

    if b <= 0:
        loi = (
            f"Tuần này thu {_tien(a)}. Tuần trước chưa có doanh thu nên "
            "chưa so sánh được."
        )
    else:
        chenh = (a - b) / b * 100
        huong = "tăng" if a >= b else "giảm"
        loi = (
            f"Tuần này thu {_tien(a)}, tuần trước {_tien(b)} — "
            f"{huong} {abs(chenh):.0f}%."
        )
        # Tuần này thường chưa hết, so nguyên tuần với tuần đủ 7 ngày là so lệch.
        if hom_nay.weekday() < 6:
            loi += f" (Tuần này mới tính tới {hom_nay.strftime('%d/%m')}.)"
    return {
        "tra_loi": loi,
        "chi_tiet": {"tuan_nay": a, "tuan_truoc": b},
        "nguon": "Thống kê",
    }


def _tra_loi_ban_chay(db, user, shop_id, cau) -> Dict[str, Any]:
    _, tu, den, nhan = _khoang_ngay(cau, mac_dinh="N_NGAY")
    so_lieu = report_service.shop_stats(
        db, user, shop_id, tu_ngay=tu.isoformat(), den_ngay=den.isoformat()
    )
    top = so_lieu.get("top_products") or []
    if not top:
        return {"tra_loi": f"{nhan.capitalize()} chưa bán được món nào.",
                "chi_tiet": None, "nguon": "Thống kê"}
    dau = top[0]
    ten = dau.get("name") or "?"
    sl = dau.get("qty") or 0
    return {
        "tra_loi": f"{nhan.capitalize()} bán chạy nhất là {ten} ({_so(sl)} cái).",
        "bang": top[:5],
        "nguon": "Thống kê",
    }


def _tra_loi_sap_het_han(db, user, shop_id, cau) -> Dict[str, Any]:
    from . import catalog_service

    d = catalog_service.danh_sach_lo(db, user, shop_id, sap_het_han_trong=30)
    het = d.get("expired") or []
    sap = d.get("expiring_soon") or []
    if not het and not sap:
        return {"tra_loi": "Không có lô nào sắp hoặc đã hết hạn trong 30 ngày tới.",
                "chi_tiet": None, "nguon": "Hạn sử dụng"}
    phan = []
    if sap:
        ten = ", ".join(str(r.get("product_name")) for r in sap[:3])
        phan.append(f"{len(sap)} lô sắp hết hạn ({ten}{'...' if len(sap) > 3 else ''})")
    if het:
        phan.append(f"{len(het)} lô ĐÃ hết hạn, cần hủy")
    return {
        "tra_loi": "Có " + " và ".join(phan) + ".",
        "bang": (het + sap)[:10],
        "nguon": "Hạn sử dụng",
    }


def _tra_loi_can_nhap(db, user, shop_id, cau) -> Dict[str, Any]:
    d = forecast_service.du_bao_nhap_hang(db, user, shop_id)
    can = [r for r in d["danh_sach"] if r["can_nhap"] > 0]
    if not can:
        return {"tra_loi": "Chưa có mặt hàng nào cần nhập thêm.",
                "chi_tiet": None, "nguon": "Dự báo nhập hàng"}
    dau = can[0]
    loi = f"Có {len(can)} mặt hàng cần nhập. Gấp nhất là {dau['ten']}"
    if dau["con_ban_duoc_ngay"] is not None:
        loi += f" (chỉ còn đủ bán {dau['con_ban_duoc_ngay']} ngày)"
    loi += f", nên nhập {_so(dau['can_nhap'])}."
    if d.get("tong_tien_can_nhap"):
        loi += f" Tổng tiền cần chuẩn bị khoảng {_tien(d['tong_tien_can_nhap'])}."
    return {"tra_loi": loi, "bang": can[:10], "nguon": "Dự báo nhập hàng"}


def _tra_loi_hang_e(db, user, shop_id, cau) -> Dict[str, Any]:
    d = clearance_service.de_xuat_xa_hang(db, user, shop_id)
    ds = d["danh_sach"]
    if not ds:
        return {"tra_loi": "Không có mặt hàng nào đang nằm ế. Kho đang đi đều.",
                "chi_tiet": None, "nguon": "Xả hàng tồn"}
    dau = ds[0]
    loi = f"Có {len(ds)} mặt hàng đang nằm, chôn khoảng {_tien(d['tong_von_dang_dong'])}."
    loi += f" Nặng nhất là {dau['ten']}"
    if dau.get("gia_de_xuat"):
        loi += f", nên hạ từ {_tien(dau['gia_hien_tai'])} xuống {_tien(dau['gia_de_xuat'])}"
        loi += f" (vẫn lãi {_tien(dau['lai_moi_cai_sau_giam'])} mỗi cái)."
    else:
        loi += "."
    return {"tra_loi": loi, "bang": ds[:10], "nguon": "Xả hàng tồn"}


def _tra_loi_cong_no(db, user, shop_id, cau) -> Dict[str, Any]:
    so_lieu = report_service.shop_stats(db, user, shop_id)
    no = float(so_lieu.get("receivable_amount") or 0)
    loi = (
        f"Khách đang nợ tổng cộng {_tien(no)}."
        if no > 0
        else "Không có khoản nợ nào của khách."
    )
    return {"tra_loi": loi, "chi_tiet": {"phai_thu": no}, "nguon": "Thống kê"}


def _tra_loi_lai(db, user, shop_id, cau) -> Dict[str, Any]:
    _, tu, den, nhan = _khoang_ngay(cau, mac_dinh="THANG_NAY")
    so_lieu = report_service.shop_stats(
        db, user, shop_id, tu_ngay=tu.isoformat(), den_ngay=den.isoformat()
    )
    # `shop_stats` BỎ HẲN nhóm field lãi khi người xem không được thấy giá vốn
    # (bẫy 13). Thiếu khóa nghĩa là không có quyền, không phải lãi bằng 0.
    if "gross_profit" not in so_lieu:
        raise HTTPException(
            status_code=403,
            detail=tr("Chỉ chủ cửa hàng mới xem được giá vốn và lãi"),
        )
    lai = float(so_lieu.get("gross_profit") or 0)
    thieu = int(so_lieu.get("orders_missing_cost") or 0)
    loi = f"Lãi gộp {nhan} khoảng {_tien(lai)}."
    if thieu:
        loi += (
            f" Con số này đã loại {thieu} đơn còn hàng chưa khai giá vốn, "
            "nên thực tế có thể cao hơn."
        )
    return {"tra_loi": loi, "chi_tiet": {"lai_gop": lai}, "nguon": "Thống kê"}


_BANG_XU_LY: Dict[str, Callable] = {
    Y_DINH_DOANH_THU: lambda db, u, s, c: _tra_loi_doanh_thu(db, u, s, c),
    Y_DINH_SO_DON: lambda db, u, s, c: _tra_loi_doanh_thu(db, u, s, c, chi_dem_don=True),
    Y_DINH_SO_SANH_TUAN: _tra_loi_so_sanh_tuan,
    Y_DINH_BAN_CHAY: _tra_loi_ban_chay,
    Y_DINH_SAP_HET_HAN: _tra_loi_sap_het_han,
    Y_DINH_CAN_NHAP: _tra_loi_can_nhap,
    Y_DINH_HANG_E: _tra_loi_hang_e,
    Y_DINH_CONG_NO: _tra_loi_cong_no,
    Y_DINH_LAI: _tra_loi_lai,
}

GOI_Y = [
    "Hôm nay bán được bao nhiêu?",
    "So sánh doanh thu tuần này với tuần trước",
    "Sản phẩm nào sắp hết hạn?",
    "Cần nhập hàng gì?",
    "Hàng nào đang nằm ế?",
    "Tháng này lãi bao nhiêu?",
    "Khách còn nợ bao nhiêu?",
]


def hoi_dap(
    db: Session, current_user: models.User, shop_id: int, cau_hoi: str
) -> Dict[str, Any]:
    """Trả lời một câu hỏi tiếng Việt bằng đúng các báo cáo đã có.

    **Hai loại "không được xem" phải xử lý khác nhau:**

    - *Không được vào shop này* -> ném 403/404 như mọi endpoint khác. Trả 200
      kèm một câu từ chối lịch sự nghe thì tử tế, nhưng nó biến một lần truy cập
      trái phép thành một request "thành công" trong log, và làm mờ đúng cái
      ranh giới mà cả app đang dựa vào. Vì vậy `require_shop_access` được gọi
      TƯỜNG MINH ở đây, trước khi làm bất cứ việc gì.
    - *Vào được shop nhưng không được xem phần này* (nhân viên hỏi về lãi) ->
      trả lời trong khung chat, KHÔNG kèm bất kỳ con số nào. Người hỏi là người
      của cửa hàng, họ xứng đáng nhận một câu trả lời thay vì một mã lỗi.

    Ngoài `require_shop_access`, ở đây KHÔNG có hàng rào phân quyền nào khác:
    mỗi báo cáo tự kiểm bằng hàng rào của nó (`require_staff_permission`,
    `has_cost_visibility`). Dựng thêm một lớp song song là tạo ra một bản sao sẽ
    lệch dần khỏi bản thật.
    """
    require_shop_access(db, shop_id, current_user)

    cau = (cau_hoi or "").strip()
    if not cau:
        raise HTTPException(status_code=400, detail=tr("Chưa có câu hỏi"))
    if len(cau) > CAU_HOI_TOI_DA:
        raise HTTPException(
            status_code=400,
            detail=tr("Câu hỏi quá dài, vui lòng hỏi ngắn gọn hơn"),
        )

    khong_dau = _bo_dau(cau)
    y_dinh = _doan_y_dinh(khong_dau)
    nho_gemini = False

    if y_dinh is None:
        # Chỉ tới đây mới nghĩ tới Gemini. Mọi câu hỏi thường gặp đã được trả
        # lời ở trên rồi, miễn phí và tức thì.
        tu_ai = _thu_hoi_gemini(db, current_user, shop_id, khong_dau)
        if tu_ai is not None:
            y_dinh, ma_khoang = tu_ai
            nho_gemini = True
            # Ghép cụm thời gian vào câu rồi để `_khoang_ngay` đọc lại, thay vì
            # viết bộ đọc ngày thứ hai cho nhánh AI - hai bộ rồi sẽ lệch nhau.
            if ma_khoang in _MA_SANG_CHU:
                khong_dau = f"{khong_dau} {_MA_SANG_CHU[ma_khoang]}"

    if y_dinh is None:
        # Ghi lại câu bị trượt để còn biết nên thêm mẫu nào. Đây là thứ làm lớp
        # phòng thủ mạnh dần lên: mỗi mẫu thêm vào là bớt một loại câu phải gọi
        # ra Google. Chỉ ghi CÂU HỎI, không ghi dữ liệu cửa hàng.
        log_to_file(f"[TRO LY] Chua hieu (shop {shop_id}): {cau}")
        return {
            "cau_hoi": cau,
            "hieu_duoc": False,
            "y_dinh": None,
            "tra_loi": "Tôi chưa hiểu câu này. Bạn thử hỏi theo một trong các cách dưới đây.",
            "goi_y": GOI_Y,
            "nguon": None,
        }

    try:
        ket_qua = _BANG_XU_LY[y_dinh](db, current_user, shop_id, khong_dau)
    except HTTPException as loi:
        # 403 từ hàng rào phân quyền: trả lời tử tế, KHÔNG kèm bất kỳ con số nào.
        if loi.status_code == 403:
            return {
                "cau_hoi": cau,
                "hieu_duoc": True,
                "y_dinh": y_dinh,
                "tra_loi": str(loi.detail),
                "goi_y": None,
                "nguon": None,
            }
        raise

    ket_qua.update({"cau_hoi": cau, "hieu_duoc": True, "y_dinh": y_dinh})
    ket_qua.setdefault("goi_y", None)
    # Nói ra khi câu trả lời đi qua AI: người dùng có quyền biết câu nào vừa
    # được gửi ra ngoài, và đó cũng là cách họ thấy hạn mức đang tiêu vào đâu.
    ket_qua["dung_ai"] = nho_gemini
    return ket_qua
