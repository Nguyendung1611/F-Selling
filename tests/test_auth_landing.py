import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_root_is_the_approved_pos_first_r11_conversion_path():
    html = _read("static/index.html")

    assert 'class="production-landing"' in html
    assert 'id="assistant-demo"' in html
    assert 'id="pos"' in html
    assert 'id="proof"' in html
    assert 'id="assistant"' in html
    assert 'id="support"' in html
    assert 'id="demo"' in html
    assert 'id="login"' in html
    assert 'id="loginForm"' in html
    assert html.count('href="/register"') >= 3
    assert html.count('href="#login"') >= 4
    assert html.count('href="tel:+84774867057"') >= 4
    assert html.count('href="https://zalo.me/0774867057"') == 2
    assert 'data-i18n="landing.r11.hero_title"' in html
    assert 'data-i18n="landing.r11.assistant_boundary"' in html
    assert 'data-i18n="landing.r11.warning_body"' in html
    assert html.index('id="pos"') < html.index('id="assistant"')
    assert "http://127.0.0.1" not in html


def test_landing_r11_uses_local_product_proof_and_no_provider_call():
    html = _read("static/index.html")

    assert 'id="askForm"' not in html
    for asset in (
        "landing-pos-cart.jpg",
        "landing-warehouse-reorder.jpg",
        "landing-seller-mobile.png",
        "landing-pos-offline.png",
        "landing-assistant-guided-task.jpg",
    ):
        assert f'src="/img/{asset}"' in html
        assert (ROOT / "static" / "img" / asset).is_file()

    for forbidden in (
        "fetch(",
        "XMLHttpRequest",
        "WebSocket",
        "EventSource",
        "sendBeacon",
        "SpeechRecognition",
        "speechSynthesis",
    ):
        assert forbidden not in html


def test_production_landing_is_bilingual_and_mobile_responsive():
    locale = _read("static/js/locales/auth-admin.js")
    html = _read("static/index.html")
    css = _read("static/css/landing-r11.css")

    for key in (
        "landing.page_title",
        "landing.nav.login",
        "landing.r11.hero_eyebrow",
        "landing.r11.hero_title",
        "landing.r11.hero_body",
        "landing.r11.proof_title",
        "landing.r11.assistant_title",
        "landing.r11.support_title",
        "landing.r11.demo_title",
        "landing.r11.faq_q1",
        "landing.r11.footer_data",
    ):
        assert locale.count(f"'{key}':") == 2

    assert '/css/landing-r11.css?v=20260828-r11-production' in html
    assert "@media (max-width: 1080px)" in css
    assert "@media (max-width: 760px)" in css
    assert "@media (max-width: 390px)" in css
    assert "@media (prefers-reduced-motion: reduce)" in css


def test_landing_r11_has_no_broken_anchors_duplicate_ids_or_missing_translations():
    html = _read("static/index.html")
    catalogs = _read("static/js/locales/common.js") + _read(
        "static/js/locales/auth-admin.js"
    )

    ids = re.findall(r'\bid="([^"]+)"', html)
    targets = {
        href[1:]
        for href in re.findall(r'\bhref="(#[^"]+)"', html)
        if href != "#"
    }
    used_keys = set(
        re.findall(r'\bdata-i18n(?:-[a-z-]+)?="([^"]+)"', html)
    )
    available_keys = set(re.findall(r"^\s*'([^']+)'\s*:", catalogs, re.MULTILINE))

    assert len(ids) == len(set(ids))
    assert targets <= set(ids)
    assert used_keys <= available_keys


def test_register_repeats_the_approved_offer_and_returns_to_login_section():
    html = _read("static/register.html")
    locale = _read("static/js/locales/auth-admin.js")

    assert 'data-i18n="register.trial_note"' in html
    assert 'href="/#login"' in html
    assert "/css/auth.css?v=20260824-production-activation-r1" in html
    assert locale.count("'register.trial_note':") == 2


def test_login_deep_link_is_revealed_after_layout_finishes():
    html = _read("static/index.html")

    assert "function revealLoginFromUrl()" in html
    assert "window.addEventListener('load', revealLoginFromUrl" in html
    assert "document.fonts.ready.then(revealLoginFromUrl)" in html
    assert "focus({ preventScroll: true })" in html


def test_demo_cta_prefills_shared_credentials_but_never_auto_submits():
    html = _read("static/index.html")
    auth_js = _read("static/js/auth.js")
    locale = _read("static/js/locales/auth-admin.js")

    assert html.count("data-demo-login") == 4  # three links plus the selector
    assert "function fillDemoLogin()" in html
    assert "username.value = 'demo'" in html
    assert "password.value = 'Demo@2026'" in html
    assert "form.dataset.demoSale = '1'" in html
    assert "get('demo') === '1'" in html
    assert 'id="demoLoginStatus"' in html
    assert locale.count("'landing.r11.demo_ready':") == 2
    assert "requestSubmit(" not in html
    assert ".submit()" not in html
    assert "e.currentTarget.dataset.demoSale === '1' && username === 'demo'" in auth_js
    assert "openDemoSale && data.role === 'SELLER'" in auth_js
    assert "navigateToPage('/pos?tour=sale')" in auth_js


def test_demo_sale_tour_is_non_blocking_and_only_appears_on_request():
    pos_html = _read("static/pos.html")
    pos_css = _read("static/css/pos.css")
    locale = _read("static/js/locales/pos.js")

    assert 'id="demoSaleGuide"' in pos_html
    assert '<details open>' in pos_html
    assert "get('tour') !== 'sale'" in pos_html
    assert "document.getElementById('demoSaleGuide').hidden = false" in pos_html
    assert 'role="dialog"' not in pos_html.split('id="demoSaleGuide"', 1)[0][-100:]
    assert ".demo-sale-guide[hidden]" in pos_css
    assert ".demo-sale-guide details:not([open])" in pos_css
    for key in (
        "pos.demo_guide.title",
        "pos.demo_guide.body",
        "pos.demo_guide.step1",
        "pos.demo_guide.step2",
        "pos.demo_guide.step3",
        "pos.demo_guide.note",
    ):
        assert locale.count(f"'{key}':") == 2
