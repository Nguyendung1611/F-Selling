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
