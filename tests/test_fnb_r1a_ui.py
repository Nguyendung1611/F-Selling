import re
import subprocess
import uuid
from pathlib import Path

from conftest import (
    auth,
    create_fnb_area,
    create_fnb_table,
    enable_fnb,
    new_staff,
    seller_with_shop,
)


ROOT = Path(__file__).resolve().parents[1]


def _catalog_keys(path: Path, locale: str) -> set[str]:
    content = path.read_text(encoding="utf-8")
    marker = f"Object.assign(resources.{locale}.translation, {{"
    start = content.index(marker) + len(marker)
    end_marker = (
        "Object.assign(resources.en.translation, {"
        if locale == "vi"
        else "})(window);"
    )
    end = content.index(end_marker, start)
    return set(re.findall(r"^\s*'([^']+)'\s*:", content[start:end], re.MULTILINE))


def test_fnb_page_and_assets_are_wired(client):
    page = client.get("/fnb")
    assert page.status_code == 200
    html = page.text
    for element_id in (
        "fnbFloor",
        "fnbSessionPanel",
        "fnbLiveStatus",
        "fnbSetupOpen",
        "fnbSetupDialog",
    ):
        assert f'id="{element_id}"' in html
    assert "/css/fnb-r1a.css?" in html
    assert "/js/locales/fnb.js?" in html
    assert "/js/fnb-r1a.js?" in html
    assert client.get("/fnb.html", follow_redirects=False).headers["location"] == "/fnb"
    api_source = (ROOT / "static/js/api.js").read_text(encoding="utf-8")
    assert "error.detail =" in api_source


def test_pos_entry_is_hidden_until_shop_capability_is_known():
    html = (ROOT / "static/pos.html").read_text(encoding="utf-8")
    assert 'id="btnTableService"' in html
    assert "hidden" in html.split('id="btnTableService"', 1)[1].split(">", 1)[0]
    source = (ROOT / "static/js/pos.js").read_text(encoding="utf-8")
    assert "function updateFnbCapability()" in source
    assert "localStorage.setItem('currentShopId'" in source
    assert "navigateToPage('/fnb')" in source


def test_owner_edit_switch_and_bilingual_contracts():
    seller_html = (ROOT / "static/seller.html").read_text(encoding="utf-8")
    seller_js = (ROOT / "static/js/seller.js").read_text(encoding="utf-8")
    assert seller_html.count('id="shopFnbEnabled"') == 1
    assert 'id="shopFnbSetting"' in seller_html
    assert "const fnbSettingOperations = new Map();" in seller_js
    assert "MY_ROLE === 'SELLER'" in seller_js
    assert "shopFnbEnabled.disabled = true" in seller_js

    fnb_path = ROOT / "static/js/locales/fnb.js"
    vi_keys = _catalog_keys(fnb_path, "vi")
    en_keys = _catalog_keys(fnb_path, "en")
    assert vi_keys == en_keys
    assert {
        "fnb.title",
        "fnb.state.loading",
        "fnb.state.no_tables",
        "fnb.state.poll_error",
        "fnb.state.offline",
        "fnb.state.conflict",
        "fnb.action.reapply",
        "fnb.setup.open",
        "fnb.setup.inactive",
        "fnb.auth.feature_disabled",
    } <= vi_keys

    for path, keys in (
        (ROOT / "static/js/locales/pos.js", {"pos.mode.table_service"}),
        (
            ROOT / "static/js/locales/seller.js",
            {
                "seller.shops.fnb_label",
                "seller.shops.fnb_hint",
                "seller.shops.fnb_enabled",
                "seller.shops.fnb_disabled",
            },
        ),
    ):
        assert keys <= _catalog_keys(path, "vi")
        assert keys <= _catalog_keys(path, "en")


def test_dynamic_fnb_content_uses_delegation_not_inline_handlers():
    source = (ROOT / "static/js/fnb-r1a.js").read_text(encoding="utf-8")
    assert "onclick" not in source.lower()
    assert "data-action" in source
    assert "addEventListener('click'" in source or 'addEventListener("click"' in source
    assert "event.key === 'Escape'" in source


def test_setup_button_stays_hidden_without_an_enabled_shop():
    source = (ROOT / "static/js/fnb-r1a.js").read_text(encoding="utf-8")
    assert "elements.fnbSetupOpen.hidden = !(setupAllowed && shops.length);" in source


def test_manager_floor_snapshot_can_include_hidden_setup_rows(client):
    ctx = seller_with_shop(client)
    enable_fnb(client, ctx)
    area = create_fnb_area(client, ctx, "Sân sau")
    table = create_fnb_table(client, ctx, area["id"], "Bàn khuất")

    hidden_table = client.patch(
        f"/api/fnb/tables/{table['id']}",
        json={
            "active": False,
            "expected_revision": table["fnb_revision"],
            "expected_state_version": table["state_version"],
            "operation_id": f"hide-table-{uuid.uuid4().hex}",
        },
        headers=auth(ctx["token"]),
    )
    assert hidden_table.status_code == 200
    hidden_area = client.patch(
        f"/api/fnb/areas/{area['id']}",
        json={
            "active": False,
            "expected_revision": hidden_table.json()["fnb_revision"],
            "operation_id": f"hide-area-{uuid.uuid4().hex}",
        },
        headers=auth(ctx["token"]),
    )
    assert hidden_area.status_code == 200

    default_floor = client.get(
        "/api/fnb/floor",
        params={"shop_id": ctx["shop_id"]},
        headers=auth(ctx["token"]),
    )
    assert default_floor.status_code == 200
    assert default_floor.json()["areas"] == []

    owner_floor = client.get(
        "/api/fnb/floor",
        params={"shop_id": ctx["shop_id"], "include_inactive": True},
        headers=auth(ctx["token"]),
    )
    assert owner_floor.status_code == 200
    assert owner_floor.json()["areas"][0]["active"] is False
    assert owner_floor.json()["areas"][0]["tables"][0]["active"] is False

    for staff_role, expected in (
        ("MANAGER", 200),
        ("CASHIER", 403),
        ("WAREHOUSE", 403),
    ):
        _, token = new_staff(client, ctx, staff_role)
        response = client.get(
            "/api/fnb/floor",
            params={"shop_id": ctx["shop_id"], "include_inactive": True},
            headers=auth(token),
        )
        assert response.status_code == expected


def test_fnb_controller_node_harness():
    result = subprocess.run(
        ["node", "tests/js/fnb-r1a.test.js"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
