"""Ngày nghiệp vụ: mọi service phải hỏi cùng một chỗ "hôm nay là ngày mấy".

Trước khi có `core/thoi_gian.py`, câu hỏi đó có ba câu trả lời khác nhau nằm
rải trong services (UTC, giờ máy, giờ Việt Nam). Hậu quả nặng nhất không phải
"lệch vài tiếng" mà là hai màn hình nói hai điều khác nhau về cùng một lô hàng.
"""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from conftest import auth, create_category, create_product, create_shop, new_seller

from fselling import models
from fselling.core import thoi_gian
from fselling.core.database import SessionLocal
from fselling.services import (
    expense_service,
    forecast_service,
    inventory_service,
    report_service,
    supplier_service,
)


@pytest.fixture
def nua_dem_viet_nam(monkeypatch):
    """Đứng ở 02:00 sáng ngày 09/08 giờ Việt Nam = 19:00 ngày 08/08 giờ UTC.

    Đây đúng là khung giờ mà mọi bản `datetime.utcnow()` cũ trả về NGÀY HÔM
    TRƯỚC. Không dựng được khung này thì lỗi chỉ lộ ra lúc 0h-7h sáng, tức là
    không bao giờ có ai ngồi xem.
    """
    moc = datetime(2026, 8, 9, 2, 0, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
    monkeypatch.setattr(thoi_gian, "_bay_gio", lambda: moc)
    return moc


def test_hai_gio_sang_van_la_ngay_moi(nua_dem_viet_nam):
    assert thoi_gian.hom_nay_vn() == date(2026, 8, 9)
    assert thoi_gian.hom_nay_vn_str() == "2026-08-09"


def test_moi_service_deu_hoi_cung_mot_cho(nua_dem_viet_nam):
    """Đổi đồng hồ ở MỘT chỗ thì cả bảy chỗ phải đổi theo.

    Chỗ nào còn tự tính lấy sẽ vẫn trả ngày thật của máy và test này đỏ.
    """
    assert inventory_service._hom_nay() == "2026-08-09"
    assert supplier_service._today_vn() == "2026-08-09"
    assert expense_service.today_vn() == date(2026, 8, 9)
    assert report_service._today_vietnam() == date(2026, 8, 9)
    assert forecast_service._hom_nay_vn() == date(2026, 8, 9)


def test_moc_dau_ngay_khop_giua_report_va_forecast():
    for ngay in (date(2026, 1, 1), date(2026, 8, 9), date(2026, 12, 31)):
        assert (
            report_service._dau_ngay_viet_nam_sang_utc(ngay)
            == forecast_service._dau_ngay_vn_sang_utc(ngay)
            == thoi_gian.dau_ngay_vn_sang_utc(ngay)
        )


def test_dau_ngay_viet_nam_la_17h_hom_truoc_theo_utc():
    assert thoi_gian.dau_ngay_vn_sang_utc(date(2026, 8, 9)) == datetime(
        2026, 8, 8, 17, 0
    )


# ---------- Hậu quả thật trên hàng hóa ----------
def _shop_co_lo_het_han_hom_qua(client):
    """Shop có một lô hết hạn 08/08 - tức là đã qua hạn tính theo giờ Việt Nam
    lúc 02:00 ngày 09/08, nhưng CHƯA qua hạn nếu tính theo giờ UTC."""
    _, token = new_seller(client)
    shop_id = create_shop(client, token)
    cat_id = create_category(client, token, shop_id)
    prod = create_product(client, token, shop_id, "Sữa tươi", 30000, 0, cat_id)

    session = SessionLocal()
    try:
        p = session.query(models.Product).filter(models.Product.id == prod["id"]).first()
        p.track_batches = True
        p.stock = 10
        session.add(
            models.ProductBatch(
                product_id=p.id, shop_id=shop_id, expiry_date="2026-08-08",
                quantity=10, cost_price=20000,
            )
        )
        session.commit()
    finally:
        session.close()
    return {"shop_id": shop_id, "token": token, "product_id": prod["id"]}


def test_hang_qua_han_khong_con_ban_duoc_ngay_tu_nua_dem(client, nua_dem_viet_nam):
    ctx = _shop_co_lo_het_han_hom_qua(client)
    session = SessionLocal()
    try:
        prod = (
            session.query(models.Product)
            .filter(models.Product.id == ctx["product_id"])
            .first()
        )
        # Bản cũ (giờ UTC) vẫn coi là còn 10 cái bán được suốt 7 tiếng nữa.
        assert inventory_service.ton_kha_dung(session, prod) == 0
    finally:
        session.close()


def test_hang_khong_ban_duoc_thi_phai_duoc_phep_huy(client, nua_dem_viet_nam):
    """Hai màn phải đồng ý với nhau.

    Lệch nhau là có lô rơi vào khe: không bán được mà cũng không hủy được, và
    chủ shop không có cách nào đưa nó ra khỏi kho.
    """
    ctx = _shop_co_lo_het_han_hom_qua(client)
    res = client.get(
        f"/api/products/{ctx['shop_id']}/write-off/expired",
        headers=auth(ctx["token"]),
    )
    assert res.status_code == 200, res.text
    lo = res.json()["items"]
    assert len(lo) == 1, res.json()
    assert lo[0]["expiry_date"] == "2026-08-08"
    assert lo[0]["quantity"] == 10


def test_voucher_het_han_theo_gio_viet_nam_khong_theo_gio_may(nua_dem_viet_nam):
    """`date.today()` đọc theo múi giờ MÁY: đúng ở máy dev Việt Nam, sai ngay
    khi deploy vào container (mặc định UTC) - voucher sống thêm 7 tiếng."""
    from fselling.services import voucher_service

    v = models.Voucher(code="TET", expires_at="2026-08-08")
    assert voucher_service.is_expired(v) is True

    con_han = models.Voucher(code="TET2", expires_at="2026-08-09")
    assert voucher_service.is_expired(con_han) is False
