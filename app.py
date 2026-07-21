"""Entrypoint tương thích cho F-Selling.

Toàn bộ business logic đã được tách sang package `fselling/` (modular monolith).
File này giữ nguyên để các lệnh khởi động cũ vẫn chạy y hệt:

    uvicorn app:app --host 127.0.0.1 --port 8000     (run.bat)
    uvicorn app:app --host 0.0.0.0 --port 8080       (Dockerfile / fly.io)
    python app.py                                     (chạy kèm ngrok)
"""
from fselling.main import app  # noqa: F401  (uvicorn cần biến tên `app`)

__all__ = ["app"]


if __name__ == "__main__":
    import uvicorn

    # Automatic Ngrok integration
    try:
        from pyngrok import ngrok

        try:
            public_url = ngrok.connect(8000).public_url
            print("\n" + "=" * 70)
            print(" NGROK REMOTE ACCESS TUNNEL OPENED:")
            print(f" -> {public_url}")
            print("=" * 70 + "\n")
        except Exception as e:
            error_msg = str(e)
            if "authtoken" in error_msg.lower() or "authentication" in error_msg.lower():
                print("\n" + "=" * 70)
                print("Ngrok requires Authtoken for remote access.")
                print(
                    "Register for a free account and get your token at: "
                    "https://dashboard.ngrok.com/get-started/your-authtoken"
                )
                print("=" * 70)
                token = input("Enter your Ngrok Authtoken: ").strip()
                if token:
                    ngrok.set_auth_token(token)
                    public_url = ngrok.connect(8000).public_url
                    print("\n" + "=" * 70)
                    print(" NGROK REMOTE ACCESS TUNNEL OPENED:")
                    print(f" -> {public_url}")
                    print("=" * 70 + "\n")
                else:
                    print("Skipping Ngrok. Running locally...")
            else:
                print(f"Skipping Ngrok due to connection error: {e}")
    except ImportError:
        print("pyngrok library not found. Running locally...")

    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
