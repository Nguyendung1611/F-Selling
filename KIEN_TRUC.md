# Kiến Trúc F-Selling (sau refactor)

Backend đã được tách từ một file `app.py` (~1.385 dòng) thành **modular monolith**.
Không có thay đổi nào về URL, JSON request/response, database, frontend hay cách deploy.

## Cây thư mục

```
python_app/
├── app.py                     # Entrypoint tương thích: `from fselling.main import app`
├── models.py                  # Shim tương thích (import models cũ vẫn chạy)
├── database.py                # Shim tương thích (import database cũ vẫn chạy)
├── fselling/
│   ├── main.py                # create_app(): middleware, include_router, mount static, lifespan
│   ├── dependencies.py        # get_db, get_current_user, require_admin, require_shop_access
│   ├── core/
│   │   ├── config.py          # BASE_DIR, UPLOAD_DIR, SECRET_KEY, CORS, log_to_file
│   │   ├── database.py        # engine / SessionLocal / Base
│   │   ├── security.py        # bcrypt, JWT, OTP, chính sách mật khẩu, compare_digest
│   │   └── bootstrap.py       # create_all + migration SQLite + seed admin
│   ├── models/                # ORM: user, shop, catalog, order, system_log
│   ├── schemas/               # Pydantic: auth, shop, catalog, order
│   ├── routers/               # Chỉ xử lý HTTP, gọi service
│   │   ├── auth.py shops.py categories.py products.py vouchers.py
│   │   ├── webhooks.py        # PHẢI include TRƯỚC orders.py (xem ghi chú bên dưới)
│   │   ├── orders.py reports.py admin.py pages.py
│   └── services/              # Toàn bộ business logic
│       ├── auth_service.py email_service.py shop_service.py catalog_service.py
│       ├── voucher_service.py inventory_service.py order_service.py
│       ├── payment_service.py report_service.py log_service.py maintenance_service.py
└── tests/                     # pytest: auth, phân quyền, đơn hàng, voucher, webhook, upload, contract
```

## Quy tắc

- **Router** chỉ nhận/validate HTTP và gọi service. Không chứa logic nghiệp vụ.
- **Service** chứa nghiệp vụ, nhận `Session` từ caller, không tự mở transaction lồng nhau.
- **core/** dùng chung cho mọi tầng; models/schemas không import ngược lên routers.
- Không có circular import (đã kiểm tra tự động).

## Ghi chú quan trọng khi thêm route

`POST /api/orders/webhook` và `POST /api/orders/{shop_id}` trùng khuôn đường dẫn.
FastAPI khớp route theo thứ tự đăng ký, nên `webhooks.router` **phải** được
`include_router` trước `orders.router` trong `fselling/main.py`.
Có test bảo vệ điều này: `tests/test_contract.py::test_webhook_dang_ky_truoc_route_shop_id`.

## Các biện pháp bảo mật (giữ nguyên)

| Biện pháp | Vị trí sau refactor |
|---|---|
| `require_shop_access()` cho endpoint theo shop | `fselling/dependencies.py` |
| Giá & tổng tiền tính lại từ DB | `services/inventory_service.py`, `services/order_service.py` |
| Webhook fail-closed + `compare_digest` | `routers/webhooks.py`, `core/security.py::compare_secret` |
| Secret lấy từ biến môi trường | `core/config.py` |
| Chỉ nhận JWT qua Authorization header | `core/security.py::extract_bearer_token` |
| Single-session bằng `session_id` | `dependencies.py::get_current_user` |
| Upload ảnh kiểm tra magic bytes | `services/catalog_service.py::is_valid_image` |
| `escapeHtml()` ở frontend | `static/js/*` (không thay đổi) |

## Chạy test

```bat
cd python_app
.venv\Scripts\activate
pip install -r requirements-dev.txt
pytest
```

Test dùng SQLite file tạm (`DB_PATH` được set trong `tests/conftest.py`), **không**
chạm vào DB thật, **không** gửi email thật và **không** gọi mạng.

## Chạy app (không đổi)

```bat
run.bat                                   :: local
uvicorn app:app --host 0.0.0.0 --port 8080 :: Docker / Fly.io
python app.py                              :: kèm ngrok
```

## Thay đổi hành vi có chủ đích (behavior fix, không phải refactor thuần)

Toàn bộ đều có test bảo vệ trong `tests/`.

1. **Voucher hết hạn giờ mới thực sự bị chặn.**
   Trường `expires_at` trước đây được lưu nhưng **không bao giờ được kiểm tra**:
   voucher quá hạn vẫn giảm giá bình thường.
   - `POST /api/vouchers/apply/{shop_id}` → trả `400 "Mã giảm giá đã hết hạn sử dụng"`.
   - `POST /api/orders/{shop_id}` → bỏ qua giảm giá (giống cách xử lý voucher hết lượt).
   - Test: `tests/test_vouchers.py::test_voucher_het_han_bi_tu_choi`,
     `::test_don_hang_bo_qua_voucher_het_han`.
   - Muốn quay lại hành vi cũ: xóa 2 khối `if is_expired(...)` trong
     `services/voucher_service.py`.

2. **Sửa chuỗi tiếng Việt bị hỏng encoding.**
   Thông báo lỗi khi tạo danh mục là `"Tên danh mục không được ��ể trống"`
   (byte hỏng trong `app.py` gốc) → nay là `"Tên danh mục không được để trống"`,
   khớp với thông báo ở endpoint sửa danh mục.

3. **OTP sinh bằng `secrets.randbelow` thay cho `random.randint`.**
   Vẫn là 6 chữ số, nhưng dùng nguồn ngẫu nhiên an toàn cho mật mã.

4. **Không ghi `session_id` vào `request_log.txt` nữa** (log ít dữ liệu nhạy cảm hơn).

5. **Bắt exception cụ thể thay vì `except Exception`** ở `log_service`,
   `email_service`, `maintenance_service`, và chỗ parse JSON của webhook.
   Rủi ro: nếu xuất hiện loại lỗi ngoài dự kiến, nó sẽ nổi lên thành 500
   thay vì bị nuốt im lặng - đây là chủ ý để không giấu lỗi.

## Bẫy cần biết khi viết service mới

### 1. Luôn `db.refresh(obj)` sau `log_system_action()` nếu còn trả object về client

`log_system_action()` gọi `db.commit()`. Commit làm **expire** mọi ORM object
trong session; với FastAPI 0.139 + Pydantic v2, object bị expire sẽ được
serialize thành `{}` (mất toàn bộ field) thay vì tự nạp lại.

```python
db.add(obj); db.commit(); db.refresh(obj)
log_system_action(db, user.id, "CREATE_X", "...")
db.refresh(obj)          # <-- BẮT BUỘC: commit trong log đã expire obj
return obj
```

Áp dụng cho: `create_shop`, `update_shop`, `create_category`, `update_category`,
`create_product`, `create_voucher`, `update_voucher`.

### 2. `LOG_FILE` cấu hình được qua biến môi trường

Mặc định vẫn là `python_app/request_log.txt`. Test set `LOG_FILE` sang thư mục
tạm để không ghi đè log thật.

### 3. Không dùng `.subquery()` cho `in_()` trong SQLAlchemy 2.0

Truyền thẳng `Query` vào `in_()` (SQLAlchemy tự coerce thành scalar subquery);
gọi `.subquery()` sẽ sinh `SAWarning` về coercion.

## Phiên bản dependency

FastAPI **0.139.0** + Starlette **1.3.1** (bản đang cài trong `.venv`).
**Không downgrade** — code và test đã được điều chỉnh theo cấu trúc router
lồng nhau (lazy router) của bản này; `tests/test_contract.py::_iter_routes`
duyệt đệ quy qua `original_router` để lấy đủ route.

## Trạng thái kiểm chứng

| Hạng mục | Kết quả |
|---|---|
| `pytest` | 84/84 pass (chạy trên Windows venv) |
| `compileall` | pass |
| `pip check` | pass |
| Uvicorn khởi động + `GET /` | HTTP 200 |
| So khớp 47 route trước/sau refactor | trùng khớp hoàn toàn |
| Circular import (42 module) | không có |
| Quét secret hardcode | sạch |
| Docker build | **chưa kiểm tra** - không có Docker trong môi trường |
