# Quy Trình Làm Việc F-Selling

> Đọc file này là biết cách sửa dự án đúng cách. Không cần biết trước gì nhiều.

Mỗi lần muốn thay đổi gì, đi theo **5 bước** này:

```
1. SỬA CODE  →  2. CHẠY TEST  →  3. NHÌN THỬ  →  4. LƯU LẠI  →  5. ĐẨY LÊN GITHUB
```

---

## Chuẩn bị: mở terminal đúng chỗ

Mở **PowerShell**, dán dòng này để vào thư mục dự án (mọi lệnh đều chạy ở đây):

```powershell
cd "C:\Users\nguye\OneDrive\Desktop\FSellingV2\F-Selling-main\F-Selling-main\F-Selling-master-main\python_app"
```

---

## Bước 1 — SỬA CODE

Mở VS Code, sửa file, nhấn `Ctrl + S` để lưu. Xong.

Muốn xem mình vừa sửa file nào:

```powershell
git status
```

(Dòng có chữ `M` = file đã sửa. Dòng `??` = file mới.)

---

## Bước 2 — CHẠY TEST

**Test là gì?** Là bộ kiểm tra tự động chạy khoảng 10–12 phút, thay cho việc
bạn phải bấm tay hàng trăm tình huống. Nó bắt lỗi giúp bạn.

Số bài test **cố ý không ghi ở đây**: nó tăng theo mỗi tính năng mới, và một con
số chép trong tài liệu sẽ sai đi trong im lặng (đã sai ba lần rồi). Script tự in
số bài và thời gian ra mỗi lần chạy — đó mới là con số thật.

### Nếu bạn sửa code Python → dùng lệnh này:

```powershell
.\test-commit.ps1 "mô tả ngắn việc vừa làm"
```

Lệnh này tự làm 3 việc liền: **chạy test → nếu đạt thì tự lưu (commit) → chặn
không cho lộ mật khẩu**.

- Hiện chữ **`TEST PASS`** màu xanh → xong, đã lưu tự động.
- Hiện chữ **`TEST FAIL`** màu đỏ → **chưa lưu**. Copy đoạn `FAILED tests/...`
  gửi cho người hỗ trợ. Đừng cố lưu.

### Nếu bạn chỉ sửa giao diện (file .css / .html / .js) → bỏ qua test:

Giao diện không có test tự động (test chỉ kiểm phần bên trong, không kiểm màu
sắc/bố cục). Nhưng có **hai việc bắt buộc phải làm trước khi lưu** — cả hai đều
là loại hỏng không báo lỗi gì cả:

#### a) Bump `?v=` — sửa file trong `static/` thì phải đổi số phiên bản

Trình duyệt giữ file JS/CSS cũ rất dai. Cách duy nhất bắt nó tải bản mới là đổi
cái đuôi `?v=` ở thẻ `<script>` / `<link>` trỏ tới file đó trong `static/*.html`:

```html
<!-- trước -->
<script src="/js/pos.js?v=20260802-bien-the"></script>
<!-- sau  -->
<script src="/js/pos.js?v=20260805-tich-diem"></script>
```

Quy ước đang dùng: `YYYYMMDD-mô-tả-ngắn`.

> **Bẫy lớn nhất: một file thường nằm trong NHIỀU trang.** `api.js`, `i18n.js`,
> `locales/common.js` và `css/style.css` mỗi cái được nhắc ở **cả 6 trang HTML**.
> Bump ở `pos.html` rồi tưởng xong, trong khi `seller.html` vẫn trỏ số cũ —
> người bán vào màn Kho Hàng chạy `api.js` cũ, còn bạn thì không thấy gì bất
> thường.
>
> Tìm hết mọi chỗ cần đổi trước khi sửa:
>
> ```powershell
> Select-String -Path static\*.html -Pattern "api\.js\?v="
> ```

Quên bump thì **người dùng chạy code cũ trong im lặng, không lỗi, không cảnh
báo** — chỉ là tính năng mới không có ở đó. Dự án đã dính đúng lỗi này một lần ở
bản giá vốn.

`Ctrl + Shift + R` chỉ chữa cho **máy bạn**. Người dùng không ai bấm cả — họ chỉ
nhận được bản mới khi số `?v=` đổi.

#### b) Kiểm cú pháp JS

`test-commit.ps1` có một bước chạy `node --check` trên mọi file trong
`static/js` — thêm vào vì file locale đã vỡ cú pháp **hai lần**, mà một file
locale vỡ là toàn bộ bản dịch của trang đó không nạp được và người dùng nhìn
thấy `seller.page_title` thay vì chữ tiếng Việt. Lưu tay là đi vòng qua đúng
bước đó. Chạy riêng cho nhanh:

```powershell
node --check static/js/tên-file-vừa-sửa.js
```

Không in gì ra = không sao. In ra lỗi = **đừng lưu**, sửa cú pháp đã.

#### Xong hai việc trên rồi thì lưu thẳng:

```powershell
git add tên/file/vừa-sửa.css static/pos.html
git commit -m "mô tả"
```

> **Chạy hơn 10 phút là bình thường**, không phải treo. Cả bộ chậm đều nhau vì
> bcrypt: mỗi test tạo tài khoản tốn hai lần băm mật khẩu. Đó là lựa chọn có chủ
> ý — test chạy đúng tham số của production. Muốn dừng ngay ở lỗi đầu tiên cho
> nhanh, dùng:
> `.\.venv\Scripts\python.exe -m pytest -x -q -p no:warnings`

---

## Khi nào cần VIẾT THÊM test?

Không phải lúc nào cũng cần. Nhìn bảng này:

| Bạn vừa làm gì | Cần viết thêm test? |
|---|---|
| Thêm tính năng mới ở **phần bên trong** (Python) | **CÓ** |
| Sửa một **lỗi** ở phần bên trong | **CÓ** — viết test tái hiện lỗi trước, rồi sửa |
| Sửa **giao diện** (màu, chữ, bố cục, nút) | **KHÔNG** |
| Sửa văn bản, chú thích, tài liệu | **KHÔNG** |

**Viết thêm test dễ hay khó?** Dễ. Chỉ cần tạo một file mới tên bắt đầu bằng
`test_` trong thư mục `tests/`, ví dụ `tests/test_hoa_don.py`. Máy tự tìm và
chạy nó cùng các test cũ — không phải khai báo ở đâu cả. Trong `tests/conftest.py`
đã có sẵn "đồ nghề" (tạo shop, tạo nhân viên, đăng nhập...) để dùng lại cho nhanh.

---

## Bước 3 — NHÌN THỬ (chỉ khi sửa giao diện)

Phần bên trong đã có test lo. Nhưng **giao diện thì phải tự mắt nhìn**:

1. Mở web (xem Bước 5 phần "Chạy thử web").
2. Vào trình duyệt: `http://127.0.0.1:8000`
3. **Bấm `Ctrl + Shift + R`** để nạp lại giao diện mới.
   (Quan trọng: `F5` thường hay giữ bản cũ, làm tưởng sửa không ăn.)
   Nhưng nhớ: cái này chỉ chữa cho máy bạn. Muốn người dùng thấy bản mới thì
   phải bump `?v=` — xem Bước 2a.
4. Muốn xem trên điện thoại: `F12` → bấm biểu tượng điện thoại → chọn máy.

---

## Bước 4 — LƯU LẠI (commit)

Nếu bạn đã dùng `test-commit.ps1` thì đã lưu tự động rồi — bỏ qua bước này.

Lưu thủ công (khi sửa giao diện):

```powershell
git add <file>
git commit -m "mô tả ngắn, rõ việc"
```

Xem lại đã lưu những gì:

```powershell
git log --oneline -5
```

---

## Bước 5 — ĐẨY LÊN GITHUB (update)

Khi muốn cập nhật code lên GitHub cho mọi người thấy:

```powershell
git push
```

> ⚠️ **GitHub Actions hiện KHÔNG chạy** — tài khoản bị khóa thanh toán. Cấu hình
> vẫn nằm nguyên ở `.github/workflows/tests.yml` và sẽ tự chạy lại khi mở khóa,
> nhưng **cho tới lúc đó, push lên không có ai kiểm hộ**.
>
> Nghĩa là: **bộ test chạy ở máy bạn là lưới an toàn duy nhất.** Càng phải dùng
> `test-commit.ps1` cho mọi lần commit code Python, đừng commit tay.

Khi Actions chạy lại được, mỗi commit trên trang repo sẽ có:
- Dấu ✅ xanh = tất cả test đạt.
- Dấu ❌ đỏ = có test hỏng, bấm vào xem chi tiết.

Xem kết quả tại: https://github.com/Nguyendung1611/F-Selling/actions

### Chạy thử web

```powershell
.\.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Đợi dòng `Uvicorn running on...` rồi mở `http://127.0.0.1:8000`.
Dừng web: bấm `Ctrl + C` trong cửa sổ đó.

---

## Bảng lệnh nhanh (tra khi cần)

| Muốn làm | Gõ lệnh |
|---|---|
| Vào thư mục dự án | `cd "...\python_app"` |
| Xem file nào vừa đổi | `git status` |
| Test + tự lưu (code Python) | `.\test-commit.ps1 "mô tả"` |
| Test nhanh, dừng ở lỗi đầu | `.\.venv\Scripts\python.exe -m pytest -x -q -p no:warnings` |
| Lưu thủ công (giao diện) | `git add <file>` rồi `git commit -m "..."` |
| Đẩy lên GitHub | `git push` |
| Mở web thử | `.\.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8000` |
| Xem lịch sử đã lưu | `git log --oneline -10` |

---

## Gặp trục trặc? (rất hay gặp)

| Hiện tượng | Cách xử |
|---|---|
| Báo `index.lock ... File exists` | `Remove-Item .git\index.lock -Force` rồi làm lại |
| Sửa giao diện mà không thấy đổi | Bấm `Ctrl + Shift + R`. Vẫn y nguyên → quên bump `?v=`, hoặc bump thiếu trang (xem Bước 2a) |
| Đã bump `?v=` rồi mà **vẫn** thấy code cũ | **Service worker đang trả bản đã lưu.** `Ctrl + Shift + R` không gỡ được nó, và `fetch()` cũng không. Mở DevTools → Application → Service Workers → **Unregister**, rồi Storage → **Clear site data**. Chỉ xảy ra khi sửa file trong một phiên đã mở trang từ trước mà chưa đổi `?v=`; người dùng thật không dính vì mỗi bản phát hành là một số `?v=` mới |
| Báo `database is locked` | Đang mở web → bấm `Ctrl+C` tắt web, chạy lại, mở lại |
| Test chạy rất lâu | Bình thường. Muốn nhanh dùng `pytest -x` (dừng ở lỗi đầu) |
| Báo `nothing to commit` | Đã lưu rồi hoặc file chưa đổi — **không phải lỗi** |
| `TEST FAIL` (test đỏ) | Copy đoạn `FAILED tests/...` gửi người hỗ trợ, **đừng lưu** |

---

## 5 nguyên tắc vàng

1. **Sửa nhỏ từng lần** — mỗi lần một việc, dễ quay lui nếu sai.
2. **Sửa phần bên trong thì phải có test** — giao diện miễn test, nhưng sửa file
   trong `static/` thì phải bump `?v=` ở **mọi** trang dùng file đó, và sửa
   `.js` thì phải `node --check` trước khi lưu.
3. **Giao diện phải tự mắt nhìn** — test không thấy được màu sắc/bố cục.
4. **Lưu (commit) xong mới đẩy (push)** — chắc chắn mới đưa lên.
5. **Không bao giờ đưa `.env` và file `.db` lên GitHub** — chứa mật khẩu và
   dữ liệu thật. (Máy đã tự chặn sẵn, nhưng luôn để ý.)
