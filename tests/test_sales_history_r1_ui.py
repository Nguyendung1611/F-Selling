import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_sales_history_node_harness():
    completed = subprocess.run(
        ["node", "tests/js/pos-sales-history-r1.test.js"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "pos-sales-history-r1 harness: passed" in completed.stdout


def test_pos_hosts_sales_history_assets_and_accessible_dialog():
    html = (ROOT / "static/pos.html").read_text(encoding="utf-8")
    assert 'id="btnSalesHistory"' in html
    assert 'onclick="moLichSuDon()"' in html
    assert 'id="btnOldReceipt"' not in html
    assert 'id="oldReceiptModal"' not in html
    assert 'id="salesHistoryModal"' in html
    assert 'role="dialog"' in html
    assert 'aria-labelledby="salesHistoryTitle"' in html
    for element_id in (
        "salesHistorySearch",
        "salesHistorySubmit",
        "salesHistoryToday",
        "salesHistory7d",
        "salesHistoryList",
        "salesHistoryLoadMore",
        "salesHistoryDetail",
    ):
        assert f'id="{element_id}"' in html
    assert "/css/pos-sales-history-r1.css?v=20260830-r1" in html
    assert "/js/pos-sales-history-r1.js?v=20260830-r1" in html
    assert html.count("sales-history=20260830-r1") == 2


def test_sales_history_copy_exists_in_both_locales():
    locale = (ROOT / "static/js/locales/pos.js").read_text(encoding="utf-8")
    for key in (
        "pos.sales_history.open",
        "pos.sales_history.search_placeholder",
        "pos.sales_history.today",
        "pos.sales_history.seven_days",
        "pos.sales_history.searching_all",
        "pos.sales_history.empty_today",
        "pos.sales_history.empty_seven_days",
        "pos.sales_history.no_results",
        "pos.sales_history.retry",
        "pos.sales_history.login_again",
        "pos.sales_history.load_more",
        "pos.sales_history.print",
        "pos.sales_history.share",
        "pos.sales_history.close",
    ):
        assert locale.count(f"'{key}'") == 2
