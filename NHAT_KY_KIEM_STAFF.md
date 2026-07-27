# NHẬT KÝ KIỂM THỬ FRONTEND NHÓM C — NHÂN VIÊN/STAFF

Ngày kiểm thử: 2026-07-22 (Asia/Saigon)

## 1. Môi trường và phạm vi

- Repo: `python_app/`, branch `main`.
- HEAD: `07e175e3a645b2fddca9f8dfc0c290d81c50e346` — `add staff login UI and owner staff-management panel` (C1d).
- OS: Microsoft Windows 11 Home 64-bit, version `10.0.26200`, build `26200`.
- Trình duyệt: Codex In-app Browser, Chromium engine, runtime/plugin `26.715.61943`. Runtime không công bố riêng phiên bản Chromium.
- URL/cổng: `http://127.0.0.1:8765`.
- DB kiểm thử: `C:\Users\nguye\AppData\Local\Temp\fselling_staff_20260722_090516\staff_test.db` (bản sao của `fselling_v4.db`).
- Upload tạm: `C:\Users\nguye\AppData\Local\Temp\fselling_staff_20260722_090516\uploads`.
- Request log tạm: `C:\Users\nguye\AppData\Local\Temp\fselling_staff_20260722_090516\request_log.txt`.
- Đã hard reload bằng `Ctrl+F5` sau khi mở trang; sau khi máy bị tắt ngoài ý muốn, đã khởi động lại server bằng đúng DB tạm và hard reload lại.
- Dữ liệu chính: owner A `qa_owner_a_090516`, shop A `#6`; staff `qa_staff_090516`; owner B `qa_owner_b_090516`, shop B `#7`; sản phẩm A `#14`, sản phẩm B `#17`.

## 2. Kết quả A1–F2

| Mục | Kết quả | Quan sát chính xác |
|---|---|---|
| A1 | PASS | SELLER A mở `Cài Đặt` → thấy khối `Nhân viên bán hàng`, combobox chỉ có `QA Staff Shop 1 090516`. Nhập `qa_staff_090516` và mật khẩu mạnh, bấm `Thêm nhân viên`; toast `Đã thêm nhân viên`, dòng `qa_staff_090516` xuất hiện trong bảng. |
| A2 | PASS | Nhập username `qa_staff_weak_090516`, mật khẩu `weak`; toast đúng: `Mật khẩu phải bao gồm kí tự đặc biệt, chữ hoa, chữ thường và số`; bảng vẫn `Chưa có nhân viên`. |
| A3 | PASS | Dùng username đã tồn tại `qa_owner_a_090516`; toast `Tên đăng nhập đã tồn tại`; không tạo thêm dòng. |
| A4 | PASS | Bấm nút thùng rác của `qa_staff_090516`; custom confirm có tiêu đề `Xóa nhân viên`, nội dung `Xóa nhân viên "qa_staff_090516"? Tài khoản này sẽ không đăng nhập được nữa.`. Bấm `Đồng ý xóa`; toast `Đã xóa nhân viên`, bảng trở lại `Chưa có nhân viên`. |
| B1 | PASS | Đăng xuất owner, đăng nhập `qa_staff_090516`; URL đích là `/seller`. |
| B2 | PASS | Staff thấy các tab `Thống Kê`, `Kho Hàng`, `Khuyến Mãi`; không có button/tab `Cài Đặt`. |
| B3 | PASS | Dashboard, selector POS, kho và voucher chỉ hiển thị `QA Staff Shop 1 090516`; không thấy `QA Staff Shop 2 090516`. Request `GET /api/shops` của staff ghi DB trả `[6]`. |
| C1 | PASS | POS chọn đúng shop A, bấm `QA Product 1-1`, chọn `Tiền mặt`, bấm `Hoàn tất Đơn Hàng`; toast `Thu tiền mặt thành công!`. Tồn hiển thị giảm `51 → 50`; tạo đơn `#26`, trạng thái `Đã thanh toán`, tổng `10,000 ₫`. |
| C2 | PASS | Kho hàng mở sửa `QA Product 1-1`, đổi giá `10,000 → 12,500`; toast `Đã cập nhật sản phẩm!`; bảng hiển thị `12,500 ₫`, tồn vẫn `50`. |
| C3 | KHONG KIEM DUOC | Đã bấm nút `Nhập/Xuất kho`, nhưng browser runtime không hỗ trợ native `prompt()` và tự chặn với lỗi Console `prompt() is not supported`. Xác minh thay thế bằng đúng token staff: `POST /api/products/14/stock {delta:20}` → 200, tồn `70`; tiếp `{delta:-5}` → 200, tồn `65`; DB/API cuối là `65`. Backend/quyền/tính cộng trừ PASS, riêng nhập số qua hộp prompt UI không thể hoàn tất trong runtime này. |
| C4 | PASS | Staff tạo `QASTAFF090516`, giảm trực tiếp `1500`; toast `Đã tạo Voucher thành công!`, dòng mới xuất hiện. Bấm thùng rác → custom confirm `Xác nhận xóa voucher` → `Đồng ý xóa`; toast `Đã xóa Voucher!`, dòng biến mất. |
| C5 | PASS | Dashboard hiển thị doanh thu `10,000 ₫`, `1` đơn, `1` sản phẩm đã bán. Lọc `2026-07-22` đến `2026-07-22` vẫn còn đúng đơn `#26`. Bấm `Xem`: modal ghi `Tiền mặt • Đã thanh toán`, dòng `QA Product 1-1`, SL `1`, tổng `10,000 ₫`. Endpoint Excel được staff cấp quyền; click xuất đã được thực hiện nhưng runtime không phát sự kiện download để kiểm tên file. |
| D1 | PASS | Ở vai trò STAFF không có tab `Cài Đặt`, không có button sửa/đổi trạng thái/xóa shop, không có khối quản lý nhân viên. |
| D2 | PASS | Token staff gọi trực tiếp: `PUT /api/shops/6` → **404** `Không tìm thấy cửa hàng`; `DELETE /api/shops/6` → **404**; `POST /api/staff/6` → **404**; `GET /api/staff/6` → **404**. Không call nào trả 200/500. |
| D3 | PASS | Token staff shop A: `POST /api/orders/7` → **403** `Bạn không có quyền truy cập cửa hàng này`; `GET /api/dashboard/seller/7` → **403**; `POST /api/products/17/stock` → **403**. Tồn sản phẩm B trước/sau đều `51`; không bị thay đổi. |
| D4 | PASS | Chu kỳ độc lập `qa_staff_d4_090516`: chủ tạo staff → staff đăng nhập lấy token → chủ `DELETE /api/staff/member/7` trả 200 → dùng lại token cũ gọi `GET /api/shops` trả **401** `User not found`. |
| E1 | PASS | Owner A sửa tên shop qua UI (toast `Cập nhật cửa hàng thành công!`) rồi khôi phục; khóa shop thấy `INACTIVE`, mở lại thấy `ACTIVE`. Owner B mở được Kho Hàng (sản phẩm `QA Product 2-1`) và Khuyến Mãi (`QAV2090516`), sau đó xóa shop B bằng custom confirm; UI báo `Đã xóa cửa hàng thành công!` và `Chưa có cửa hàng nào.` |
| E2 | PASS | Admin dashboard hiển thị doanh thu các shop, gồm shop A `10,000 ₫`. Tab `Nhật Ký Hệ Thống` hoạt động và có cả `CREATE_STAFF` lẫn `DELETE_STAFF` cho `qa_staff_090516` và staff D4. |
| E3 | PASS | SELLER đăng nhập về `/seller`; ADMIN đăng nhập về `/admin`. |
| F1 | PASS | Đã thu toàn bộ Console. Có đúng 1 lỗi đỏ, là giới hạn runtime khi bấm nhập/xuất kho (xem mục 3). Sau khi máy khởi động lại, Console chỉ thêm 1 dòng mức `log`: `div#errorMsg` từ lần đăng nhập thử có dữ liệu form cũ, không có lỗi đỏ mới. |
| F2 | KHONG KIEM DUOC | Runtime trình duyệt không cung cấp F12/Network header inspector; Computer Use trên Chrome Windows bị dừng vì không xác định URL đủ tin cậy. Vì vậy không tuyên bố đã nhìn trực tiếp header trong Network. Xác minh thay thế: các request trực tiếp đều gửi `Authorization: Bearer <redacted>`; status D2/D3/D4 lần lượt đúng 404/403/401, không có 500. UI staff cũng gọi API có xác thực thành công (POS, giá, voucher, dashboard). |

## 3. Toàn bộ lỗi đỏ Console

```text
Error: prompt() is not supported.
    at nhapXuatKho (http://127.0.0.1:8765/js/seller.js:629:17)
    at HTMLButtonElement.onclick (http://127.0.0.1:8765/seller:1:1)
    at h (<anonymous>:1:1997)
    at S (<anonymous>:1:3494)
    at eH (<anonymous>:2:77)
    at <anonymous>:2:310
```

Đây là giới hạn của browser automation runtime đối với `window.prompt()`, không phải response 500 hoặc lỗi quyền của F-Selling. API stock tương ứng vẫn trả 200 và tính đúng.

Dòng Console không đỏ đã ghi nhận:

```text
[log] div#errorMsg (http://127.0.0.1:8765/js/auth.js)
```

## 4. Trọng tâm bảo mật D

**Không phát hiện staff lọt quyền. Không có bất kỳ call D2/D3/D4 nào trả 200 khi lẽ ra phải bị chặn.**

- D2 che giấu tài nguyên/quyền quản trị shop và staff bằng 404 đúng yêu cầu.
- D3 cách ly chéo bằng 403; tồn kho shop B không đổi.
- D4 vô hiệu token ngay khi bản ghi staff bị xóa; token cũ nhận 401.
- Không có response 500 trong các call bị chặn.

## 5. Bug, sửa code và ảnh

- Không tìm thấy bug sản phẩm cần behavior fix.
- Không sửa code, không thêm test hồi quy, không downgrade dependency.
- Không có mục `FAIL`, do đó không có ảnh FAIL phải nộp.
- Hai mục `KHONG KIEM DUOC` là giới hạn công cụ trình duyệt (native prompt và Network inspector), đã ghi rõ bằng chứng thay thế; không được ghi giả thành PASS.

## 6. Kiểm tra cuối

```text
.venv\Scripts\python.exe -m pytest -q
→ chạy đủ 100% test assertions nhưng pytest exit 1 ở cleanup do Windows từ chối xóa symlink
  C:\Users\nguye\AppData\Local\Temp\pytest-of-nguye\pytest-current
  (PermissionError WinError 5; không có test assertion fail).

.venv\Scripts\python.exe -m pytest -q --basetemp C:\Users\nguye\AppData\Local\Temp\fselling_staff_20260722_090516\pytest_final
→ 255 markers: 254 passed, 1 skipped; exit code 0.
→ 1 warning: StarletteDeprecationWarning về httpx/TestClient.

.venv\Scripts\python.exe -m compileall -q app.py fselling tests
→ exit code 0.

.venv\Scripts\python.exe -m pip check
→ No broken requirements found; exit code 0.

node --check static\js\api.js
node --check static\js\pos.js
node --check static\js\seller.js
→ cả 3 exit code 0.
```

## 7. Dọn dẹp và bảo toàn file gốc

- Uvicorn tạm PID `30300` đã dừng; cổng `8765` không còn listener.
- Đã xóa `C:\Users\nguye\AppData\Local\Temp\fselling_staff_20260722_090516`; kiểm tra cuối `TEMP_EXISTS=False`.
- SHA-256 ban đầu và sau dọn dẹp:
  - `.env`: `BEB10DCBEC85CCE64E3C528C4F45B0E6B3B3440406BBF996C85B20E7B0C18BE9`
  - `fselling_v4.db`: `D86400A00B11C348E7E060F603E713D7A4C4794A6F0CFE47B725C5A601920AFB`
  - `request_log.txt`: `874C27EA51654113A2D951EDEBAF487E210E5C2FD17C2E5F143C741D2D03DEA8`
- Các hash cuối trùng đúng ba giá trị trên.
- Không commit, không push, không deploy.
