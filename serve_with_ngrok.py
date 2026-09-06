"""Run the local F-Selling pilot and expose only its shared demo account."""
import os
import sys
import time
import threading
import urllib.request
from pathlib import Path

# A development tunnel never authorizes paid application providers.
os.environ["GEMINI_ENABLED"] = "false"
os.environ["TTS_SERVER_ENABLED"] = "false"

import uvicorn
from pyngrok import ngrok

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE_DIR = Path(__file__).resolve().parent
URL_FILE = BASE_DIR / "NGROK_PUBLIC_URL.txt"

# Đặt biến môi trường nếu có
token = os.getenv("NGROK_AUTHTOKEN")
if token:
    ngrok.set_auth_token(token)

def print_banner(public_url: str):
    print("\n" + "=" * 70, flush=True)
    print("  🚀 LINK NGROK CÔNG KHAI ĐỂ TRUY CẬP (ĐÃ KÍCH HOẠT):", flush=True)
    print("  " + public_url, flush=True)
    print("=" * 70, flush=True)
    print("  📋 TÀI KHOẢN DEMO CÓ THỂ CHIA SẺ:", flush=True)
    print("  Chủ shop (SELLER):", flush=True)
    print("     - Tài khoản: demo", flush=True)
    print("     - Mật khẩu : Demo@2026", flush=True)
    print("  ⚠ Chỉ dùng dữ liệu mẫu; không nhập dữ liệu kinh doanh thật.", flush=True)
    print("=" * 70 + "\n", flush=True)


def local_ready() -> bool:
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:8000/api/health/ready", timeout=1
        ) as response:
            return response.status == 200
    except Exception:
        return False

def ngrok_watchdog():
    """Vòng lặp giám sát ngrok để tự động kết nối lại nếu bị ngắt kết nối mạng."""
    current_url = None
    while True:
        if not local_ready():
            time.sleep(1)
            continue
        try:
            tunnels = ngrok.get_tunnels()
            http_tunnel = next(
                (
                    t
                    for t in tunnels
                    if t.proto in {"https", "http"}
                    and str(t.config.get("addr", "")).endswith(":8000")
                ),
                None,
            )
            if not http_tunnel:
                # Mở tunnel mới
                tunnel = ngrok.connect(8000, "http")
                current_url = tunnel.public_url
                with open(URL_FILE, "w", encoding="utf-8") as f:
                    f.write(current_url + "\n")
                print_banner(current_url)
            else:
                if current_url != http_tunnel.public_url:
                    current_url = http_tunnel.public_url
                    with open(URL_FILE, "w", encoding="utf-8") as f:
                        f.write(current_url + "\n")
                    print_banner(current_url)
        except Exception as e:
            print(f"[NGROK WATCHDOG] Đang thử kết nối lại ngrok do lỗi: {e}", flush=True)
        time.sleep(10)

def start_server():
    if local_ready():
        raise SystemExit(
            "[LỖI] Cổng 8000 đã có F-Selling chạy. Hãy dừng server đó trước "
            "khi mở link pilot."
        )

    # Chạy watchdog trong background thread
    t = threading.Thread(target=ngrok_watchdog, daemon=True)
    t.start()

    # Chạy uvicorn trên main thread
    config = uvicorn.Config(
        "fselling.main:app",
        host="127.0.0.1",
        port=8000,
        log_level="info",
        access_log=True,
    )
    server = uvicorn.Server(config)
    try:
        server.run()
    finally:
        URL_FILE.unlink(missing_ok=True)

if __name__ == "__main__":
    start_server()
