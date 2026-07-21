"""Contract tĩnh cho hai lỗi phát hiện khi bấm giao diện thật."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_kho_hang_co_thao_tac_sua_san_pham():
    seller_js = (ROOT / "static" / "js" / "seller.js").read_text(encoding="utf-8")
    seller_html = (ROOT / "static" / "seller.html").read_text(encoding="utf-8")

    assert "function editProduct(id)" in seller_js
    assert "editProduct(${p.id})" in seller_js
    assert 'id="btnCancelEditProduct"' in seller_html


def test_dashboard_gui_ro_per_page_trong_query_string():
    seller_js = (ROOT / "static" / "js" / "seller.js").read_text(encoding="utf-8")

    assert "const DON_MOI_TRANG = 50;" in seller_js
    assert "p.set('per_page', String(DON_MOI_TRANG));" in seller_js


def test_trinh_duyet_khong_nhan_404_khi_tu_dong_lay_favicon(client):
    assert client.get("/favicon.ico").status_code in {200, 204}
