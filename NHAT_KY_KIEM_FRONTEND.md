# NHẬT KÝ KIỂM THỬ FRONTEND F-SELLING

## Môi trường

- Thời gian kiểm: 2026-07-22, múi giờ Asia/Saigon.
- OS: Microsoft Windows 11 Home 10.0.26200 (build 26200).
- Trình duyệt: Codex In-app Browser, Browser plugin build `26.715.61943`. API điều khiển không công bố phiên bản engine Chromium cụ thể.
- Repo: branch `main`, HEAD ban đầu `bf2ac0ce89f3e8e1a668e484374f63d9d0676432`.
- Server kiểm thử: `http://127.0.0.1:18777`, Uvicorn chạy bằng `.venv\Scripts\python.exe`.
- DB tạm: `C:\Users\nguye\AppData\Local\Temp\fselling_frontend_browser_9f60834d4b2443d4bad703f4f4626992\fselling_frontend.db` (đã xóa sau kiểm thử).
- `DB_PATH`, `UPLOAD_DIR`, `LOG_FILE`, `SECRET_KEY`, `ORDER_PENDING_TIMEOUT_MINUTES=0` đều trỏ/cấu hình riêng cho tiến trình tạm. Không sửa `.env`.
- Dữ liệu bấm thử: seller `frontend_ui_20260722`, admin `frontend_admin_20260722`, shop `Shop kiểm thử Frontend`, 3 sản phẩm, voucher `FRONTEND10K`, 57 đơn để tạo 2 trang (50 + 7). Tất cả chỉ nằm trong DB tạm.
- Trang Seller và POS đều được hard reload bằng `Ctrl+F5`; sau behavior fix dùng `Control+F5` và URL cache-bust để chắc chắn HTML/JS mới được tải.

## Kết quả A1..G4

| Mục | Kết quả | Quan sát cụ thể |
|---|---|---|
| A1 | PASS | Lọc `14/07/2026`–`18/07/2026`: bảng còn 6 đơn `#30`–`#35`; thống kê đổi thành `940,000 ₫ / 6 đơn / 7 SP`. Biểu đồ đường đổi sang các mốc 14, 16, 18/07 và biểu đồ tròn hiển thị Beta/Alpha/Gamma theo dữ liệu trong khoảng. |
| A2 | PASS | Lọc cùng ngày `18/07/2026`: vẫn hiện `#35` lúc 22:45 và `#34` lúc 09:30, không bị rỗng; thống kê `340,000 ₫ / 2 đơn / 3 SP`. |
| A3 | PASS | Bấm `Bỏ lọc`: hai input ngày về rỗng, thống kê về `5,340,000 ₫ / 57 đơn / 53 SP`, bảng về trang 1. |
| A4 | PASS | Nhập Từ ngày `20/07/2026` > Đến ngày `10/07/2026`: toast hiện đúng `Từ ngày không được lớn hơn đến ngày`; số request dashboard/stats giữ nguyên `9/9`, tức không gọi API. |
| B1 | PASS | Trang đầu: `Hiển thị 1-50 trên tổng 57 đơn`; trang cuối: `Hiển thị 51-57 trên tổng 57 đơn`. |
| B2 | PASS | Trang 1 chứa 50 ID, trang 2 chứa `#206`…`#200`; hợp hai tập đủ 57 đơn, không trùng và không mất. Bấm Sau rồi Trước trả đúng danh sách ban đầu. |
| B3 | PASS | Trang 1: `← Trước` disabled, `Sau →` enabled. Trang 2: `← Trước` enabled, `Sau →` disabled. |
| B4 | PASS | Đang ở trang 2, bấm Lọc khoảng 14–18/07 thì UI quay về trang 1 (`Hiển thị 1-6...`). |
| C1 | PASS | Modal đơn `#37` hiện đúng `Sản phẩm Alpha/Beta/Gamma`, đơn giá `100,000/200,000/50,000 ₫`, SL 1 và thành tiền từng dòng. Dữ liệu seed ban đầu bị PowerShell thay dấu tiếng Việt bằng `?`; đã sửa riêng DB tạm bằng Unicode escape rồi bấm kiểm lại, không phải lỗi ứng dụng. |
| C2 | PASS | Modal `#37`: tạm tính và tổng cộng đều `1,400,000 ₫`, khớp cột Tổng tiền ở bảng. |
| C3 | PASS | Modal `#34`: tạm tính `350,000 ₫`, dòng màu cam `Giảm giá (FRONTEND10K): -10,000 ₫`, tổng cộng `340,000 ₫`. |
| C4 | PASS | Bấm `Đóng` làm `#orderDetailModal` đổi từ `display:flex` sang `display:none`. |
| C5 | PASS | Đơn `#37` có 12 dòng; vùng bảng `overflow-y:auto`, `scrollHeight=692`, `clientHeight=305`, nên cuộn nội bộ hoạt động. |
| D1 | PASS | Bảng hiện đủ: `Chờ thanh toán` màu cam `rgb(245,158,11)`, `Đã thanh toán` xanh `rgb(16,185,129)`, `Đã hủy` xám `rgb(148,163,184)`, `Cần đối soát` đỏ `rgb(239,68,68)`. Không có chữ trạng thái thô. |
| D2 | PASS | Modal `#37` hiện `Chờ thanh toán`; modal `#34` hiện `Đã thanh toán`, đều là nhãn tiếng Việt. |
| E1 | PASS | Tạo đơn VietQR: ảnh QR hiện, bên dưới có `Xác nhận Đã Nhận Tiền` và `Hủy đơn & Hoàn kho`. |
| E2 | PASS | Nút hủy mở native dialog loại `confirm`. Nhánh không chấp nhận giữ đơn `#233` ở `PENDING`, tồn kho Alpha giữ `99`, QR/giỏ vẫn mở và chưa có POST cancel. |
| E3 | KHONG KIEM DUOC | Nhánh xác nhận đã thực sự gọi `POST /api/orders/230/cancel` → 200, đơn thành `CANCELLED`, tồn kho `99 → 100`, POS reset. Tuy nhiên Browser giữ native dialog quá lâu nên toast ngắn đã hết trước khi DOM đọc lại; không thể xác nhận trực quan đúng câu toast cho riêng nhánh này. Không thấy lỗi dữ liệu/nghiệp vụ. |
| E4 | PASS | Tạo đơn `#234`, dùng phiên admin gọi API hủy từ ngoài để không làm mất single-session của seller. Polling bắt được sau 250 ms: toast `Đơn đã bị hủy, hàng đã được hoàn về kho.`, QR biến mất, POS reset. |
| F1 | PASS | `dev.logs` toàn bộ mức debug/info/log/warn/error trả về 0 dòng; không có lỗi đỏ hay warning Console. |
| F2 | PASS sau fix | Trước fix request chỉ có `?page=1`. Sau fix Network/access log ghi đúng `?page=1&per_page=50&tu_ngay=2026-07-18&den_ngay=2026-07-18`; stats nhận đúng `tu_ngay/den_ngay`. |
| F3 | PASS sau fix | Các request UI/API cần thiết trả 200. Browser từng tự gọi `/favicon.ico` và nhận 404; đã thêm route 204 tối thiểu, regression test và HTTP smoke đều xác nhận 204. Hai dòng 405/401 trong log cũ là lệnh shell kiểm thử gõ sai `/api/login` và token trống, không phải request từ UI. |
| G1 | PASS sau fix | Trước fix chỉ có nút bật/tắt và xóa, không có Sửa. Sau fix: thêm `UI-G1` (toast thành công), mở form Sửa có dữ liệu điền sẵn, đổi tên/giá/tồn thành `Sản phẩm Browser CRUD đã sửa / 123,999 ₫ / 8` (toast `Đã cập nhật sản phẩm!`), sau đó ẩn thành `INACTIVE`. |
| G2 | PASS | Tạo voucher `UI50` giá trị 5,000 (toast thành công), sửa thành 7,000 (toast cập nhật), xóa qua custom confirm (toast xóa); dòng biến mất khỏi bảng. |
| G3 | PASS | Sửa SĐT shop từ `0901000000` thành `0901000001`; toast `Cập nhật cửa hàng thành công!`, DB tạm xác nhận giá trị mới. |
| G4 | PASS | Admin dashboard hiện `Shop kiểm thử Frontend — 5,340,000 ₫`; tab Nhật ký hiện các dòng LOGIN, UPDATE_SHOP, DELETE_VOUCHER, UPDATE_VOUCHER đúng dữ liệu vừa bấm. |

## Ảnh chụp lỗi

- `NHAT_KY_FRONTEND_FAIL_G1.png`: trạng thái trước fix cho thấy mỗi sản phẩm chỉ có nút bật/tắt và xóa, không có thao tác Sửa.

## Console và Network

- Console: không có log, warning hoặc error (`0` dòng trên toàn bộ phiên Browser).
- Query cuối sau fix:
  - `GET /api/dashboard/seller/6?page=1&per_page=50` → 200.
  - `GET /api/dashboard/seller/6?page=1&per_page=50&tu_ngay=2026-07-18&den_ngay=2026-07-18` → 200.
  - `GET /api/shops/6/stats?tu_ngay=2026-07-18&den_ngay=2026-07-18` → 200.
- Smoke cuối: `GET /` → 200; `GET /favicon.ico` → 204.

## Bug tìm được và behavior fix

### 1. Kho hàng thiếu hoàn toàn thao tác sửa sản phẩm

- Mức độ: Medium — trái với CRUD sản phẩm và làm seller không thể sửa sai tên/giá/tồn.
- Tái hiện: Seller → Kho hàng → chọn shop → nhìn cột Hành động. Trước fix chỉ có bật/tắt và xóa.
- Test đỏ trước fix: 3 test API update trả 405; test contract frontend không tìm thấy `editProduct`/nút hủy chỉnh sửa.
- Fix tối thiểu:
  - Thêm `PUT /api/products/{product_id}` dạng multipart, kiểm quyền shop, giá/tồn, danh mục cùng shop, trùng tên và ảnh mới tùy chọn.
  - Thêm nút Sửa, trạng thái edit/cancel và tái sử dụng form sản phẩm.
  - Thêm test owner sửa được, seller khác bị 403, giá/tồn sai bị 400 và contract UI.
- Ảnh trước fix: `NHAT_KY_FRONTEND_FAIL_G1.png`.

### 2. Frontend không gửi `per_page`

- Mức độ: Low — backend default 50 nên phân trang vẫn chạy, nhưng Network không đúng contract cần kiểm và frontend phụ thuộc ngầm vào default backend.
- Tái hiện: bấm Dashboard rồi xem request `/api/dashboard/seller/6?page=1`.
- Test đỏ trước fix: thiếu hằng `DON_MOI_TRANG` và `p.set('per_page', ...)`.
- Fix tối thiểu: khai báo `DON_MOI_TRANG = 50` và luôn thêm `per_page=50` vào query.

### 3. Browser nhận 404 cho `/favicon.ico`

- Mức độ: Low — không ảnh hưởng nghiệp vụ nhưng vi phạm tiêu chí không có request 4xx ngoài dự kiến.
- Test đỏ trước fix: `GET /favicon.ico` trả 404.
- Fix tối thiểu: route ngoài schema trả 204; test và smoke cuối đều xanh.

## Lệnh kiểm tra cuối

```text
.venv\Scripts\python.exe -m pytest -q
→ 193 test được chạy: 192 passed, 1 skipped

node --check static\js\api.js
node --check static\js\pos.js
node --check static\js\seller.js
→ cả 3 exit code 0

.venv\Scripts\python.exe -m compileall -q app.py fselling tests
→ exit code 0

.venv\Scripts\python.exe -m pip check
→ No broken requirements found.
```

Test regression đã được chạy ở trạng thái đỏ trước khi sửa:

- Product update + UI edit/per_page: `5 failed`.
- Favicon: `1 failed` (404).

Sau sửa, targeted test đều xanh và toàn bộ suite xanh như trên. Warning duy nhất của pytest là `StarletteDeprecationWarning` về `httpx`/`TestClient`; không phải failure và không downgrade dependency.

## Việc không kiểm được

- Phiên bản engine Chromium cụ thể: Browser API chỉ công bố tên `Codex In-app Browser` và plugin build, không công bố engine version.
- E3: không bắt kịp text toast của nhánh nhấn OK vì vòng đời native confirm của Browser; các tín hiệu server, DB, tồn kho và reset POS đều đã xác minh.

## Dọn dẹp và bảo toàn dữ liệu

- Đã đóng toàn bộ tab Browser của phiên kiểm thử.
- Đã dừng đúng Uvicorn tạm trên cổng 18777; kiểm tra cuối `port18777=0`.
- Đã xóa DB, upload và toàn bộ thư mục tạm; `temp_exists=False`.
- Không dừng server sẵn có của người dùng ở cổng 8000 (PID 31288).
- `.env` không đổi: SHA-256 đầu/cuối `BEB10DCBEC85CCE64E3C528C4F45B0E6B3B3440406BBF996C85B20E7B0C18BE9`.
- `fselling.db`, `fselling_v2.db`, `fselling_v3.db` không đổi SHA-256, size và mtime.
- `fselling_v4.db` không đổi size/mtime và logical SHA3: `0ec66e52daddab5ffb4b52a0befba54ef5ded3c2ac703cd5a4f12eb6`.
- `request_log.txt` **có đổi ngoài tiến trình kiểm thử**: từ SHA-256 `2850D6AC98A23A73E13DBEAF8583BB324D225377D90B9DE3ED685D743A3A053E` (1,112,489 byte) thành `6B32F6A0DCEFD82F5DC74DAF4C5DA32917105FA0BED7642E87C6D20C6B6ADA5D` (1,117,448 byte). Nguyên nhân: server người dùng đã chạy sẵn ở cổng 8000 và tiếp tục ghi log trong suốt phiên. Server kiểm thử dùng `LOG_FILE` trong thư mục tạm, sau đó đã xóa; tôi không sửa, xóa hay hoàn nguyên `request_log.txt` gốc.
- Không push, không deploy, không downgrade dependency, không commit. Working tree được để lại để xem.
