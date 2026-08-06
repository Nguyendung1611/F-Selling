"""Hai sửa lỗi UX do người kiểm thử ngoài phát hiện, cộng một bug cache tự lộ ra.

Test đáng giá nhất ở đây là `test_moi_ham_dinh_dang_deu_ton_tai_that`: nó bắt
đúng loại lỗi đã mắc HAI LẦN trong một buổi — gọi một hàm không có trong phạm
vi của file đó. Cả hai lần đều xanh hết mọi test cũ và chỉ lộ ra khi mở trình
duyệt:

  - `dinhDangTien()` trong seller.js  (hàm đó nằm ở pos.js)
  - `escapeHtmlPOS()` trong pos.js    (tên bịa, hàm thật là escapeHtml)

Lỗi kiểu này im lặng vì `catch` nuốt mất, và màn hình chỉ trống trơn.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _doc(p: str) -> str:
    return (ROOT / p).read_text(encoding="utf-8")


def _bo_chu_thich(ma: str) -> str:
    return "\n".join(d.split("//")[0] for d in ma.splitlines())


def _ham_khai_bao(*duong_dan: str) -> set:
    """Mọi tên hàm được khai báo trong các file đã cho."""
    ten = set()
    for p in duong_dan:
        s = _doc(p)
        ten |= set(re.findall(r"(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(", s))
        ten |= set(re.findall(r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(", s))
        ten |= set(re.findall(r"global\.([A-Za-z_$][\w$]*)\s*=", s))
    return ten


# ---------- Bug đã mắc hai lần trong một buổi ----------
@pytest.mark.parametrize(
    "file_js, file_kem",
    [
        ("static/js/pos.js", ("static/js/api.js", "static/js/i18n.js")),
        ("static/js/seller.js", ("static/js/api.js", "static/js/i18n.js")),
    ],
)
def test_moi_ham_dinh_dang_deu_ton_tai_that(file_js, file_kem):
    """Hàm định dạng/thoát HTML được gọi phải CÓ THẬT trong phạm vi trang đó.

    `seller.html` không nạp `pos.js`, và ngược lại. Gọi nhầm sang file kia thì
    trình duyệt ném ReferenceError, `catch` gần nhất nuốt mất, và người dùng chỉ
    thấy một khối trống — không có lỗi nào hiện ra.
    """
    ma = _bo_chu_thich(_doc(file_js))
    co_san = _ham_khai_bao(file_js, *file_kem)
    goi = set(re.findall(r"\b((?:escapeHtml|dinhDang)[A-Za-z]*)\s*\(", ma))
    thieu = sorted(g for g in goi if g not in co_san)
    assert not thieu, f"{file_js} gọi hàm không tồn tại trong phạm vi của nó: {thieu}"


# ---------- Lỗi UX 1: một ô chọn cửa hàng ----------
def test_co_o_chon_cua_hang_chung():
    html = _doc("static/seller.html")
    assert 'id="shopChungSelect"' in html
    assert 'onchange="doiCuaHangChung(this.value)"' in html


def test_cac_o_chon_cu_deu_bi_an():
    """Chín ô chọn trên một trang là lý do người dùng đổi cửa hàng ở tab này rồi
    sang tab khác vẫn thấy số cũ."""
    html = _doc("static/seller.html")
    for khung in ("dashboardShopSelector", "warehouseShopSelector", "kkShopSelector",
                  "voucherShopSelector", "customerShopSelector", "staffShopSelector",
                  "nhatKyShopSelector"):
        assert f"#{khung}" in html, f"quên ẩn {khung}"
    assert ".doi-soat-shop-field { display: none" in html or \
           ".doi-soat-shop-field" in html


def test_doi_cua_hang_dat_LAI_CA_BON_bien_trang_thai():
    """Gốc của lỗi không phải 9 ô chọn mà là BỐN biến trạng thái riêng biệt.
    Sót một biến là tab đó vẫn hiển thị cửa hàng cũ.

    `currentShopId` được đặt gián tiếp qua `changeShop(id)` — hàm đó vừa gán
    biến vừa ghi `localStorage` vừa nạp lại dữ liệu dùng chung, nên gọi nó đúng
    hơn là gán tay rồi quên hai việc kia.
    """
    js = _bo_chu_thich(_doc("static/js/seller.js"))
    dau = js.index("function doiCuaHangChung(")
    ma = js[dau:js.index("function renderOChonCuaHangChung(")]
    for bien in ("dashboardShopId", "doiSoatShopId", "nhatKyShopId"):
        assert bien in ma, f"doiCuaHangChung không đặt lại {bien}"
    assert "changeShop(id)" in ma, "currentShopId phải được đặt qua changeShop()"


def test_van_goi_changeShop_du_dang_o_tab_khac():
    """`changeShop` nạp dữ liệu dùng chung (sản phẩm, danh mục, khuyến mãi).
    Bỏ qua nó thì lát nữa mở Kho Hàng ra thấy hàng của cửa hàng trước."""
    js = _bo_chu_thich(_doc("static/js/seller.js"))
    dau = js.index("function doiCuaHangChung(")
    ma = js[dau:js.index("function renderOChonCuaHangChung(")]
    assert "changeShop(id)" in ma


def test_khong_gop_o_chon_mo_POS():
    """`posShopList` không lọc dữ liệu mà là nút "mở POS cho cửa hàng nào" —
    gộp vào ô chung là mất chức năng."""
    html = _doc("static/seller.html")
    assert 'id="posShopList"' in html
    assert "#posShopList" not in html.split("</style>")[0], "posShopList không được ẩn"


# ---------- Lỗi UX 2: thu nợ tại quầy ----------
def test_pos_co_nut_va_hop_thoai_thu_no():
    html = _doc("static/pos.html")
    assert 'id="btnThuNoPOS"' in html
    assert 'id="thuNoModal"' in html
    assert 'id="thuNoDanhSach"' in html


def test_pos_goi_dung_endpoint_thu_no():
    js = _doc("static/js/pos.js")
    assert "/debt-payment" in js


def test_thu_no_bat_buoc_co_ca_dang_mo():
    """Tiền mặt vào két phải thuộc về một ca. Không có ca thì khoản này không
    biết tính vào đâu — cùng luật với mọi khoản tiền mặt khác."""
    js = _bo_chu_thich(_doc("static/js/pos.js"))
    dau = js.index("async function thuNoDon(")
    ma = js[dau:dau + 900]
    assert "activeShift" in ma
    assert "moModalMoCa()" in ma


def test_thu_no_co_ma_chong_bam_hai_lan():
    """Bấm lại vì mạng chậm không được thu tiền hai lần."""
    js = _bo_chu_thich(_doc("static/js/pos.js"))
    dau = js.index("async function thuNoDon(")
    ma = js[dau:js.index("async function capNhatCanhBaoGhiNo(")]
    assert "operation_id" in ma


def test_thu_no_chan_thu_qua_so_con_no():
    js = _bo_chu_thich(_doc("static/js/pos.js"))
    dau = js.index("async function thuNoDon(")
    ma = js[dau:js.index("async function capNhatCanhBaoGhiNo(")]
    assert "conNo" in ma and "collect_too_much" in ma


def test_thu_no_hoi_lai_truoc_khi_ghi():
    """Tiền vào két thì phải có một lần nhìn lại bằng mắt, giống lúc chốt đơn."""
    js = _bo_chu_thich(_doc("static/js/pos.js"))
    dau = js.index("async function thuNoDon(")
    ma = js[dau:js.index("async function capNhatCanhBaoGhiNo(")]
    assert "xacNhan(" in ma


@pytest.mark.parametrize("khoa", [
    "pos.debt.collect_button", "pos.debt.collect_title", "pos.debt.collect_action",
    "pos.debt.collect_need_shift", "pos.debt.collect_too_much",
    "pos.debt.collect_confirm", "pos.debt.collect_done",
])
@pytest.mark.parametrize("ngon_ngu", ["vi", "en"])
def test_du_ban_dich_thu_no(khoa, ngon_ngu):
    locale = _doc("static/js/locales/pos.js")
    khoi = locale.split(f"resources.{ngon_ngu}.translation")[1]
    ket = khoi.find("resources.")
    if ket > 0:
        khoi = khoi[:ket]
    assert f"'{khoa}'" in khoi


# ---------- Bug cache tự lộ ra khi kiểm hai sửa lỗi trên ----------
@pytest.mark.parametrize("duong_dan", ["/", "/pos", "/seller", "/admin"])
def test_trang_html_bat_trinh_duyet_hoi_lai(client, duong_dan):
    """File HTML chứa mọi dấu `?v=`. FastAPI không gửi `Cache-Control` nên trình
    duyệt tự suy hạn dùng từ `Last-Modified` và có thể phục vụ HTML CŨ — khi đó
    bump `?v=` vô tác dụng vì bản HTML cũ vẫn trỏ số cũ.

    Đo được thật: server phục vụ `?v=20260806-thu-no` mà trình duyệt vẫn chạy
    `?v=20260806-offline-pos`. Service worker cũng không cứu được vì `fetch()`
    bên trong nó vẫn đi qua HTTP cache của trình duyệt.
    """
    res = client.get(duong_dan)
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert res.headers.get("cache-control") == "no-cache"


def test_file_js_khong_bi_ep_hoi_lai(client):
    """JS đã có `?v=` trong URL nên đổi nội dung là đổi địa chỉ — ép hỏi lại chỉ
    tốn thêm một vòng mạng cho mỗi file, mỗi lần mở trang."""
    res = client.get("/js/pos.js?v=test")
    assert res.status_code == 200
    assert res.headers.get("cache-control") != "no-cache"
