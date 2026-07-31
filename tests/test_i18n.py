"""Đa ngôn ngữ: chọn theo thiết bị, API, email và file Excel."""
from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path

import openpyxl

from conftest import admin_token, auth
from fselling.core.i18n import negotiate_locale, tr, using_locale
from fselling.services.email_service import _build_body

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_negotiate_locale_chi_nhan_vi_en_va_ton_trong_q_weight():
    assert negotiate_locale(None) == "vi"
    assert negotiate_locale("fr-FR, de;q=0.8") == "vi"
    assert negotiate_locale("en-US") == "en"
    assert negotiate_locale("en;q=0.4, vi-VN;q=0.9") == "vi"
    assert negotiate_locale("vi;q=0, en;q=0.5") == "en"


def test_backend_dich_theo_request_va_mac_dinh_tieng_viet(client):
    vi_response = client.get("/api/auth/session-check")
    assert vi_response.status_code == 401
    assert vi_response.headers["content-language"] == "vi"
    assert "accept-language" in vi_response.headers["vary"].lower()
    assert vi_response.json()["detail"] == "Phiên đăng nhập không hợp lệ"

    en_response = client.get(
        "/api/auth/session-check",
        headers={
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": "http://testserver",
        },
    )
    assert en_response.status_code == 401
    assert en_response.headers["content-language"] == "en"
    assert {"origin", "accept-language"} <= {
        value.strip().lower()
        for value in en_response.headers["vary"].split(",")
    }
    assert en_response.json()["detail"] == "Invalid session"


def test_loi_validation_422_cung_theo_ngon_ngu_request(client):
    vi_response = client.post("/api/auth/login", json={})
    en_response = client.post(
        "/api/auth/login",
        json={},
        headers={"Accept-Language": "en"},
    )

    assert vi_response.status_code == 422
    assert en_response.status_code == 422
    assert {error["msg"] for error in vi_response.json()["detail"]} == {
        "Trường này là bắt buộc"
    }
    assert {error["msg"] for error in en_response.json()["detail"]} == {
        "This field is required"
    }


def test_catalog_backend_fallback_va_email_theo_ngon_ngu():
    with using_locale("en"):
        assert tr("Không tìm thấy cửa hàng") == "Store not found"
        assert tr("Chuỗi mới chưa có bản dịch") == "Chuỗi mới chưa có bản dịch"
        english_body = _build_body("123456")

    with using_locale("vi"):
        vietnamese_body = _build_body("123456")

    assert '<html lang="en">' in english_body
    assert "Your verification code (OTP) is:" in english_body
    assert '<html lang="vi">' in vietnamese_body
    assert "Mã xác minh (OTP) của bạn là:" in vietnamese_body


def test_file_excel_theo_ngon_ngu_request(client):
    token = admin_token(client)
    vi_response = client.get("/api/export/admin", headers=auth(token))
    en_response = client.get(
        "/api/export/admin",
        headers={
            **auth(token),
            "Accept-Language": "en",
        },
    )

    assert vi_response.status_code == 200
    assert en_response.status_code == 200

    vi_sheet = openpyxl.load_workbook(BytesIO(vi_response.content)).active
    en_sheet = openpyxl.load_workbook(BytesIO(en_response.content)).active
    assert vi_sheet.title == "Doanh thu Shops"
    assert [cell.value for cell in vi_sheet[1]] == ["Tên Shop", "Tổng Doanh Thu"]
    assert en_sheet.title == "Store revenue"
    assert [cell.value for cell in en_sheet[1]] == ["Store name", "Total revenue"]


def _frontend_catalog_keys(path: Path, locale: str) -> set[str]:
    content = path.read_text(encoding="utf-8")
    marker = f"Object.assign(resources.{locale}.translation, {{"
    start = content.index(marker) + len(marker)
    if locale == "vi":
        end = content.index("Object.assign(resources.en.translation, {", start)
    else:
        end = content.index("})(window);", start)
    return set(re.findall(r"^\s*'([^']+)'\s*:", content[start:end], re.MULTILINE))


def test_catalog_frontend_du_key_va_thu_tu_script_on_dinh():
    locale_dir = PROJECT_ROOT / "static" / "js" / "locales"
    for path in locale_dir.glob("*.js"):
        vi_keys = _frontend_catalog_keys(path, "vi")
        en_keys = _frontend_catalog_keys(path, "en")
        assert vi_keys, f"Catalog rỗng: {path.name}"
        assert vi_keys == en_keys, (
            f"Catalog lệch key {path.name}: "
            f"thiếu EN={sorted(vi_keys - en_keys)}, thiếu VI={sorted(en_keys - vi_keys)}"
        )

    page_catalogs = {
        "index.html": "auth-admin",
        "register.html": "auth-admin",
        "verify.html": "auth-admin",
        "admin.html": "auth-admin",
        "seller.html": "seller",
        "pos.html": "pos",
    }
    for page_name, catalog in page_catalogs.items():
        html = (PROJECT_ROOT / "static" / page_name).read_text(encoding="utf-8")
        positions = [
            html.index("/js/vendor/i18next-26.3.6.min.js"),
            html.index("/js/locales/common.js"),
            html.index(f"/js/locales/{catalog}.js"),
            html.index("/js/i18n.js"),
            html.index("/js/api.js"),
        ]
        assert positions == sorted(positions), f"Sai thứ tự script i18n: {page_name}"

    frontend_js = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (PROJECT_ROOT / "static" / "js").glob("*.js")
    )
    assert "localStorage.clear(" not in frontend_js


def test_logout_giu_locale_va_khong_lo_trang_cu_qua_nut_back():
    api_js = (PROJECT_ROOT / "static" / "js" / "api.js").read_text(
        encoding="utf-8"
    )
    auth_keys = api_js.split("AUTH_STORAGE_KEYS", 1)[1].split("]);", 1)[0]

    assert "fselling.locale" not in auth_keys
    assert "window.location.replace(`/?auth=${Date.now()}`)" in api_js
    assert "window.addEventListener('pageshow'" in api_js
    assert "event.persisted" in api_js
    assert "hasLocalAccessToPage(window.location.pathname)" in api_js
    assert "localStorage.getItem('token') !== cachedToken" in api_js
    assert "setLanguage(locale, { persist: false })" in api_js


def test_hoa_don_va_doc_tien_luon_giu_tieng_viet():
    pos_js = (PROJECT_ROOT / "static" / "js" / "pos.js").read_text(
        encoding="utf-8"
    )
    receipt_formatters = pos_js.split("function dinhDangSoHoaDon", 1)[1].split(
        "function veHoaDon", 1
    )[0]
    receipt_renderer = pos_js.split("function veHoaDon", 1)[1].split(
        "function dongHoaDon", 1
    )[0]

    assert receipt_formatters.count("'vi-VN'") >= 2
    assert "HÓA ĐƠN BÁN HÀNG" in receipt_renderer
    assert "Cảm ơn quý khách!" in receipt_renderer


def test_ghi_chu_he_thong_pos_duoc_dich_con_ghi_chu_khach_giu_nguyen():
    pos_js = (PROJECT_ROOT / "static" / "js" / "pos.js").read_text(
        encoding="utf-8"
    )
    seller_js = (PROJECT_ROOT / "static" / "js" / "seller.js").read_text(
        encoding="utf-8"
    )

    assert "note: 'SYSTEM_POS_CASH_TOPUP'" in pos_js
    assert "function nhanGhiChuButToan(note)" in seller_js
    assert "seller.order_detail.system_pos_cash_topup" in seller_js
    assert "return value;" in seller_js
