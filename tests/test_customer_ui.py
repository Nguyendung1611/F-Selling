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


def test_du_lieu_nguoi_dung_khong_bi_nhung_vao_inline_javascript():
    """HTML escaping không đủ an toàn trong thuộc tính onclick JavaScript."""
    seller_js = (ROOT / "static" / "js" / "seller.js").read_text(encoding="utf-8")
    pos_js = (ROOT / "static" / "js" / "pos.js").read_text(encoding="utf-8")

    assert 'onclick="editCategory(' not in seller_js
    assert 'onclick="xoaNhanVien(' not in seller_js
    assert 'onclick="deleteCustomer(' not in seller_js
    assert 'onclick="chonKhach(' not in pos_js
