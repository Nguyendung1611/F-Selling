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

### 3. Form field rỗng bị FastAPI quy về giá trị mặc định

`Optional[str] = Form(None)` trả về `None` cho **cả hai** trường hợp "form không
gửi field" và "form gửi field rỗng". Đặt default khác `None` cũng không cứu
được: field rỗng vẫn rơi về đúng default đó.

Khi cần phân biệt (ví dụ `barcode`: không gửi = giữ nguyên, gửi rỗng = xóa),
phải đọc lại form thô — xem `routers/products.py::barcode_field`. Dependency đó
là `async` nhưng endpoint vẫn để `def` đồng bộ: FastAPI giải dependency trên
event loop rồi chạy endpoint trong threadpool, nên phần gọi database đồng bộ
không chặn event loop.

### 4. `run_migrations()` nuốt lỗi, nên index bắt buộc phải được kiểm lại

Hàm này bọc mọi câu lệnh trong `except SQLAlchemyError` để chạy lặp lại được.
Hệ quả: một `CREATE UNIQUE INDEX` thất bại (DB đang có sẵn dữ liệu trùng) sẽ
**trôi qua im lặng**, app vẫn khởi động, và ràng buộc trùng lặp bị hổng mà
không ai biết. Thêm index bắt buộc thì phải khai vào `_REQUIRED_INDEXES` để
`verify_required_indexes()` kiểm lại và in cảnh báo.

### 5. Mã sản phẩm tự sinh phải lấy từ `id`, không lấy từ đồng hồ

Bản đầu sinh mã bằng `SP-<timestamp giây>`, nên mọi sản phẩm tạo trong cùng một
giây đều trùng mã. Nay `create_product` gọi `db.flush()` để lấy `id` rồi đặt
`SP-<id>` — duy nhất tuyệt đối, không phụ thuộc tốc độ tạo.

`code`, `barcode` và `name` đều duy nhất trong phạm vi một shop
(`ix_products_shop_code`, `ix_products_shop_barcode`, `ix_products_shop_name`)
và đều được kiểm ở service để báo tên sản phẩm đang giữ mã.
`dedupe_product_codes()` dọn dữ liệu cũ và **phải chạy trước
`run_migrations()`**, nếu không lệnh tạo unique index sẽ thất bại trên DB còn mã
trùng. Riêng `name` cố ý KHÔNG có bước dồn tự động: tên là dữ liệu người dùng
đặt, tự đổi thành "... (2)" là quyết định không nên thay họ - DB nào còn tên
trùng thì `verify_required_indexes()` sẽ nêu index bị thiếu để tự sửa.

### 6. Kiểm trùng ở service không thay được ràng buộc ở DB

Giữa lúc service kiểm trùng và lúc ghi vẫn có khe cho hai request cùng lọt.
Unique index chặn được nhưng ném `IntegrityError` → 500. `_ghi_bat_trung()`
trong `catalog_service` bọc **cả `flush()` lẫn `commit()`** (create flush để lấy
id nên INSERT chạy ở đó; update không flush nên UPDATE chạy lúc commit) và chỉ
dịch những ràng buộc có tên trong `_RANG_BUOC_DUY_NHAT` thành 400. Mọi
`IntegrityError` khác vẫn ném tiếp - lỗi lập trình phải lộ ra, không được giấu.

Cách nhận biết dựa vào chuỗi thông báo của SQLite; đổi database khác là phải
sửa lại bảng khóa đó.

### 7. Quét bằng camera: hai cái bẫy đã mất công tìm ra

**Không tự gọi `video.play()` rồi mới đưa cho ZXing.** Hàm
`decodeFromVideoElementContinuously` chờ sự kiện `canplay`; nếu video đã chạy
thì sự kiện đó bắn xong rồi và nó chờ mãi - camera hiện hình bình thường nhưng
không bao giờ quét ra gì. Dùng `decodeFromStream(stream, video, callback)` để
ZXing tự gắn stream và tự phát.

**Chống quét lặp phải dựa vào "mã rời khỏi khung", không dựa vào thời gian.**
Camera đọc lại cùng một mã ở mọi khung hình. Nếu chỉ chờ hết một khoảng rồi
nhận lại thì để yên máy vài giây là món hàng bị cộng thêm mấy lần - tính thừa
tiền mà không ai để ý. Xem `NGUONG_ROI_KHUNG_MS` trong `barcode-camera.js`.

### 8. Webhook thanh toán: phải đối chiếu SỐ TIỀN, không chỉ mã đơn

`apply_webhook_payment` không được chỉ rút `ORDERxxx` rồi đánh dấu `PAID`.
Luật hiện tại:

| Tình huống | Kết quả |
|---|---|
| Tiền RA (`transferType: out`, hoặc số tiền âm) | Từ chối, giữ nguyên trạng thái |
| Payload không có số tiền | Từ chối, giữ `PENDING` |
| Tổng nhận < tổng đơn | `UNRECONCILED/UNDERPAID`, tiếp tục chờ chuyển thêm hoặc bù tiền mặt |
| Tổng nhận = tổng đơn | Tự động `PAID`, frontend xuất hóa đơn |
| Tổng nhận > tổng đơn | `PAID/OVERPAID`, xuất hóa đơn ngay và mở khoản chờ hoàn |
| Tiền về sau khi đơn đã hủy | `UNRECONCILED/LATE_PAYMENT`, không hồi sinh đơn; chờ hoàn |
| Sai số tài khoản nhận | Chỉ cảnh báo, KHÔNG chặn |

Ba điều dễ làm sai khi sửa tiếp:

**Phải phân biệt "số tiền = 0" với "không có số tiền".** `GiaoDich.amount is None`
nghĩa là payload không chứa số tiền nên không có cơ sở xác nhận; `amount == 0`
là một số tiền thật và sai. Gộp hai ca này lại là mở lại đúng lỗ hổng cũ.

**Giao dịch bị từ chối vẫn trả HTTP 200.** Ngân hàng retry vô hạn khi nhận
4xx/5xx. Lý do từ chối nằm ở `SystemLog` và khóa `rejected_order_ids`.

**Đừng đặt unique index lên `bank_txn_id`.** Ngân hàng gửi lại cùng một giao
dịch là bình thường. Khi hỗ trợ khách chuyển nhiều lần, máy trạng thái KHÔNG
còn đủ để chống lặp: mọi khoản tiền vào/tiền mặt/hoàn tiền nằm trong ledger
`order_payments`, và webhook dùng unique `idempotency_key` riêng. Cả ledger,
tổng lũy kế, trạng thái và `SystemLog` phải commit trong cùng một transaction;
không gọi `transition_status()` hay `log_system_action()` ở giữa vì hai hàm đó
tự commit. `bank_txn_id` vẫn non-unique và chỉ dùng để tra cứu.

### 9. Đọc tiền: phải đổi số sang CHỮ trước khi đọc

`DocTien.docSo()` đổi `150000` thành `"một trăm năm mươi nghìn"`. Đừng đưa thẳng
chuỗi đã định dạng `"150.000"` cho bộ đọc: nhiều engine đọc dấu chấm ngăn cách
nghìn thành `"một trăm năm mươi chấm không không không"`, hoặc đọc rời từng số.

Hai chỗ dễ viết sai trong hàm đổi số:

- Nhóm không phải cao nhất **phải** đọc cả `"không trăm"`. Thiếu nó thì
  `1.005.000` thành `"một triệu năm nghìn"` — sai hẳn con số.
- Tiếng Việt đổi vần theo hàng chục: `mười lăm` (không phải "mười năm"),
  `hai mươi mốt`, `hai mươi tư`, `hai mươi lăm`.

Chỉ đọc ở nhánh polling của chuyển khoản — đó là ca thu ngân không nhìn màn
hình. Tiền mặt thì người bán vừa cầm tiền nên đọc thành ồn.

**Hai tầng phát tiếng.** `DocTien.noi()` ưu tiên giọng tiếng Việt cài sẵn trên
thiết bị (nhanh, miễn phí, không cần mạng — điện thoại thường có). Máy không có
giọng Việt thì gọi `POST /api/tts` để server sinh. Chrome trên Windows luôn rơi
vào tầng hai: bộ giọng "Google …" kèm theo Chrome **không có tiếng Việt**, phải
cài gói của Windows mới có.

Trang web KHÔNG thể tự cài giọng cho máy người dùng — `SpeechSynthesis` chỉ
liệt kê giọng mà hệ điều hành đã có. Đó là lý do phải có tầng server.

Cấu hình server (để trống = tắt, frontend tự lùi về giọng thiết bị):

```
TTS_PROVIDER=google|azure
TTS_API_KEY=...
TTS_AZURE_REGION=southeastasia      # chỉ Azure mới cần
TTS_VOICE=                          # để trống = giọng mặc định của nhà cung cấp
```

Ba điều bắt buộc ở endpoint này: **key chỉ nằm ở backend** (đặt trong frontend
là ai mở F12 cũng xài chùa hết hạn mức), **phải đăng nhập mới gọi được** (để mở
thì thành dịch vụ đọc chữ miễn phí cho cả internet), và **cache theo nội dung
câu** vì cửa hàng bán quanh vài mức giá quen nên cùng một câu lặp rất nhiều.

### 10. Kiểm kê: ba nguyên tắc không được phá

`apply_stocktake()` đặt tồn kho bằng số đếm thực tế. Ba điều bắt buộc giữ:

1. **Chỉ đụng vào sản phẩm có trong phiếu.** Sản phẩm không đếm tới giữ nguyên
   tồn, KHÔNG coi là 0 - quên quét một kệ mà bị xóa sạch tồn thì tai hại hơn
   nhiều so với kiểm kê thiếu.
2. **Dòng nào tồn kho đã đổi so với lúc bắt đầu đếm thì bỏ qua và báo lại.**
   Bán hàng vẫn chạy song song khi đang kiểm kê; ghi đè lúc đó sẽ hồi sinh số
   hàng vừa bán. Máy khách gửi kèm `stock_snapshot` để server so.
3. **Không nhận số đếm âm.**

Máy quét USB bắt phím ở tầm `document` nên `xuLyQuetSeller()` phải tự phân
biệt: tab Kiểm Kê đang mở thì mã vào phiếu đếm, ngược lại mới đi đường
nhập/xuất kho.

### 11. Đơn hàng định danh sản phẩm bằng `product_id`

`OrderItemCreate` nhận cả `product_id` và `product_name`; `product_id` được ưu
tiên, `product_name` chỉ dùng khi thiếu id (client cũ). `resolve_items` **luôn**
lọc kèm `shop_id` kể cả khi tra theo id - thiếu điều kiện đó thì đoán id là đặt
được hàng của shop khác. Giỏ hàng ở POS cũng gộp dòng theo `product_id`, không
theo tên.

### 12. Không dùng `.subquery()` cho `in_()` trong SQLAlchemy 2.0

Truyền thẳng `Query` vào `in_()` (SQLAlchemy tự coerce thành scalar subquery);
gọi `.subquery()` sẽ sinh `SAWarning` về coercion.

### 13. Giá vốn: `NULL` không bao giờ được đối xử như `0`

`products.cost_price` và `order_items.cost_price` đều nullable, và hai giá trị
này là hai chuyện khác hẳn nhau:

| Giá trị | Nghĩa |
|---|---|
| `NULL` | Chưa ai khai giá vốn. Không có cơ sở tính lãi. |
| `0` | Hàng được tặng. Lãi bằng đúng giá bán. |

Gộp lại thì mọi sản phẩm cũ bỗng có lãi bằng giá bán, và chủ shop nhìn con số
đó tin là thật. Đây đúng là bài học của webhook thanh toán ở mục 8, lặp lại ở
một chỗ khác. Vì vậy cũng KHÔNG có bước backfill: đơn bán trước migration F1
không có cách nào biết giá vốn, báo cáo phải đếm riêng và nói ra.

**Ba điều dễ làm sai khi sửa tiếp:**

**Giá vốn phải được CHỐT vào `order_items` lúc bán**, giống cách `product_name`
chụp lại tên. Tra ngược `Product.cost_price` lúc làm báo cáo thì mỗi lần nhập
một lô giá khác là lãi của các tháng trước tự đổi số - và không lấy lại được
số cũ nữa.

**Báo cáo lãi loại NGUYÊN ĐƠN khi đơn còn dòng thiếu giá vốn.** Giảm giá
voucher nằm ở mức đơn hàng nên không tách được phần doanh thu ứng với riêng
các dòng đã biết giá vốn. Loại nửa vời - trừ giá vốn đã biết ra khỏi toàn bộ
doanh thu - **đẩy lãi lên** đúng bằng phần chưa khai, tức là sai theo hướng
làm người xem yên tâm. `_lai_gop()` trả về `orders_missing_cost` và
`revenue_missing_cost` để giao diện nói ra phần bị loại.

**Chỉ chủ shop và ADMIN được xem giá vốn và lãi** (`has_cost_visibility`).
MANAGER có `PERMISSION_REPORT` nên vẫn xem doanh thu, nhưng biết lãi là suy ra
được giá vốn. Khi không có quyền thì `shop_stats` **bỏ hẳn** nhóm field đó khỏi
phản hồi chứ không trả 0 - lãi bằng 0 là một con số có nghĩa (bán đúng bằng giá
vốn), trả 0 là nói dối chứ không phải giấu.

Hệ quả về route: `GET /api/products/{shop_id}` **không yêu cầu đăng nhập** (POS
đang dựa vào), nên tuyệt đối không nhét `cost_price` vào đó. Giá vốn đi qua
`GET /api/products/{shop_id}/costs` riêng, có xác thực.

### 14. Bình quân gia quyền tính ngay trong câu UPDATE, và phụ thuộc SQLite

`adjust_stock` nhận thêm `unit_cost` - đơn giá của **lô đang nhập**, không phải
giá vốn mới. Công thức nằm trong `_ADJUST_STOCK`, cùng một câu UPDATE nguyên tử
với `stock = stock + delta`: tách ra đọc-rồi-ghi là mở lại đúng khe hở mà câu
lệnh đó sinh ra để bịt.

```
cost_mới = (tồn_cũ × cost_cũ + SL_nhập × đơn_giá) / (tồn_cũ + SL_nhập)
```

**SQLite đánh giá mọi vế phải của `SET` theo giá trị CŨ của hàng**, nên `stock`
trong biểu thức tính giá vốn vẫn là tồn trước khi nhập, bất kể thứ tự các mệnh
đề `SET`. MySQL thì ngược lại (đánh giá lần lượt, vế sau thấy giá trị đã cập
nhật) - đổi database là phải viết lại câu này. Cùng loại ràng buộc với mục 6.

Bốn ca biên, đều có test trong `tests/test_gia_von.py`:

| Tình huống | Xử lý |
|---|---|
| Không gửi `unit_cost` | Giữ nguyên giá vốn, chỉ cộng tồn |
| `unit_cost = 0` | Đơn giá thật của hàng tặng, kéo bình quân xuống |
| Tồn cũ ≤ 0, hoặc `cost_price` NULL | Lấy luôn đơn giá (không có gì để bình quân) |
| Xuất kho (`delta < 0`) kèm `unit_cost` | **Từ chối 400**, không im lặng bỏ qua |

Ô đơn giá đi qua **JSON body** (`StockAdjust`) chứ không phải form, nên `None`
và `0` là hai giá trị khác nhau thật sự - không dính bẫy #3. Ngược lại ô giá vốn
trên form sửa sản phẩm thì dính, và được xử lý theo đúng mẫu của `barcode_field`
(`cost_price_field` trong `routers/products.py`).

**Kiểm kê và hủy đơn đều KHÔNG đụng vào giá vốn.** Kiểm kê chỉ đặt lại số
lượng. Hủy đơn hoàn tồn kho đúng số lượng đã trừ, mà số đó ra đi với đúng giá
vốn đã chốt, nên bình quân tự khớp lại - chạy lại công thức lúc hoàn mới là cái
làm lệch.

### 15. Trả hàng khác hẳn hủy đơn và khác hẳn hoàn khoản chuyển thừa

Ba nghiệp vụ rất dễ nhầm, và đã có sẵn hai cái trước khi có cái thứ ba:

| Nghiệp vụ | Đơn ở trạng thái | Hàng | Số lần |
|---|---|---|---|
| `cancel_order` | Chưa thanh toán (`PENDING`) | Chưa ra khỏi cửa | 1 |
| `complete_refund` | Đã thanh toán, khách chuyển THỪA | Vẫn của khách | 1 |
| `return_service.create_return` | Đã thanh toán (`PAID`) | Quay về shop | **Nhiều** |

**Đơn giữ nguyên `PAID` sau khi trả hàng.** Hóa đơn đã xuất là sự thật lịch sử;
việc khách trả lại là sự kiện xảy ra sau đó, nằm ở bảng `order_returns` chứ
không xóa đi lần bán. Nhờ vậy máy trạng thái ở mục 8 không phải mở lại, và mọi
chỗ đang lọc `status == PAID` (doanh thu, đối soát, Excel) không phải rà lại.

**Cụm `refund_*` trên `orders` KHÔNG dùng cho trả hàng.** Cụm đó là chu kỳ hoàn
khoản chuyển thừa, chỉ chạy một lần và `refund_due_amount` là số vô hướng. Trả
hàng có bảng riêng vì xảy ra nhiều lần.

**Bốn điều bắt buộc giữ khi sửa tiếp:**

**Tiền hoàn phải phân bổ giảm giá theo tỷ trọng.** Đơn 100k giảm 10% còn 90k,
khách trả 1 trong 2 món giá niêm yết 50k thì hoàn **45k**, không phải 50k. Hoàn
theo giá niêm yết là shop chịu trọn phần đã giảm cho món khách vẫn giữ. Riêng
ca trả HẾT được xử lý riêng để tổng khớp tuyệt đối - cộng dồn từng dòng đã làm
tròn có thể lệch vài đồng, mà trả hết thì khách phải nhận đúng số đã trả.

**`restocked` là quyết định của TỪNG DÒNG.** Áo khách mặc bẩn, sữa hết hạn, hộp
móp: vẫn hoàn tiền nhưng không được cộng lại vào tồn bán được, nếu không POS sẽ
bán tiếp món đó cho người khác. Trong báo cáo, dòng không nhập lại kho làm lãi
giảm bằng **toàn bộ** tiền hoàn (mất trắng cả vốn), dòng có nhập lại chỉ giảm
phần chênh giữa tiền hoàn và giá vốn thu hồi.

**Nhập lại kho KHÔNG chạy lại công thức bình quân.** Số hàng đó ra đi với đúng
giá vốn đã chốt trên dòng đơn nên khi quay về, đơn giá bình quân tự khớp lại -
giống hệt lý do ở hủy đơn (mục 13).

**Hoàn tiền mặt bắt buộc có ca OPEN, kể cả chủ shop.** Ledger ghi
`entry_type = RETURN_CASH` kèm `shift_id`, và `RETURN_CASH` đã được khai vào
`CASH_PAYMENT_OUT_TYPES` của `shift_service` nên `_expected_cash` tự trừ. **Đừng
thêm `CashMovement` cho khoản này** - sẽ trừ hai lần.

Điểm phụ thuộc một chiều: `return_service` import `order_service`, không bao giờ
ngược lại. Chi tiết đơn kèm lịch sử trả được **router ghép hai service** nối
tiếp (`orders.py::get_order_detail`) để không sinh vòng import.

### 16. Sửa file trong `static/` thì phải bump dấu `?v=`

Mọi `<script>` và `<link>` trong `static/*.html` đều mang query `?v=<ngày>-<mô tả>`.
Sửa file mà quên đổi dấu đó thì trình duyệt của người dùng **chạy code cũ trong
im lặng** - không lỗi, không cảnh báo, tính năng mới coi như không tồn tại với
những người đã từng mở trang. Bản giá vốn (F1) đã bị đúng lỗi này một lần.

`tests/test_contract.py::test_moi_file_js_css_deu_co_dau_phien_ban` chỉ bắt được
ca thêm file mới mà quên `?v=`; việc BUMP khi sửa file thì không máy nào kiểm hộ
được, phải tự nhớ.

### 17. Chống dò mật khẩu và dò mã OTP: hai hình phạt khác nhau, có lý do

Trước bản F3, cả ba đường dưới đây đều cho đoán **không giới hạn**:
`login`, `verify-email`, `forgot-password-reset`. Đường thứ ba nặng nhất — mã
chỉ 6 chữ số (một triệu khả năng) mà phần thưởng là **đặt được mật khẩu mới cho
tài khoản người khác**.

Hai đường bị phạt theo hai kiểu khác nhau, và **không được đổi chỗ cho nhau**:

| Đường | Sai quá ngưỡng | Vì sao |
|---|---|---|
| Sai mật khẩu | **Khóa tài khoản** `LOGIN_LOCKOUT_MINUTES` phút | Kẻ tấn công phải biết username; khóa tạm là giá phải trả hợp lý |
| Sai mã OTP | **Hủy mã**, KHÔNG khóa tài khoản | Chỉ cần biết email là gõ bừa được. Khóa tài khoản ở đây = ai biết email của bạn cũng vô hiệu hóa được tài khoản bạn |

Hủy mã thì kẻ tấn công chỉ tự làm mất công của chính họ; chủ tài khoản bấm "gửi
lại mã" là dùng tiếp.

**Bốn điều bắt buộc giữ:**

**Bộ đếm nằm trong DB, không nằm trong bộ nhớ tiến trình.** Để trong RAM thì
restart là kẻ tấn công được xóa bộ đếm — mà restart họ ép được (chỉ cần làm app
lỗi). DB cũng là nơi duy nhất còn đúng khi chạy nhiều worker hoặc nhiều máy.

**Kiểm khóa TRƯỚC khi kiểm mật khẩu.** Kiểm mật khẩu rồi mới chặn thì mỗi
request bị khóa vẫn tốn một lần bcrypt, và cửa khóa thành ra đường làm nghẽn
server.

**Username không tồn tại vẫn phải tốn đúng chừng ấy thời gian**
(`security.burn_password_time()`). Trả lời tức thì là nói cho kẻ dò biết
username nào KHÔNG có, và loại trừ dần cũng chính là dò ra username nào CÓ.
Thông báo lỗi của hai ca cũng phải giống hệt nhau.

**Cấp mã mới thì phải reset bộ đếm sai** (`_cap_ma_moi`). Mã mới là bí mật mới;
số lần đoán hụt mã cũ không nói gì về nó. Quên reset thì người dùng thật xin mã
mới xong vẫn bị chặn ngay lần nhập đầu.

Đường cứu khi admin tự khóa mình: đặt lại `ADMIN_INITIAL_PASSWORD` rồi khởi động
lại — `seed_admin()` gỡ khóa. Chỉ người có quyền trên máy chủ mới làm được.

Cooldown xin mã (`OTP_RESEND_COOLDOWN_SECONDS`) **dùng chung cho cả
`resend-code` lẫn `forgot-password-request`**: hai endpoint gửi mail tới cùng
một hộp thư, tách riêng thì luân phiên hai đường là gửi được gấp đôi.

Bốn giá trị đều chỉnh được qua biến môi trường: `LOGIN_MAX_ATTEMPTS`,
`LOGIN_LOCKOUT_MINUTES`, `OTP_MAX_ATTEMPTS`, `OTP_RESEND_COOLDOWN_SECONDS`.

### 18. Gửi email PHẢI nằm ngoài thời gian trả lời request

`send_otp_email` nói chuyện với máy chủ mail qua mạng — đo thực tế với Gmail là
**3,5 giây**. FastAPI chạy endpoint đồng bộ trong threadpool (~40 luồng), nên
mỗi lần gửi giữ một luồng suốt chừng ấy. Vài chục request `quên mật khẩu` là hết
luồng, và lúc đó **POS cũng không bán được hàng** dù POS chẳng liên quan gì tới
email. Không cần kẻ xấu: một hôm Gmail chậm là đủ.

Ba lớp bảo vệ, phải giữ đủ cả ba:

1. **`background_tasks.add_task(...)`** (`auth_service._gui_mail_nen`) — request
   trả lời xong rồi mới gửi mail. Router phải nhận `BackgroundTasks` và truyền
   xuống service.
2. **`timeout=SMTP_TIMEOUT_SECONDS`** khi mở `smtplib.SMTP`. Không có nó thì
   smtplib chờ **vô hạn** lúc máy chủ mail không phản hồi.
3. **`server.quit()` bọc trong `finally` + `close()` dự phòng** — `quit()` cũng
   đi qua mạng nên cũng hỏng được, mà socket thì kiểu gì cũng phải đóng.

### 19. Bốn endpoint xin mã KHÔNG được lộ email nào đã đăng ký

`forgot-password-request` gọi được mà không cần đăng nhập và chỉ cần một địa chỉ
email — đó là chỗ thuận tiện nhất để quét xem email nào có tài khoản F-Selling,
thứ dùng để nhắm mục tiêu lừa đảo.

Rò rỉ đi qua **ba kênh riêng biệt**, bịt thiếu kênh nào cũng bằng không:

| Kênh | Cách bịt |
|---|---|
| Mã HTTP | `forgot-password-request` và `resend-code` luôn trả 200; `verify-email` và `forgot-password-reset` trả đúng 400 "mã sai" cho email lạ |
| Nội dung câu trả lời | Dùng **cùng một hằng** `MSG_DA_GUI_MA`, và ở nhánh email lạ phải dùng **đúng chuỗi** mà `_dem_lan_nhap_sai_ma` trả về |
| Thời gian phản hồi | Đẩy việc gửi mail ra nền (mục 18) |

**Cooldown phải im lặng.** Trả 429 cho lần bấm thứ hai chính là một kênh rò rỉ
hoàn chỉnh: email không tồn tại thì bấm bao nhiêu lần cũng 200, email có thật
thì lần hai ra 429 — bấm hai lần là biết. Nay trong thời gian chờ vẫn trả 200 và
chỉ lặng lẽ không gửi mail.

**Lệch một chữ là hỏng.** Bản đầu nhánh email lạ của `forgot_password_reset` trả
"Mã **xác nhận** không hợp lệ" trong khi nhánh mã sai trả "Mã **xác thực** không
hợp lệ" — đúng một từ, và đủ để phân biệt.
`tests/test_rate_limit.py::test_forgot_password_reset_khong_lo_email_la` so sánh
nguyên vẹn hai body chính vì vậy.

**Frontend cũng phải đổi theo.** `auth.js` và `verify.js` hiện chuỗi của riêng
chúng (`forgot.code_sent`, `verify.resend_success`) chứ không hiện câu từ server,
nên sửa mỗi backend là người dùng vẫn đọc "đã gửi mã tới email của bạn" và không
bao giờ nghi mình gõ nhầm địa chỉ.

**Còn sót:** thời gian phản hồi vẫn lệch ~50ms (60ms so với 7ms) vì nhánh email
có thật còn ghi DB. Yếu hơn hẳn mức 3.522ms so với 4ms lúc đầu nhưng chưa phải
bằng 0; đóng nốt thì phải đẩy cả phần ghi DB ra nền.

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
