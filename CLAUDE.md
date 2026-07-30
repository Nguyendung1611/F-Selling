# Hướng dẫn cho AI làm việc trên F-Selling

Đọc file này trước khi sửa bất cứ thứ gì. Ngắn thôi, nhưng mỗi dòng đều là một
lần đã trả giá.

## Ba việc bắt buộc

1. **Đọc `KIEN_TRUC.md` mục "Bẫy cần biết khi viết service mới"** trước khi
   động vào `fselling/services/`. Có 12 bẫy, phần lớn không nhìn ra được từ code.
2. **Commit bằng `.\test-commit.ps1 "mô tả"`**, không commit tay. Script chạy
   toàn bộ 410 test rồi mới cho commit, và chặn `.env` / `*.db` lọt lên Git.
3. **Sửa giao diện thì phải tự mắt nhìn.** Test không thấy được màu sắc, bố cục
   hay việc một cái nút bấm vào không ra gì. Xem `QUY_TRINH_LAM_VIEC.md`.

## Luật không được phá

Mỗi luật dưới đây đều đã từng bị vi phạm và gây hậu quả thật.

**Tiền**

- Webhook ngân hàng **phải đối chiếu số tiền** với `total_amount` trước khi cho
  `PAID`. Thiếu tiền → `UNRECONCILED`. Tiền RA (`transferType: out`, số tiền âm)
  → từ chối. Payload không có số tiền → từ chối. Đừng gộp "số tiền = 0" với
  "không có số tiền", đó là hai ca khác nhau.
- Giao dịch bị từ chối **vẫn trả HTTP 200**. Trả 4xx/5xx thì ngân hàng retry vô
  hạn. Lý do ghi vào `SystemLog` và khóa `rejected_order_ids`.
- Giá và tổng tiền **luôn tính lại từ database**, không tin số client gửi.

**Đơn hàng & kho**

- Đơn hàng định danh sản phẩm bằng `product_id`. `resolve_items` **luôn lọc kèm
  `shop_id`** — thiếu điều kiện đó thì đoán id là đặt được hàng của shop khác.
- Kiểm kê **chỉ đụng vào sản phẩm có trong phiếu**. Sản phẩm không đếm tới giữ
  nguyên tồn, KHÔNG coi là 0. Và phải so `stock_snapshot` với tồn hiện tại để
  không nuốt mất số hàng vừa bán trong lúc đếm.
- Tồn kho đổi qua `adjust_stock` (cộng trừ theo delta), không ghi đè.

**Database**

- `run_migrations()` **cố ý nuốt mọi lỗi** để chạy lặp lại được. Nên thêm unique
  index thì phải khai vào `_REQUIRED_INDEXES`, nếu không lệnh tạo index thất bại
  sẽ trôi qua im lặng và ràng buộc bị hổng mà không ai biết.
- `log_system_action()` gọi `commit()`, làm **expire** mọi ORM object. Còn trả
  object về client thì phải `db.refresh(obj)` sau đó.
- Migration dọn dữ liệu (như `dedupe_product_codes`) phải chạy **trước**
  `run_migrations()`.

**Route**

- `webhooks.router` phải `include_router` **trước** `orders.router`.
  `POST /api/orders/webhook` trùng khuôn với `POST /api/orders/{shop_id}`.
- Thêm route `/api` mới thì `tests/test_contract.py` sẽ đỏ. Đó là **cố ý** —
  khai route vào `ROUTES_BO_SUNG` kèm chú thích, đừng sửa test cho qua chuyện.

**Frontend**

- **Không dùng `confirm()` / `alert()` của trình duyệt** ở màn POS. Chrome cho
  người dùng tick "chặn hộp thoại của trang này", từ đó `confirm()` trả false
  lặng lẽ và cái nút chết câm. Dùng `xacNhan()` trong `pos.js`.
- Ngày giờ từ server là UTC **không có ký hiệu múi giờ**. Luôn hiển thị qua
  `dinhDangNgayGio()` trong `api.js`, đừng gọi thẳng `new Date(...)` —
  sẽ lệch 7 tiếng và đơn buổi tối bị ghi lùi sang hôm trước.
- Không có build step (không npm/webpack). Thư viện ngoài nạp qua CDN hoặc để
  thẳng file vào `static/js/`.
- **Trình duyệt cache JS rất dai.** Sửa xong mà test không thấy đổi thì gần như
  chắc chắn là cache — hard reload (`Ctrl + Shift + R`) trước khi kết luận.

**Bảo mật**

- Secret chỉ lấy từ biến môi trường. **Không bao giờ** đặt API key trong
  JavaScript — ai mở devtools cũng lấy được.
- Không commit `.env`, `*.db`, `request_log.txt`.

## Cách chạy

```powershell
cd python_app
.\test-commit.ps1 "mô tả thay đổi"                                   # test + commit
.\.venv\Scripts\python.exe -m pytest -x -q -p no:warnings            # test nhanh
.\.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8000
```

**Kiểm cổng trước khi khởi động server thử nghiệm.** Cổng đang bận có thể là
server thật của người dùng — gửi request vào đó là ghi nhầm vào database thật.

Muốn thử nghiệm thì chạy DB riêng, đừng đụng `fselling_v4.db`:

```powershell
$env:DB_PATH="C:\duong\dan\tam\thu.db"
```

## Hai việc đang treo

- `DEPLOY_FLY.md` **đang chứa secret thật** và đã nằm trong lịch sử Git công
  khai. `ADMIN_INITIAL_PASSWORD` trong đó trùng với `.env` đang dùng. Phải **đổi
  mật khẩu**, sửa file không xóa được nó khỏi lịch sử.
- GitHub Actions **không chạy** (tài khoản bị khóa thanh toán), nên CI không bắt
  lỗi giúp. Bộ test ở máy là lưới an toàn duy nhất.

## Tài liệu

| File | Nội dung |
|---|---|
| `KIEN_TRUC.md` | Kiến trúc + 12 bẫy khi viết service. **Đọc trước khi sửa backend** |
| `QUY_TRINH_LAM_VIEC.md` | Quy trình sửa → test → nhìn thử → commit → push |
| `HUONG_DAN_SU_DUNG.md` | Hướng dẫn cho người dùng cuối |
| `DEPLOY_FLY.md` | Deploy lên Fly.io (xem cảnh báo secret ở trên) |

Thêm bẫy mới thì ghi vào `KIEN_TRUC.md`, đừng để nó chỉ nằm trong commit message.
