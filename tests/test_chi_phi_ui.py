"""K1: giao diện màn Dòng Tiền.

Test giao diện ở đây là kiểm TĨNH trên mã nguồn, không thay được việc tự mở
trình duyệt nhìn (xem QUY_TRINH_LAM_VIEC.md). Nó chỉ bắt đúng loại lỗi mà mắt
người hay bỏ sót vì màn hình trông vẫn bình thường:

- Gọi một key i18n chưa khai: chữ hiện ra là "seller.cashflow.xyz" trên nền
  giao diện đẹp, và nếu key nằm trong nhánh hiếm (ví dụ ca lỗi) thì có thể qua
  mắt cả buổi kiểm.
- Gọi một helper không tồn tại trong trang: cả tab chết câm, console mới có lỗi.
- Nút chỉ dành cho chủ shop nhưng quên ẩn.
"""
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _read(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def _function(js: str, start: str, end: str) -> str:
    begin = js.index(start)
    return js[begin:js.index(end, begin)]


def _catalog_keys(source: str, lang: str) -> set[str]:
    """Các key đã khai trong một khối `resources.<lang>.translation`."""
    marker = f"resources.{lang}.translation, {{"
    begin = source.index(marker)
    block = source[begin:]
    ket_thuc = block.index("\n    });")
    return set(re.findall(r"'([a-zA-Z0-9_.]+)':", block[:ket_thuc]))


def _declared_functions(*relative_paths: str) -> set[str]:
    names: set[str] = set()
    for relative_path in relative_paths:
        source = _read(relative_path)
        names |= set(re.findall(r"function\s+([A-Za-z_$][\w$]*)\s*\(", source))
        names |= set(re.findall(r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*\(", source))
    return names


# Key được ghép động lúc chạy, không bắt được bằng regex trên `t('...')`.
# Thiếu một nhánh ở đây là cột "Nguồn tiền" trong bảng hiện ra chuỗi khóa thô.
KEY_GHEP_DONG = (
    "seller.cashflow.method_cash_shift",
    "seller.cashflow.method_transfer",
    "seller.cashflow.method_outside",
    "seller.cashflow.method_hint_cash_shift",
    "seller.cashflow.method_hint_transfer",
    "seller.cashflow.method_hint_outside",
)


def test_moi_key_i18n_cua_man_dong_tien_deu_da_duoc_khai():
    locales = _read("static/js/locales/seller.js")
    vi = _catalog_keys(locales, "vi")
    en = _catalog_keys(locales, "en")

    html = _read("static/seller.html")
    js = _read("static/js/expenses.js")

    dung = set(re.findall(r'data-i18n="(seller\.cashflow\.[\w.]+)"', html))
    # Bắt MỌI chuỗi khóa trong expenses.js, không chỉ dạng `t('...')`: một số
    # khóa nằm trong biểu thức ba ngôi (`t(x < 0 ? 'a' : 'b', ...)`) và bản
    # regex hẹp hơn sẽ bỏ sót đúng những nhánh hiếm khó thấy nhất.
    dung |= set(re.findall(r"'(seller\.cashflow\.[\w.]+)'", js))
    dung |= set(KEY_GHEP_DONG)
    dung.add("seller.tabs.cashflow")

    assert dung, "Không tìm thấy key nào - regex hỏng chứ không phải màn hình rỗng"
    assert not (dung - vi), f"Thiếu key tiếng Việt: {sorted(dung - vi)}"
    assert not (dung - en), f"Thiếu key tiếng Anh: {sorted(dung - en)}"


def test_moi_helper_expenses_goi_deu_co_that_trong_trang_seller():
    """Bắt lại đúng lỗi từng xảy ra ở purchasing.js: gọi hàm chỉ có ở pos.js."""
    source = "\n".join(
        line.split("//")[0] for line in _read("static/js/expenses.js").splitlines()
    )
    declared = _declared_functions(
        "static/js/expenses.js",
        "static/js/seller.js",
        "static/js/api.js",
        "static/js/i18n.js",
    )
    called = set(
        re.findall(
            r"\b((?:escapeHtml|showToast|showCustomConfirm|apiCall|dinhDang)[A-Za-z]*)\s*\(",
            source,
        )
    )
    thieu = sorted(called - declared)
    assert not thieu, f"expenses.js gọi helper không có trong trang seller: {thieu}"


def test_tab_dong_tien_mac_dinh_an_va_chi_mo_cho_chu_shop():
    html = _read("static/seller.html")
    seller_js = _read("static/js/seller.js")

    assert 'id="tabCashflow"' in html
    # Mặc định ẩn trong HTML: nhân viên tải trang về không thấy tab nào nhấp nháy
    # rồi biến mất. Server vẫn là lớp chặn thật.
    khoi = html[html.index('id="tabCashflow"'):]
    assert 'style="display:none;"' in khoi[:khoi.index("</button>")]

    assert "if (tabId === 'cashflow' && !XEM_DUOC_GIA_VON)" in seller_js
    assert "tabCashflow" in seller_js
    assert "if (tabId === 'cashflow') window.FSellingExpenses?.load?.()" in seller_js
    # Đổi cửa hàng phải xóa số của shop cũ, không để nó nằm lại trên màn hình.
    assert "window.FSellingExpenses?.resetForShopChange?.()" in seller_js


def test_form_chi_phi_canh_bao_chong_tru_hai_lan_voi_phieu_huy():
    """Hàng hỏng/hết hạn đã bị trừ vào lãi gộp qua phiếu hủy.

    Nếu chủ shop gõ lại số đó vào sổ chi phí thì cùng một thùng hàng bị trừ hai
    lần và lãi ròng thấp hơn sự thật. Cảnh báo phải nằm NGAY TRÊN form, không
    phải trong tài liệu hướng dẫn.
    """
    html = _read("static/seller.html")
    locales = _read("static/js/locales/seller.js")
    assert 'data-i18n="seller.cashflow.write_off_warning"' in html
    assert "Hủy hàng" in locales
    # Và tuyệt đối không có danh mục mặc định nào mời người dùng làm việc đó.
    from fselling.services import expense_service

    for ten in expense_service.DEFAULT_CATEGORIES:
        thap = ten.lower()
        assert "hao hụt" not in thap
        assert "hàng hỏng" not in thap
        assert "hết hạn" not in thap


def test_giu_nguyen_ma_thao_tac_khi_thu_lai():
    """Mất mạng giữa chừng: lần bấm sau phải gửi lại ĐÚNG mã cũ.

    Sinh mã mới là server coi đây là khoản chi thứ hai và trừ két hai lần.
    """
    js = _read("static/js/expenses.js")
    assert "state.pendingExpense?.operation_id || newOperationId()" in js
    assert "savePending({ operation_id: payload.operation_id })" in js
    assert "savePending(null)" in js
    assert "cfExpenseRetryNotice" in js


def test_quy_tac_cong_thang_cua_giao_dien_khop_voi_server():
    """Giao diện chỉ HIỆN XEM TRƯỚC; số được lưu do server tính.

    Nhưng hai bên vẫn phải ra cùng một ngày, nếu không người dùng bấm "3 tháng",
    nhìn thấy 14/11 rồi hệ thống lưu một ngày khác.
    """
    from datetime import date

    from fselling.services import expense_service

    js = _read("static/js/expenses.js")
    # Client gửi SỐ THÁNG, không gửi ngày kết thúc - đó là thứ giữ một nguồn sự thật.
    assert "payload.amortize_months = state.months" in js
    assert "amortize_end_date" not in _function(
        js, "async function submitExpense()", "function recordTemplate("
    )

    assert expense_service.moc_ket_thuc_phan_bo(date(2026, 8, 15), 3) == date(2026, 11, 14)
    assert expense_service.moc_ket_thuc_phan_bo(date(2026, 1, 31), 1) == date(2026, 2, 27)


def test_bieu_do_noi_ro_duong_cong_don_khong_phai_so_du_ket():
    """Đường cộng dồn bắt đầu từ 0 ở đầu kỳ, KHÔNG phải tiền đang có trong két.

    Thiếu câu này thì người xem đọc đường xanh thành "tôi đang có bằng này tiền".
    """
    locales = _read("static/js/locales/seller.js")
    html = _read("static/seller.html")
    assert 'data-i18n="seller.cashflow.chart_hint"' in html
    assert "không phải số tiền đang có trong két" in locales
