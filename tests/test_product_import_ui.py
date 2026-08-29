"""Static UI contract for the owner-only product import flow."""
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
HTML = (ROOT / "static" / "seller.html").read_text(encoding="utf-8")
JS = (ROOT / "static" / "js" / "seller.js").read_text(encoding="utf-8")
API_JS = (ROOT / "static" / "js" / "api.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "css" / "seller.css").read_text(encoding="utf-8")
LOCALE = (ROOT / "static" / "js" / "locales" / "seller.js").read_text(
    encoding="utf-8"
)


def test_import_controls_are_in_warehouse_and_owner_only_in_js():
    for marker in (
        'id="productImportPanel"',
        'id="productImportFile"',
        'id="productImportPreview"',
        'id="productImportCommit"',
        'id="productImportUndo"',
        'accept=".xlsx,.csv"',
        "/templates/fselling-mau-nhap-san-pham.xlsx",
    ):
        assert marker in HTML
    assert "MY_ROLE === 'SELLER'" in JS
    assert "capNhatQuyenImportSanPham" in JS
    assert "subTab !== 'products'" in JS


def test_import_uses_formdata_preview_commit_and_operation_id():
    assert "body instanceof FormData" in API_JS
    assert "/imports/preview" in JS
    assert "/imports/commit" in JS
    assert "/undo" in JS
    assert "taoProductImportOperationId" in JS
    assert "new FormData()" in JS


def test_import_has_recovery_states_locales_and_mobile_css():
    for key in (
        "seller.product_import.title",
        "seller.product_import.preview",
        "seller.product_import.commit",
        "seller.product_import.undo",
        "seller.product_import.invalid_file",
        "seller.product_import.network_retry",
        "seller.product_import.no_rows",
    ):
        assert key in LOCALE
    assert ".product-import-panel" in CSS
    assert ".product-import-results" in CSS
    assert "@media (max-width: 520px)" in CSS
