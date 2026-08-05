"""Kiểm phần PWA: cài được lên máy, và service worker không làm hỏng dữ liệu.

Test ở đây chia làm hai nhóm với hai mục đích khác hẳn nhau:

1. **Cài được** — manifest hợp lệ, icon có thật, mọi trang đều khai báo. Loại
   này hỏng thì chỉ là không cài được app, khó chịu chứ không nguy hiểm.

2. **Service worker không nói dối** — nhóm này mới quan trọng. Một service
   worker cache nhầm `/api` sẽ cho thu ngân xem giá và tồn kho CŨ mà không có
   dấu hiệu gì, và cache nhầm HTML sẽ làm luật bump `?v=` của dự án mất tác
   dụng vĩnh viễn. Cả hai đều là loại hỏng im lặng.

Nhóm 2 kiểm bằng cách đọc mã nguồn `sw.js` chứ không chạy thật (pytest không
có trình duyệt). Đây là dây bảo hiểm, không phải bằng chứng: nó bắt được việc
ai đó XÓA MẤT luật, chứ không chứng minh được luật chạy đúng. Muốn chứng minh
thì phải mở trình duyệt xem tab Network.
"""
from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "static"
TRANG_HTML = sorted(STATIC.glob("*.html"))


def _doc(ten: str) -> str:
    return (STATIC / ten).read_text(encoding="utf-8")


# ---------- Nhóm 1: cài được ----------
def test_manifest_duoc_phuc_vu(client):
    res = client.get("/manifest.json")
    assert res.status_code == 200
    assert res.json()["name"]


def test_manifest_du_truong_bat_buoc():
    m = json.loads(_doc("manifest.json"))
    for truong in ("name", "short_name", "start_url", "display", "icons"):
        assert m.get(truong), f"manifest thiếu {truong}"
    assert m["display"] == "standalone", "phải standalone thì mở ra mới hết thanh địa chỉ"
    assert m["start_url"] == "/"


@pytest.mark.parametrize("canh", [192, 512])
def test_icon_ton_tai_va_dung_kich_thuoc(canh):
    """Manifest khai 192 và 512 thì file phải có thật và ĐÚNG kích thước đó.

    Khai một đằng, file một nẻo thì Chrome lặng lẽ bỏ qua icon và không cho cài,
    không báo lỗi gì.
    """
    f = STATIC / "img" / f"icon-{canh}.png"
    assert f.is_file(), f"thiếu {f.name} — chạy scripts/tao_icon_pwa.py"
    d = f.read_bytes()
    assert d[:8] == b"\x89PNG\r\n\x1a\n", "không phải file PNG"
    rong, cao = struct.unpack(">II", d[16:24])
    assert (rong, cao) == (canh, canh), f"{f.name} là {rong}x{cao}, phải {canh}x{canh}"


def test_moi_icon_trong_manifest_deu_co_file_that():
    m = json.loads(_doc("manifest.json"))
    for icon in m["icons"]:
        duong_dan = STATIC / icon["src"].lstrip("/")
        assert duong_dan.is_file(), f"manifest trỏ tới {icon['src']} nhưng không có file"


def test_icon_maskable_de_android_bo_goc_khong_mat_chu():
    m = json.loads(_doc("manifest.json"))
    assert any("maskable" in i.get("purpose", "") for i in m["icons"])


@pytest.mark.parametrize("trang", [p.name for p in TRANG_HTML])
def test_moi_trang_deu_khai_manifest_va_nap_pwa_js(trang):
    """Thiếu ở một trang thì vào đúng trang đó sẽ không cài được — và đó là
    kiểu lỗi chỉ lộ ra khi người dùng tình cờ mở trang ấy trước."""
    t = _doc(trang)
    assert 'rel="manifest"' in t, f"{trang} thiếu <link rel=manifest>"
    assert "/js/pwa.js" in t, f"{trang} không nạp pwa.js"
    assert 'name="theme-color"' in t, f"{trang} thiếu theme-color"


@pytest.mark.parametrize("trang", [p.name for p in TRANG_HTML])
def test_pwa_js_co_dau_phien_ban(trang):
    """Luật của dự án: file trong static/ phải kèm `?v=`, kẻo trình duyệt giữ
    bản cũ mãi. Xem QUY_TRINH_LAM_VIEC.md bước 2a."""
    t = _doc(trang)
    assert "/js/pwa.js?v=" in t, f"{trang} nạp pwa.js mà quên ?v="


def test_service_worker_duoc_phuc_vu_o_goc(client):
    """Phải nằm ở `/sw.js`. Đặt trong thư mục con thì phạm vi kiểm soát của nó
    co lại đúng thư mục đó và không quản được cả app."""
    res = client.get("/sw.js")
    assert res.status_code == 200
    assert "javascript" in res.headers["content-type"]


# ---------- Nhóm 2: service worker không nói dối ----------
def test_sw_khong_bao_gio_cache_api():
    """LUẬT SỐ 1. Giá, tồn kho, công nợ phải lấy từ mạng.

    Trả một con số cũ từ cache là nói dối đúng chỗ nguy hiểm nhất: thu ngân
    nhìn thấy "còn 5 cái" trong khi kho đã hết.
    """
    sw = _doc("sw.js")
    assert "'/api/'" in sw, "mất nhánh chặn /api"
    vi_tri = sw.index("startsWith('/api/')")
    doan = sw[vi_tri:vi_tri + 400]
    assert "return" in doan, "nhánh /api phải thoát sớm, không đụng cache"


def test_sw_chi_dung_toi_GET():
    """LUẬT SỐ 2. POST tạo đơn, PUT sửa hàng — để nguyên cho mạng."""
    sw = _doc("sw.js")
    assert "method !== 'GET'" in sw


def test_sw_lay_html_tu_mang_truoc():
    """LUẬT SỐ 3, và là luật dễ phá nhất.

    File HTML chứa các dấu `?v=` trỏ tới CSS/JS. Cache HTML trước thì bump
    `?v=` KHÔNG BAO GIỜ có tác dụng nữa, và bẫy "cache JS rất dai" trong
    CLAUDE.md trở thành không sửa được.
    """
    sw = _doc("sw.js")
    assert "'navigate'" in sw, "mất nhánh xử lý điều hướng trang"
    vi_tri = sw.index("'navigate'")
    doan = sw[vi_tri:vi_tri + 200]
    assert "mang_truoc" in doan, "trang HTML phải network-first, không được cache-first"


def test_sw_lui_ve_khung_app_khi_url_co_query_la():
    """Bẫy đã đo được thật, không phải phòng xa.

    `auth.js` chuyển hướng về `/?auth=<timestamp>` và timestamp đổi MỖI LẦN.
    Cache giữ `/?auth=1785949778146`, lần sau trình duyệt hỏi
    `/?auth=1785949873816` — khác URL nên không khớp, và người dùng offline
    nhận trang lỗi của trình duyệt thay vì app.

    Lỗi này KHÔNG lộ ra khi thử bằng `fetch()`, chỉ lộ khi điều hướng thật.
    Nên phải có bước lùi bỏ qua `?query` cho điều hướng.
    """
    sw = _doc("sw.js")
    assert "ignoreSearch" in sw, "mất bước lùi bỏ qua query khi điều hướng offline"
    vi_tri = sw.index("ignoreSearch")
    doan = sw[max(0, vi_tri - 500):vi_tri]
    assert "la_trang" in doan, "ignoreSearch chỉ được dùng cho điều hướng, không cho file lẻ"


def test_sw_khong_bo_qua_query_voi_file_le():
    """Ngược lại: CSS/JS phải khớp chính xác cả `?v=`.

    Bỏ qua query ở đó là phục vụ đúng bản cũ mà luật bump `?v=` vừa mất công
    chặn — tự tay dựng lại đúng cái bẫy đã đi vòng qua.
    """
    sw = _doc("sw.js")
    dau = sw.index("async function cache_truoc")
    cuoi = sw.index("async function", dau + 10)
    assert "ignoreSearch" not in sw[dau:cuoi], "cache_truoc không được bỏ qua ?v="


def test_sw_co_don_dep_cache_cu():
    """Đổi PHIEN_BAN mà không xóa cache cũ thì máy người dùng giữ cả hai, và
    bản cũ vẫn có thể được dùng."""
    sw = _doc("sw.js")
    assert "activate" in sw
    assert "caches.delete" in sw


def test_sw_co_so_phien_ban():
    sw = _doc("sw.js")
    assert "const PHIEN_BAN" in sw


def test_sw_khong_ghi_cung_danh_sach_css_js():
    """Danh sách nạp sẵn KHÔNG được liệt kê file có `?v=`.

    Ghi vào đó thì mỗi lần bump `?v=` lại phải sửa cả sw.js — quên một lần là
    người dùng nạp file không tồn tại và bước cài service worker thất bại.
    """
    sw = _doc("sw.js")
    dau = sw.index("const KHUNG_APP")
    cuoi = sw.index("]", dau)
    assert "?v=" not in sw[dau:cuoi], "KHUNG_APP không được chứa file có ?v="
