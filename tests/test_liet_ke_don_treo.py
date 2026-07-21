import os
import sqlite3
import subprocess
import sys
from pathlib import Path


def test_script_in_duoc_ten_tieng_viet_tren_console_cp1252(tmp_path):
    db_path = tmp_path / "legacy.db"
    con = sqlite3.connect(db_path)
    try:
        con.executescript(
            """
            CREATE TABLE shops (id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE orders (
                id INTEGER PRIMARY KEY,
                shop_id INTEGER,
                total_amount REAL,
                status TEXT,
                created_at TEXT
            );
            CREATE TABLE products (
                id INTEGER PRIMARY KEY,
                shop_id INTEGER,
                name TEXT,
                stock INTEGER
            );
            CREATE TABLE order_items (
                id INTEGER PRIMARY KEY,
                order_id INTEGER,
                product_name TEXT,
                quantity INTEGER
            );
            INSERT INTO shops VALUES (1, 'Shop test');
            INSERT INTO products VALUES (1, 1, 'Phấn mắt', 9);
            INSERT INTO orders VALUES (1, 1, 100000, 'PENDING', '2026-01-01 00:00:00');
            INSERT INTO order_items VALUES (1, 1, 'Phấn mắt', 1);
            """
        )
        con.commit()
    finally:
        con.close()

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "cp1252"
    script = Path(__file__).resolve().parent.parent / "liet_ke_don_treo.py"
    result = subprocess.run(
        [sys.executable, str(script), "--db", str(db_path)],
        env=env,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    assert "Phấn mắt" in result.stdout.decode("utf-8")
