"""Khóa các móc UI của màn "Ai làm gì"."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Những hành động chắc chắn sẽ xuất hiện và cần có tên tiếng người.
HANH_DONG_QUAN_TRONG = [
    "CANCEL_ORDER", "REFUND_COMPLETE", "CASH_PAY_OUT", "WRITE_OFF_STOCK",
    "ORDER_RETURN", "PAY_ORDER", "OFFLINE_SALE", "ADJUST_STOCK",
    "STOCKTAKE", "UPDATE_PRODUCT", "DELETE_PRODUCT", "DISABLE_STAFF",
]


def _doc(p: str) -> str:
    return (ROOT / p).read_text(encoding="utf-8")


def _bo_chu_thich(ma: str) -> str:
    return "\n".join(d.split("//")[0] for d in ma.splitlines())


def test_co_tab_va_khoi_noi_dung():
    html = _doc("static/seller.html")
    assert 'data-main-tab="nhatky"' in html
    assert 'id="nhatky"' in html
    assert 'id="nhatKyList"' in html


def test_mo_tab_thi_tu_nap():
    """Thiếu dòng này thì tab mở ra trống, phải bấm Tải lại mới thấy gì."""
    js = _doc("static/js/seller.js")
    dau = js.index("function switchTab(")
    ma = _bo_chu_thich(js[dau:js.index("}", js.index("if (tabId === 'nhatky')"))])
    assert "loadNhatKy()" in ma


def test_du_cac_ham():
    js = _doc("static/js/seller.js")
    for ten in ("async function loadNhatKy(", "function renderNhatKy(",
                "function taoDongNhatKy(", "function chonShopNhatKy(",
                "function doiTrangNhatKy("):
        assert ten in js, f"thiếu {ten}"


def test_hanh_dong_chua_dich_van_hien_ma_tran():
    """Server mới hơn giao diện là chuyện thường. Giấu một dòng nhật ký còn tệ
    hơn hiện nó khó đọc — đây là màn hình dùng để soi."""
    js = _doc("static/js/seller.js")
    dau = js.index("function tenHanhDong(")
    ma = _bo_chu_thich(js[dau:js.index("function taoDongNhatKy(")])
    # Bỏ khoảng trắng rồi so: không phụ thuộc cách xuống dòng của người viết,
    # nhưng vẫn khẳng định đúng phép rẽ nhánh "chưa dịch thì trả về mã trần".
    assert "ten===khoa?action:ten" in ma.replace(" ", "").replace("\n", "")


def test_nhom_mau_chi_de_to_mau_khong_de_loc():
    """`NHOM_HANH_DONG` chỉ quyết định MÀU. Hành động ngoài mọi nhóm vẫn phải
    hiện, chỉ là màu trung tính."""
    js = _doc("static/js/seller.js")
    dau = js.index("function mauHanhDong(")
    ma = _bo_chu_thich(js[dau:js.index("function tenHanhDong(")])
    assert "return '#64748B'" in ma, "thiếu màu mặc định cho hành động lạ"


def test_thoi_gian_qua_dinh_dang_ngay_gio():
    js = _doc("static/js/seller.js")
    dau = js.index("function taoDongNhatKy(")
    ma = _bo_chu_thich(js[dau:js.index("function renderNhatKy(")])
    assert "dinhDangNgayGio(" in ma
    assert "new Date(" not in ma


def test_chi_tiet_duoc_thoat_html():
    """`details` chứa tên sản phẩm và ghi chú do người dùng nhập. Nhét thẳng vào
    innerHTML là mở đường chèn mã."""
    js = _doc("static/js/seller.js")
    dau = js.index("function taoDongNhatKy(")
    ma = js[dau:js.index("function renderNhatKy(")]
    assert "escapeHtml(muc.details" in ma
    assert "escapeHtml(muc.username" in ma


def test_khong_de_phan_hoi_cu_ghi_de_phan_hoi_moi():
    """Đổi cửa hàng nhanh hai lần thì lần chậm hơn về sau sẽ ghi đè lên lần mới."""
    js = _doc("static/js/seller.js")
    dau = js.index("async function loadNhatKy(")
    ma = _bo_chu_thich(js[dau:js.index("function chonShopNhatKy(")])
    assert "nhatKyRequestId" in ma
    assert "requestId !== nhatKyRequestId" in ma


@pytest.mark.parametrize("action", HANH_DONG_QUAN_TRONG)
@pytest.mark.parametrize("ngon_ngu", ["vi", "en"])
def test_hanh_dong_quan_trong_co_ten_tieng_nguoi(action, ngon_ngu):
    locale = _doc("static/js/locales/seller.js")
    khoi = locale.split(f"resources.{ngon_ngu}.translation")[1]
    ket = khoi.find("resources.")
    if ket > 0:
        khoi = khoi[:ket]
    assert f"'seller.activity.action.{action}'" in khoi, f"thiếu tên {action} ({ngon_ngu})"


@pytest.mark.parametrize("khoa", [
    "seller.tabs.activity", "seller.activity.title", "seller.activity.description",
    "seller.activity.empty", "seller.activity.page_info",
])
@pytest.mark.parametrize("ngon_ngu", ["vi", "en"])
def test_du_cau_chu_khung_man_hinh(khoa, ngon_ngu):
    locale = _doc("static/js/locales/seller.js")
    khoi = locale.split(f"resources.{ngon_ngu}.translation")[1]
    ket = khoi.find("resources.")
    if ket > 0:
        khoi = khoi[:ket]
    assert f"'{khoa}'" in khoi


def test_da_bump_phien_ban():
    html = _doc("static/seller.html")
    assert "/js/seller.js?v=20260806-offline-ui2" not in html
    assert "/js/seller.js?v=" in html
