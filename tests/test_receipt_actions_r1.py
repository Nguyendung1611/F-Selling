"""Receipt R1 browser-action behavior contract."""

from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_receipt_actions_node_harness():
    completed = subprocess.run(
        ["node", "tests/js/receipt-actions-r1.test.js"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "receipt-actions-r1 harness: 14 passed" in completed.stdout
