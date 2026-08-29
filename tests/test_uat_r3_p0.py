from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_registration_success_explicitly_tells_user_to_check_email():
    source = read("static/js/register.js")
    locale = read("static/js/locales/auth-admin.js")
    verify_html = read("static/verify.html")

    assert "nhanSangTrangSau(t('register.success_redirect'))" in source
    assert "navigateToPage('/verify')" in source
    assert "Hãy kiểm tra email để lấy mã xác thực" in locale
    assert "Check your email for the verification code" in locale
    assert 'data-i18n="verify.instructions"' in verify_html


def test_first_product_price_names_vnd_and_uses_an_unformatted_example():
    html = read("static/seller.html")
    locale = read("static/js/locales/seller.js")

    price_input = html[
        html.index('id="firstRunProductPrice"') : html.index(">", html.index('id="firstRunProductPrice"'))
    ]
    assert 'data-i18n-placeholder="seller.first_run.product_price_placeholder"' in price_input
    assert 'placeholder="10000"' in price_input
    assert "'seller.first_run.product_price': 'Giá bán (đồng)'" in locale
    assert "'seller.first_run.product_price': 'Sale price (VND)'" in locale
    assert locale.count("'seller.first_run.product_price_placeholder':") == 2
