"""Khóa các móc UI quan trọng của luồng đối soát D4."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_pos_khong_con_xac_nhan_chuyen_khoan_thu_cong():
    html = _read("static/pos.html")
    js = _read("static/js/pos.js")

    assert "Xác nhận Đã Nhận Tiền" not in html
    assert "confirmPayment" not in js
    assert 'id="paymentStatusBox"' in html
    assert 'id="btnCashTopup"' in html
    assert 'id="hoaDonCanhBao"' in html


def test_pos_giu_qr_khi_thieu_va_xuat_hoa_don_khi_thua():
    js = _read("static/js/pos.js")

    assert "DocTien.canhBaoThieuTien(" in js
    assert "DocTien.canhBaoThuaTien(" in js
    assert "renderPaymentStatus(statusRes);" in js
    assert "`/orders/${idDon}/cash-topup`" in js
    assert "if(statusRes.refund_pending)" in js
    assert "ĐÃ XUẤT HÓA ĐƠN — CẦN HOÀN KHÁCH" in js
    assert "Chuyển khoản + tiền mặt" in js


def test_seller_co_hang_cho_doi_soat_va_refund_idempotent():
    html = _read("static/seller.html")
    js = _read("static/js/seller.js")

    for element_id in (
        "doiSoatBadge",
        "doiSoatList",
        "refundModal",
        "refundMethod",
        "refundReference",
        "refundNote",
    ):
        assert f'id="{element_id}"' in html

    assert "reconciliation_only: 'true'" in js
    assert "`/orders/${id}/cash-topup`" in js
    assert "`/orders/${orderId}/refund-complete`" in js
    assert "async function coCaTienMatDangMo()" in js
    assert "if (!await coCaTienMatDangMo()) return;" in js
    assert "`/shifts/current/${shopId}`" in js
    assert "operation_id: refundOperationId" in js
    assert "setInterval(lamMoiBadgeDoiSoatNen, 30000)" in js
    assert "Chuyển khoản + tiền mặt" in js
