"""Khóa các móc UI của màn xử lý đơn bán offline.

Test đắt giá nhất ở đây là `test_moi_co_backend_deu_co_ban_dich`: nó buộc danh
sách cờ trong `offline_service` và bản dịch trong locale phải đi cùng nhau.
Thêm một cờ mới ở backend mà quên dịch thì chủ shop nhìn thấy `TON_AM` trần
trụi — biết là có chuyện nhưng không biết chuyện gì và phải làm gì.
"""
from pathlib import Path

import pytest

from fselling.services import offline_service

ROOT = Path(__file__).resolve().parents[1]

# Mọi cờ mà service có thể gắn. Thêm cờ mới ở service thì thêm vào đây, và test
# bên dưới sẽ đòi bản dịch cho cả tiếng Việt lẫn tiếng Anh.
CAC_CO = [
    offline_service.ISSUE_TON_AM,
    offline_service.ISSUE_CA_DA_CHOT,
    offline_service.ISSUE_KHONG_CO_CA,
    offline_service.ISSUE_SP_KHONG_CON,
    offline_service.ISSUE_GIA_DOI,
]


def _doc(duong_dan: str) -> str:
    return (ROOT / duong_dan).read_text(encoding="utf-8")


def test_khoi_offline_co_trong_tab_doi_soat():
    html = _doc("static/seller.html")
    assert 'id="offlineIssueBox"' in html
    assert 'id="offlineIssueList"' in html
    assert 'id="offlineIssueCount"' in html


def test_khoi_offline_an_khi_chua_co_don_nao():
    """Cửa hàng chưa bao giờ mất mạng thì không phải nhìn một ô trống."""
    html = _doc("static/seller.html")
    vi_tri = html.index('id="offlineIssueBox"')
    the = html[vi_tri:vi_tri + 200]
    assert "display: none" in the


def test_seller_js_co_du_ba_ham():
    js = _doc("static/js/seller.js")
    assert "async function loadDonOffline(" in js
    assert "function renderDonOffline(" in js
    assert "function taoTheDonOffline(" in js


def test_load_doi_soat_goi_kem_don_offline():
    """Không có dòng này thì khối chỉ hiện sau khi bấm Tải lại lần hai."""
    js = _doc("static/js/seller.js")
    dau = js.index("async function loadDoiSoat(")
    cuoi = js.index("async function lamMoiBadgeDoiSoatNen(")
    assert "loadDonOffline(shopId)" in js[dau:cuoi]


def test_dung_ham_dinh_dang_tien_co_that_trong_seller_js():
    """Bẫy đã dính thật: `dinhDangTien` nằm ở `pos.js`, mà `seller.html` KHÔNG
    nạp file đó. Gọi nhầm thì `taoTheDonOffline` ném lỗi, `catch` của khối phụ
    nuốt mất, và màn hình trông y hệt "không có đơn nào cần kiểm".

    `seller.js` dùng `dinhDangTienDoiSoat`.
    """
    js = _doc("static/js/seller.js")
    dau = js.index("function taoTheDonOffline(")
    ma = _bo_chu_thich(js[dau:js.index("function renderDonOffline(")])
    assert "dinhDangTienDoiSoat(" in ma
    # Bắt đúng lời gọi `dinhDangTien(`, không bắt nhầm `dinhDangTienDoiSoat(`
    assert "dinhDangTien(" not in ma


def test_loi_khoi_offline_van_keu_ra_console():
    """Nuốt lỗi để bảo vệ màn hình là đúng; nuốt luôn cả tiếng kêu là tự bịt mắt.
    `console.debug` bị ẩn ở mức log mặc định nên đã giấu trọn một lỗi thật."""
    js = _doc("static/js/seller.js")
    dau = js.index("async function loadDonOffline(")
    # Cắt theo hàm kế tiếp, KHÔNG cắt theo số ký tự: bản đầu lấy 700 ký tự và
    # đỏ oan vì chính khối chú thích giải thích lỗi này đã chiếm hết cửa sổ.
    ma = _bo_chu_thich(js[dau:js.index("async function lamMoiBadgeDoiSoatNen(")])
    assert "console.warn(" in ma
    assert "console.debug(" not in ma


def test_hong_khoi_offline_khong_lam_hong_danh_sach_doi_soat():
    """Khối phụ phải nuốt lỗi của chính nó. Ném ra ngoài là mất luôn danh sách
    đối soát ngân hàng - đổi một khối phụ lấy một màn hình tiền."""
    js = _doc("static/js/seller.js")
    dau = js.index("async function loadDonOffline(")
    doan = js[dau:dau + 600]
    assert "catch" in doan
    assert "showToast" not in doan, "khối phụ không được chen toast"


@pytest.mark.parametrize("co", CAC_CO)
@pytest.mark.parametrize("ngon_ngu", ["vi", "en"])
def test_moi_co_backend_deu_co_ban_dich(co, ngon_ngu):
    """Cờ mới ở backend mà quên dịch thì chủ shop thấy `TON_AM` trần trụi."""
    locale = _doc("static/js/locales/seller.js")
    khoi = locale.split(f"resources.{ngon_ngu}.translation")[1]
    ket_thuc = khoi.find("resources.")
    if ket_thuc > 0:
        khoi = khoi[:ket_thuc]
    assert f"'seller.offline.issue.{co}'" in khoi, f"thiếu tên cờ {co} ({ngon_ngu})"
    assert f"'seller.offline.fix.{co}'" in khoi, f"thiếu cách xử lý cho {co} ({ngon_ngu})"


def _bo_chu_thich(ma: str) -> str:
    """Bỏ chú thích `//` để chỉ còn phần CODE thật sự chạy.

    Cần thật: bản đầu của test này đỏ oan vì chính dòng chú thích cảnh báo
    "đừng gọi new Date()" lại chứa chuỗi đang bị cấm. Kiểm cả lời văn thì viết
    chú thích cẩn thận lại thành có lỗi.

    Cắt thô theo `//` là đủ ở đây (đoạn đang xét không có URL nào), nhưng đừng
    mang hàm này đi dùng cho mã có chuỗi chứa `//`.
    """
    return "\n".join(dong.split("//")[0] for dong in ma.splitlines())


def test_gio_ban_hien_qua_dinh_dang_ngay_gio():
    """Giờ từ server là UTC không có ký hiệu múi giờ. Dựng ngày thẳng từ chuỗi
    đó là lệch 7 tiếng, và đơn buổi tối bị ghi lùi sang hôm trước."""
    js = _doc("static/js/seller.js")
    dau = js.index("function taoTheDonOffline(")
    ma = _bo_chu_thich(js[dau:js.index("function renderDonOffline(")])
    assert "dinhDangNgayGio(" in ma
    assert "new Date(" not in ma


def test_ten_may_duoc_thoat_html():
    """`device_label` do máy bán gửi lên, tức là dữ liệu KHÔNG tin được. Nhét
    thẳng vào innerHTML là mở đường chèn mã."""
    js = _doc("static/js/seller.js")
    dau = js.index("function taoTheDonOffline(")
    doan = js[dau:js.index("function renderDonOffline(")]
    assert "escapeHtml(may)" in doan
    assert "escapeHtml(don.device)" not in doan or "escapeHtml" in doan


def test_co_la_van_hien_ra_chu_khong_bi_nuot():
    """Server mới hơn giao diện thì sẽ có cờ chưa kịp dịch. Ẩn nó đi là giấu
    mất một cảnh báo — hiện mã trần vẫn hơn không hiện gì."""
    js = _doc("static/js/seller.js")
    dau = js.index("function taoTheDonOffline(")
    doan = js[dau:js.index("function renderDonOffline(")]
    assert "chua_dich" in doan


def test_da_bump_phien_ban_khi_sua_static():
    """Luật của dự án: sửa file trong static/ thì phải đổi `?v=`, kẻo người dùng
    chạy code cũ trong im lặng. Xem QUY_TRINH_LAM_VIEC.md bước 2a."""
    html = _doc("static/seller.html")
    assert "/js/seller.js?v=20260803-lich-su-huy" not in html
    assert "/js/locales/seller.js?v=20260803-lich-su-huy" not in html
    assert "/js/seller.js?v=" in html
    assert "/js/locales/seller.js?v=" in html
