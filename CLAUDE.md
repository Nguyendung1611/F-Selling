# Hướng dẫn cho AI làm việc trên F-Selling

Đọc file này trước khi sửa bất cứ thứ gì. Ngắn thôi, nhưng mỗi dòng đều là một
lần đã trả giá.

## Ba việc bắt buộc

1. **Đọc `KIEN_TRUC.md` mục "Bẫy cần biết khi viết service mới"** trước khi
   động vào `fselling/services/`. Có 24 bẫy, phần lớn không nhìn ra được từ code.
2. **Commit bằng `.\test-commit.ps1 "mô tả"`**, không commit tay. Script chạy
   toàn bộ 711 test rồi mới cho commit, và chặn `.env` / `*.db` lọt lên Git.
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
- **Hàng có `track_batches`: bảng lô là sự thật, `Product.stock` là bản sao.**
  Bán và xuất trừ theo **FEFO** (hạn gần nhất trước), "còn hàng" chỉ tính phần
  chưa hết hạn, giá vốn lấy từ đúng lô đã xuất, hoàn kho về đúng lô đã xuất
  (`order_item_batches`), kiểm kê đếm **theo từng lô** (so snapshot ở mức lô,
  rồi dựng lại `stock` bằng tổng mọi lô). Sản phẩm tắt cờ chạy y như cũ — đừng
  làm hỏng điều đó.
- **Hủy hàng KHÔNG phải xuất kho.** Xuất kho không ghi lý do và không chốt giá
  vốn, nên hàng hết hạn đi đường đó biến mất khỏi báo cáo và lãi bị thổi lên
  đúng bằng phần vốn đã mất. Phiếu hủy chốt `cost_price` từ **đúng lô bị hủy**,
  trừ vào lãi gộp, chỉ chủ shop/ADMIN được bấm, và chống bấm hai lần bằng
  `idempotency_key` — bấm hai lần là trừ kho hai lần.
- **Đơn ghi nợ ở trạng thái `DEBT`, KHÔNG phải `PENDING`.** Để ở `PENDING` thì
  `cancel_expired_pending_orders` xóa sạch sổ nợ và hoàn kho hàng đã giao, còn
  `close_shift` chặn thu ngân kết ca vĩnh viễn. Đơn nợ bắt buộc có khách; tiền
  thu nợ cộng vào `paid_amount`/`cash_paid_amount` sẵn có; `DEBT_CASH` đã nằm
  trong `CASH_PAYMENT_IN_TYPES` nên **đừng** thêm `CashMovement`. Nợ chưa thu
  không tính vào doanh thu. `credit_limit` `NULL` = không giới hạn, `0` = cấm nợ.
- **Trả hàng không phải hủy đơn.** Hủy là đơn chưa thanh toán; trả hàng là đơn
  `PAID`, hàng quay về, và xảy ra được nhiều lần. Đơn **giữ nguyên `PAID`** sau
  khi trả — việc trả nằm ở bảng `order_returns`. Tiền hoàn phải phân bổ giảm giá
  theo tỷ trọng (trả 1 trong 2 món của đơn giảm 10% thì hoàn 45k chứ không 50k).
  Hàng hỏng thì `restock=false`: vẫn hoàn tiền nhưng không lên kệ lại. Hoàn tiền
  mặt bắt buộc có ca OPEN, ghi `RETURN_CASH` vào ledger — **đừng** thêm
  `CashMovement`, sẽ trừ két hai lần.
- **Biến thể (size/màu) là DÒNG `Product`, không phải bảng con.** `variant_group`
  + `variant_name` luôn đi cùng nhau (cùng NULL = hàng đơn lẻ), và `name` do
  **server ghép** thành `"<nhóm> - <biến thể>"`. Form sửa phải điền
  `variant_group` vào ô tên, KHÔNG điền `name` — điền `name` là ghép chồng lên
  nhau. Ô biến thể có ba trạng thái như `barcode`: không gửi = giữ, rỗng = gỡ.
- **Giá vốn `NULL` không phải `0`.** `NULL` = chưa ai khai; `0` = hàng tặng,
  lãi bằng cả giá bán. Gộp lại là mọi sản phẩm cũ bỗng có lãi bằng giá bán và
  chủ shop tin là thật. Giá vốn phải **chốt vào `order_items` lúc bán**, và báo
  cáo lãi **loại nguyên đơn** nào còn dòng thiếu giá vốn — loại nửa vời sẽ đẩy
  lãi lên. Chỉ chủ shop và ADMIN xem được giá vốn/lãi (`has_cost_visibility`);
  `GET /api/products/{shop_id}` nay có xác thực nhưng **nhân viên vẫn đọc
  được**, nên tuyệt đối không trả giá vốn ở đó.

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
- **Sửa file trong `static/` thì phải bump `?v=` ở thẻ `<script>`/`<link>`
  tương ứng trong `static/*.html`.** Quên là người dùng chạy code cũ trong im
  lặng, không lỗi gì cả. Đã bị đúng lỗi này một lần ở bản giá vốn.

**Bảo mật**

- **Sai mật khẩu bị khóa tạm tài khoản, nhưng sai mã OTP thì HỦY MÃ chứ không
  khóa.** Khóa tài khoản theo email là mở đường cho kẻ xấu vô hiệu hóa tài khoản
  người khác chỉ bằng cách gõ bừa. Bộ đếm để trong DB, không để trong RAM
  (restart là kẻ tấn công xóa được bộ đếm). Kiểm khóa **trước** khi kiểm mật
  khẩu, và username không tồn tại vẫn phải tốn đúng chừng ấy thời gian
  (`burn_password_time`).
- **Gửi email phải đi qua `background_tasks`, và `smtplib.SMTP` phải có
  `timeout`.** Gửi thẳng trong request giữ một luồng threadpool suốt 3,5 giây;
  vài chục request là POS đứng máy dù POS không liên quan gì tới email.
- **Các endpoint xin mã không được lộ email nào đã đăng ký.** Cùng mã HTTP, cùng
  y nguyên câu trả lời (`MSG_DA_GUI_MA`) cho mọi ca: email có thật, email lạ, hay
  đang trong thời gian chờ. Cooldown phải **im lặng** — trả 429 cho lần bấm thứ
  hai là tự mở lại kênh rò rỉ.
- **Mọi endpoint có `{shop_id}` phải đi qua `require_shop_access`.**
  `GET /api/products/{shop_id}` từng thiếu: `shop_id` là số nguyên nhỏ, dò từ 1
  lên là đọc trọn danh mục hàng, giá bán và tồn kho của cửa hàng bất kỳ.
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

## Quyết định đã chốt — đừng tự ý làm khác

**Secret trong `DEPLOY_FLY.md` cứ để nguyên.** File đó chứa `SECRET_KEY`,
`PAYMENT_WEBHOOK_SECRET` và `ADMIN_INITIAL_PASSWORD` thật, đã nằm trong lịch sử
Git công khai. Chủ dự án **biết và chấp nhận** vì đang trong giai đoạn phát
triển, chưa có dữ liệu khách hàng thật.

Đừng "tiện tay" đổi mật khẩu, xóa file hay viết lại lịch sử Git — sẽ làm hỏng
môi trường đang chạy mà không ai yêu cầu.

Nhưng **trước khi đưa vào dùng thật với dữ liệu khách hàng** thì phải đổi toàn
bộ ba giá trị trên. Sửa file không xóa được chúng khỏi lịch sử, nên bắt buộc
phải đổi giá trị chứ không phải sửa file.

## Việc đang treo

GitHub Actions **không chạy** (tài khoản bị khóa thanh toán) nên CI không bắt
lỗi giúp. Bộ test chạy ở máy là lưới an toàn duy nhất — càng phải dùng
`test-commit.ps1` cho mọi lần commit.

## Tài liệu

| File | Nội dung |
|---|---|
| `KIEN_TRUC.md` | Kiến trúc + 24 bẫy khi viết service. **Đọc trước khi sửa backend** |
| `QUY_TRINH_LAM_VIEC.md` | Quy trình sửa → test → nhìn thử → commit → push |
| `HUONG_DAN_SU_DUNG.md` | Hướng dẫn cho người dùng cuối |
| `DEPLOY_FLY.md` | Deploy lên Fly.io (xem cảnh báo secret ở trên) |

Thêm bẫy mới thì ghi vào `KIEN_TRUC.md`, đừng để nó chỉ nằm trong commit message.
