"""Contract giao diện CRM cho các lỗi phát hiện khi bấm trình duyệt thật."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_modal_chi_tiet_don_hien_ten_va_so_dien_thoai_khach():
    seller_html = (ROOT / "static" / "seller.html").read_text(encoding="utf-8")
    seller_js = (ROOT / "static" / "js" / "seller.js").read_text(encoding="utf-8")

    assert 'id="odKhachHang"' in seller_html
    assert "document.getElementById('odKhachHang')" in seller_js
    assert "d.customer.name" in seller_js
    assert "d.customer.phone" in seller_js
