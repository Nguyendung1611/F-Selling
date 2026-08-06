# Hướng Dẫn Sử Dụng F-Selling

Ứng dụng quản lý bán hàng (POS) cho nhiều cửa hàng: quản lý sản phẩm, danh mục,
khách hàng, khuyến mãi, tích điểm, bán hàng, thống kê doanh thu, và trang quản
trị (admin).

## 1. Yêu cầu

- Cài **Python 3.10 trở lên** (máy đang dùng Python 3.14 là được).
- Kết nối internet (để cài thư viện lần đầu và nếu dùng ngrok).

## 2. Chạy trên máy (local)

Vào thư mục `python_app`, nhấp đúp **`run.bat`**.

Lần đầu script sẽ tự tạo môi trường ảo và cài thư viện (mất vài phút). Khi thấy dòng:

```
Uvicorn running on http://127.0.0.1:8000
```

là server đã chạy. Mở trình duyệt vào: **http://127.0.0.1:8000**

Để **dừng** server: đóng cửa sổ terminal đó (hoặc nhấn `Ctrl + C`).

## 3. Chia sẻ ra internet (miễn phí, qua ngrok)

Nếu muốn người khác truy cập qua một đường link công khai, nhấp đúp **`run_ngrok.bat`**.

Lần đầu cần authtoken ngrok (miễn phí, không cần thẻ):

1. Đăng ký: https://dashboard.ngrok.com/signup
2. Lấy token: https://dashboard.ngrok.com/get-started/your-authtoken
3. Mở terminal chạy 1 lần: `ngrok config add-authtoken <token_của_bạn>`

Sau đó chạy lại `run_ngrok.bat`, cửa sổ ngrok sẽ hiện **LINK CÔNG KHAI** dạng
`https://xxxx.ngrok-free.app` — gửi link này cho người khác để truy cập.

## 3b. Cài F-Selling lên điện thoại như một app

App cài được lên màn hình chính, mở ra **toàn màn hình** (không còn thanh địa
chỉ trình duyệt), và **mở lại được khi mất mạng**.

### Điện thoại Android (Chrome)

1. Mở link `https://...` của bạn (link ngrok ở mục 3, hoặc link server nếu đã deploy).
2. Đợi vài giây, một khung nhỏ **"Cài F-Selling lên máy"** hiện ở góc dưới trái → bấm **Cài**.
3. Không thấy khung đó thì bấm dấu **⋮** góc trên phải → **Thêm vào Màn hình chính**.

### iPhone / iPad (Safari)

Safari không hiện nút tự động, phải làm tay:

1. Mở link bằng **Safari** (Chrome trên iPhone không cài được).
2. Bấm nút **Chia sẻ** (hình vuông có mũi tên đi lên, ở thanh dưới).
3. Kéo xuống chọn **Thêm vào MH chính** → **Thêm**.

### Máy tính (Chrome / Edge)

Bấm biểu tượng **cài đặt** hình màn hình có mũi tên, nằm ở cuối thanh địa chỉ.

---

⚠️ **Bắt buộc phải là link `https://`.** Mở bằng `http://192.168.x.x` (địa chỉ
mạng nội bộ) thì trình duyệt **không cho cài** — đây là quy định bảo mật của
trình duyệt, không phải lỗi app. Dùng link ngrok ở mục 3 là có `https` sẵn.

*(Riêng `http://127.0.0.1:8000` ngay trên máy chạy server thì vẫn cài được.)*

### Mất mạng thì dùng được tới đâu?

| Việc | Khi mất mạng |
|---|---|
| Mở app, xem giao diện | ✅ được |
| Xem danh mục sản phẩm đã tải gần nhất | ✅ được |
| Bán và thu **tiền mặt** | ✅ được, phiếu sẽ chờ đồng bộ |
| Chuyển khoản, ghi nợ, Voucher, khách hàng, tích/đổi điểm | ❌ không dùng offline |

Đơn offline chỉ dùng giá đã chụp trên máy lúc còn mạng và chỉ nhận tiền mặt.
Khi có mạng lại, app tự gửi các phiếu đang chờ lên server. Không dùng điểm khi
offline vì máy không thể kiểm tra số dư mới nhất; đoán sai ở đây là lệch tiền.

### Nếu app hiện bản cũ sau khi cập nhật

Mở app → F12 (trên máy tính) → gõ vào Console:

```
FSellingPWA.xoaCache()
```

Rồi tải lại trang bằng `Ctrl + Shift + R`.

## 4. Đăng nhập Admin

- Tên đăng nhập: `admin`
- Mật khẩu: xem dòng `ADMIN_INITIAL_PASSWORD` trong file `.env`. Mật khẩu thật
  không được ghi trong tài liệu hoặc đưa lên Git.

### Đổi mật khẩu admin

Cách 1 (khuyến nghị cho lúc setup): mở `.env`, sửa `ADMIN_INITIAL_PASSWORD=<mật khẩu mới>`
rồi khởi động lại server. App tự cập nhật, **không cần chạy script gì thêm**.

Cách 2: sau khi đã chốt mật khẩu, **xóa dòng `ADMIN_INITIAL_PASSWORD` khỏi `.env`**.
Từ đó app không tự đổi nữa, bạn quản lý mật khẩu bằng chức năng "Đổi mật khẩu" trong app.

> Lưu ý: khi còn dòng `ADMIN_INITIAL_PASSWORD` trong `.env`, nếu bạn đổi mật khẩu
> trong app thì lần khởi động sau sẽ bị ghi đè về giá trị trong `.env`.

## 5. Người bán (Seller)

- Vào trang chủ → **Đăng ký Người bán** để tạo tài khoản (cần xác minh email nếu có cấu hình SMTP).
- Đăng nhập → tạo **Cửa hàng** (tối đa 3), thêm **Danh mục**, **Sản phẩm**, **Khuyến mãi**.
- Mở **POS** để bán hàng: chọn sản phẩm, áp voucher, thanh toán (chuyển khoản QR hoặc tiền mặt).
- Xem **Dashboard**: doanh thu, số đơn, sản phẩm bán chạy, biểu đồ.

### Tự cài chương trình tích điểm

Chỉ **chủ cửa hàng** sửa được luật điểm; nhân viên ở POS chỉ dùng luật đã lưu.

1. Đăng nhập tài khoản chủ shop → bấm tab **Tích Điểm**.
2. Nếu có nhiều cửa hàng, chọn cửa hàng ở ô **Cửa hàng** trên đầu trang.
3. Nhập lần lượt:
   - khách chi bao nhiêu tiền thì được bao nhiêu điểm;
   - dùng bao nhiêu điểm thì giảm bao nhiêu tiền;
   - số điểm tối thiểu cho một lần dùng;
   - tối đa được giảm bao nhiêu phần trăm hóa đơn;
   - số ngày hết hạn (để trống nếu điểm không hết hạn).
   Các ô này chỉ nhận số nguyên, không nhập số lẻ.
4. Nhìn ô xem trước ở cuối form. Đúng ý thì đánh dấu **Bật chương trình** → bấm
   **Lưu chương trình tích điểm**. Bạn sẽ thấy dòng trạng thái màu xanh báo POS
   đã có thể cộng và dùng điểm.

Ở POS: chọn khách hàng trước. Khi chương trình đang bật, ngay dưới tên khách sẽ
hiện khung **Điểm khách thân thiết** và số dư hiện tại. Nhập số điểm → bấm
**Áp dụng điểm**; dòng **Giảm bằng điểm** và **Tổng cần thu** sẽ đổi ngay. Nếu có
Voucher thì hệ thống trừ Voucher trước, rồi mới tính điểm và giới hạn phần trăm.

Điểm mới chỉ được cộng sau khi đơn đã báo **Đã thanh toán**. Đơn ghi nợ phải thu
đủ mới cộng. Tắt chương trình thì số dư cũ vẫn giữ nguyên nhưng POS tạm ngừng cả
cộng lẫn dùng điểm. Bán offline không cộng và không dùng điểm. Nếu đã áp điểm
rồi mới mất mạng, bấm **Bỏ dùng điểm và tiếp tục bán offline** → nhìn lại tổng
tiền vừa tăng → xác nhận; app không tự ý đổi số tiền phải thu.

Khách đã có lịch sử điểm sẽ không bị xóa mất sổ. Ở tab **Khách Hàng**, bấm nút
xóa sẽ chuyển khách thành **Ngừng sử dụng**; khách biến khỏi danh sách chọn ở
POS nhưng vẫn còn trong danh sách quản lý. Muốn dùng lại, bấm nút mũi tên xanh.
Shop đã có chương trình hoặc lịch sử điểm cũng không xóa hẳn được: vào phần cửa
hàng và bấm **Khóa** để ngừng sử dụng mà vẫn giữ nguyên sổ đối soát.

### Hàng có nhiều size / màu (biến thể)

Trong **Kho hàng**, ô **Tên biến thể** ngay dưới ô tên sản phẩm là chỗ khai
size/màu. Khai ô đó thì ô tên ở trên được hiểu là **tên nhóm**:

| Tên sản phẩm | Tên biến thể | Kết quả |
|---|---|---|
| Áo thun cổ tròn | Đỏ / L | Áo thun cổ tròn - Đỏ / L |
| Áo thun cổ tròn | Xanh / M | Áo thun cổ tròn - Xanh / M |
| Nước suối 500ml | *(để trống)* | Nước suối 500ml |

Mỗi biến thể là một mặt hàng riêng: **tồn kho, giá bán, giá vốn, mã vạch và hạn
sử dụng đều tính riêng**. Khai xong biến thể đầu tiên thì bấm nút **copy** ở
dòng đó trong bảng để thêm size tiếp theo — tên nhóm, giá và danh mục được điền
sẵn, chỉ cần gõ tên biến thể mới.

Ở màn **POS**, các biến thể cùng nhóm gom lại thành **một ô**; bấm vào ô đó rồi
chọn đúng size/màu. Ô nhóm hiện tổng tồn của cả nhóm và khoảng giá (ví dụ
"150.000 ₫ – 165.000 ₫" khi các size khác giá). Size hết hàng vẫn hiện trong
danh sách nhưng bấm không được.

> Muốn bỏ biến thể để món hàng thành hàng đơn lẻ: sửa sản phẩm, **xóa trắng ô
> Tên biến thể** rồi lưu. Tồn kho và lịch sử bán không bị ảnh hưởng.

> Báo cáo và Excel hiện đếm theo **từng biến thể**, chưa cộng gộp theo nhóm.

### Kiểm kê hàng có hạn sử dụng

Sản phẩm bật "Theo dõi hạn sử dụng theo lô" thì phải đếm **theo từng hạn**. Quét
mã của nó ở tab Kiểm Kê, phiếu sẽ hiện ra một dòng cho mỗi hạn còn hàng — điền
số đếm được vào đúng dòng có hạn tương ứng.

> Đếm ra hàng thuộc một hạn **chưa có trong phiếu** thì đó là hàng nhập bị sót,
> không phải việc của kiểm kê. Vào Kho hàng → Nhập kho và khai đúng hạn đó.

### Hủy hàng hết hạn

Kho hàng → tab **Hạn sử dụng** → nút **Hủy hàng hết hạn** (chỉ chủ cửa hàng
thấy). Hệ thống liệt kê sẵn các lô đã quá hạn kèm số tiền vốn sẽ mất; xem lại
rồi mới xác nhận.

Số hàng hủy bị trừ khỏi kho và ghi thành **lỗ** trong báo cáo — dòng "Trừ ... hàng
hủy" dưới ô Lãi gộp ở Dashboard. Đây là điểm khác quan trọng so với việc dùng
Xuất kho: xuất kho làm tồn giảm mà lãi vẫn báo như cũ, tức là cao hơn thực tế.

> Thao tác này **không hoàn tác được**, và lô nào chưa khai giá vốn thì phần lỗ
> của nó không tính được — hệ thống sẽ nói rõ thay vì coi như bằng 0.

## 6. File cấu hình `.env`

| Biến | Ý nghĩa |
|---|---|
| `SECRET_KEY` | Khóa ký JWT. Bắt buộc, giữ bí mật. |
| `ADMIN_INITIAL_PASSWORD` | Mật khẩu admin (app tự đồng bộ khi khởi động). |
| `PAYMENT_WEBHOOK_SECRET` | Secret cho webhook thanh toán (thiếu thì webhook trả 503). |
| `ALLOWED_ORIGINS` | Domain được phép gọi API (CORS). |
| `SMTP_HOST/PORT/USER/PASSWORD` | Cấu hình gửi email OTP (tùy chọn). |
| `LOGIN_MAX_ATTEMPTS` | Sai mật khẩu bao nhiêu lần thì khóa tạm (mặc định 5). |
| `LOGIN_LOCKOUT_MINUTES` | Khóa tạm bao nhiêu phút (mặc định 15). |
| `OTP_MAX_ATTEMPTS` | Nhập sai mã bao nhiêu lần thì hủy mã (mặc định 5). |
| `OTP_RESEND_COOLDOWN_SECONDS` | Cách nhau bao lâu mới được xin mã mới (mặc định 60). |
| `SMTP_TIMEOUT_SECONDS` | Chờ máy chủ mail tối đa bao lâu (mặc định 10). |

> **Vì sao "quên mật khẩu" luôn báo đã gửi mã?** Kể cả khi email chưa từng đăng
> ký, hệ thống vẫn trả lời y hệt. Nếu báo "không tìm thấy tài khoản" thì bất kỳ
> ai cũng dò được email nào có tài khoản F-Selling để nhắm lừa đảo. Không nhận
> được mã thì kiểm tra lại địa chỉ email và xem cả hộp thư rác.

> **Lỡ tự khóa tài khoản admin?** Đặt lại `ADMIN_INITIAL_PASSWORD` trong `.env`
> rồi khởi động lại server — khóa được gỡ ngay, không phải ngồi chờ hết giờ.

## 7. Deploy lên server (tùy chọn)

Nếu muốn chạy 24/7 trên máy chủ (không cần bật máy tính), xem file **`DEPLOY_FLY.md`**
(hướng dẫn deploy miễn phí lên Fly.io kèm lưu trữ dữ liệu bền).

## 8. Cấu trúc mã nguồn

Backend đã được tách thành package `fselling/` (routers / services / models / schemas).
Cách chạy **không đổi** (`run.bat`, `uvicorn app:app`, Docker, Fly.io).
Chi tiết kiến trúc và cách chạy test: xem **`KIEN_TRUC.md`**.

## 9. Lưu ý bảo mật quan trọng

- **Thu hồi Gmail App Password cũ** trong `.env` (đã từng bị lộ) và tạo cái mới.
- **Không** commit lên git / **không** gửi cho ai file `.env` và các file `.db`
  (chúng chứa mật khẩu và dữ liệu thật).
- Chi tiết các lỗi bảo mật đã được sửa: xem file **`CAC_LOI_BAO_MAT_DA_FIX.md`**.
