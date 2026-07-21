"""Mo mot duong link cong khai (ngrok) tro vao server dang chay o localhost:8000."""
import os
import time
from pyngrok import ngrok

# Neu co bien moi truong NGROK_AUTHTOKEN thi dung, khong thi dua vao config da luu san
token = os.getenv("NGROK_AUTHTOKEN")
if token:
    ngrok.set_auth_token(token)

try:
    public_url = ngrok.connect(8000, "http").public_url
except Exception as e:
    print("\n[LOI] Khong mo duoc tunnel ngrok:", e)
    print("\nBan can authtoken ngrok (MIEN PHI, khong can the):")
    print("  1. Dang ky: https://dashboard.ngrok.com/signup")
    print("  2. Lay token: https://dashboard.ngrok.com/get-started/your-authtoken")
    print("  3. Chay 1 lan:  ngrok config add-authtoken <token_cua_ban>")
    print("     (hoac dat bien moi truong NGROK_AUTHTOKEN roi chay lai)")
    input("\nNhan Enter de thoat...")
    raise SystemExit(1)

print("\n" + "=" * 60)
print("  LINK CONG KHAI (gui cho nguoi khac de truy cap):")
print("  " + public_url)
print("=" * 60)
print("  Giu cua so nay mo. Nhan Ctrl+C de dung tunnel.")
print("=" * 60 + "\n")

try:
    while True:
        time.sleep(3600)
except KeyboardInterrupt:
    ngrok.disconnect(public_url)
    print("Da dung tunnel.")
