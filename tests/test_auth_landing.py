from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_login_root_explains_value_and_the_three_step_first_run_path():
    html = _read("static/index.html")

    assert 'class="auth-landing"' in html
    assert 'data-i18n="login.hero_title"' in html
    assert 'data-i18n="login.hero_body"' in html
    assert html.count('class="landing-step"') == 3
    for key in (
        "login.step_shop",
        "login.step_catalog",
        "login.step_sell",
    ):
        assert f'data-i18n="{key}"' in html

    # Landing is an enhancement of the proven login route, not a second app.
    assert 'id="loginForm"' in html
    assert 'href="/register"' in html


def test_auth_landing_is_bilingual_and_mobile_responsive():
    locale = _read("static/js/locales/auth-admin.js")
    css = _read("static/css/auth.css")

    for key in (
        "login.hero_eyebrow",
        "login.hero_title",
        "login.hero_body",
        "login.step_shop",
        "login.step_catalog",
        "login.step_sell",
    ):
        assert locale.count(f"'{key}':") == 2

    assert ".auth-landing" in css
    assert ".landing-step" in css
    assert "@media (max-width: 900px)" in css
