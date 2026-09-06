from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_pos_stabilization_hosts_progressive_checkout_controls():
    html = _read("static/pos.html")
    for element_id in (
        "posTools",
        "posExtraInfo",
        "posCheckoutColumn",
        "btnCloseCartMobile",
        "posCartBackdrop",
        "posCartDock",
        "posCartDockCount",
        "posCartDockTotal",
    ):
        assert f'id="{element_id}"' in html

    tools = html[html.index('id="shiftBar"'):html.index('id="posCheckoutColumn"')]
    assert tools.index('id="btnSalesHistory"') < tools.index('id="posTools"')
    for tool_id in ("btnCashMovement", "btnDoiSoat", "btnReturn", "btnCloseShift"):
        assert f'id="{tool_id}"' in tools


def test_pos_stabilization_updates_cart_sheet_from_existing_cart_state():
    js = _read("static/js/pos.js")
    assert "function capNhatGioHangResponsivePOS()" in js
    assert "function moGioHangMobile()" in js
    assert "function dongGioHangMobile(" in js
    update_ui = js[js.index("function updateUI()") : js.index("function setMethod(m)")]
    assert "capNhatGioHangResponsivePOS();" in update_ui
    assert "checkout?.setAttribute('inert', '')" in js


def test_pos_stabilization_mobile_layout_keeps_checkout_reachable():
    css = _read("static/css/pos.css")
    assert ".pos-cart-dock" in css
    assert ".pos-cart-backdrop" in css
    assert ".pos-checkout-column.is-mobile-open" in css
    assert "position: fixed" in css
    assert ".pos-checkout-column.is-cart-empty .pos-payment" in css


def test_pos_stabilization_copy_exists_in_both_locales():
    locale = _read("static/js/locales/pos.js")
    for key in (
        "pos.tools.title",
        "pos.cart.empty_action",
        "pos.cart.empty_hint",
        "pos.cart.mobile_count",
        "pos.cart.view",
        "pos.cart.close",
        "pos.checkout.more_info",
        "pos.checkout.more_info_hint",
    ):
        assert locale.count(f"'{key}'") == 2
