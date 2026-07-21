FROM python:3.12-slim

WORKDIR /app

# Cài dependencies trước để tận dụng cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Dữ liệu bền (DB + ảnh) sẽ nằm trên volume mount tại /data
ENV DB_PATH=/data/fselling_v4.db
ENV UPLOAD_DIR=/data/uploads

EXPOSE 8080

# Chạy bằng uvicorn, lắng nghe mọi interface trên cổng 8080 (khớp fly.toml)
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
