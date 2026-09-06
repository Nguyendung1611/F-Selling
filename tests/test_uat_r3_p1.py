from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_disabled_vietqr_names_the_reason_and_keeps_recovery_link():
    html = read("static/pos.html")
    source = read("static/js/pos.js")
    locale = read("static/js/locales/pos.js")

    assert 'id="btnMethodQRLabel"' in html
    capability = source[
        source.index("function setTransferCapability") : source.index(
            "function updateTransferCapability"
        )
    ]
    assert "pos.payment.transfer_setup_required" in capability
    assert "button.title" in capability
    assert locale.count("'pos.payment.transfer_setup_required':") == 2
    assert 'id="qrSetupHint"' in html
    assert 'href="/seller?setup=bank"' in html


def test_core_uat_actions_show_a_processing_state_while_requests_run():
    onboarding = read("static/js/onboarding-r2.js")
    seller_locale = read("static/js/locales/seller.js")
    pos = read("static/js/pos.js")

    set_busy = onboarding[
        onboarding.index("function setBusy") : onboarding.index(
            "function showInlineError"
        )
    ]
    assert "ph-spinner-gap ph-spin" in set_busy
    assert "seller.first_run.saving" in set_busy
    assert seller_locale.count("'seller.first_run.saving':") == 2

    checkout_button = pos[
        pos.index("function capNhatNutCheckout") : pos.index(
            "function taoTrangThaiCheckout"
        )
    ]
    assert "checkoutBusy" in checkout_button
    assert "htmlNut('ph-spinner-gap ph-spin', 'pos.processing')" in checkout_button


def test_first_product_quantity_has_a_localized_numeric_example():
    html = read("static/seller.html")
    locale = read("static/js/locales/seller.js")

    start = html.index('id="firstRunProductStock"')
    stock_input = html[start : html.index(">", start)]
    assert 'placeholder="10"' in stock_input
    assert 'data-i18n-placeholder="seller.first_run.product_stock_placeholder"' in stock_input
    assert locale.count("'seller.first_run.product_stock_placeholder':") == 2
