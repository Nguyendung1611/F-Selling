"""F-Selling - modular monolith package.

Toàn bộ business logic được tách theo domain trong package này.
File `app.py` ở thư mục gốc chỉ còn là entrypoint tương thích
(`uvicorn app:app` trong Dockerfile / run.bat vẫn chạy như cũ).
"""
