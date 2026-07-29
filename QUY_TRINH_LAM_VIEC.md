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

**Test là gì?** Là bộ kiểm tra tự động (~292 bài) chạy trong vài phút, thay
cho việc bạn phải bấm tay hàng trăm tình huống. Nó bắt lỗi giúp bạn.

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
sắc/bố cục). Cứ lưu thẳng:

```powershell
git add tên/file/vừa-sửa.css
git commit -m "mô tả"
```

> **Test chạy lâu (1–3 phút) là bình thường**, không phải treo. Muốn dừng ngay
> ở lỗi đầu tiên cho nhanh, dùng:
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

**Điều hay:** ngay sau khi push, **GitHub tự chạy lại toàn bộ test giúp bạn**
(nhờ GitHub Actions đã cài sẵn). Vào trang repo, mỗi commit sẽ có:
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
| Sửa giao diện mà không thấy đổi | Cache — bấm `Ctrl + Shift + R` |
| Báo `database is locked` | Đang mở web → bấm `Ctrl+C` tắt web, chạy lại, mở lại |
| Test chạy rất lâu | Bình thường. Muốn nhanh dùng `pytest -x` (dừng ở lỗi đầu) |
| Báo `nothing to commit` | Đã lưu rồi hoặc file chưa đổi — **không phải lỗi** |
| `TEST FAIL` (test đỏ) | Copy đoạn `FAILED tests/...` gửi người hỗ trợ, **đừng lưu** |

---

## 5 nguyên tắc vàng

1. **Sửa nhỏ từng lần** — mỗi lần một việc, dễ quay lui nếu sai.
2. **Sửa phần bên trong thì phải có test** — giao diện thì miễn.
3. **Giao diện phải tự mắt nhìn** — test không thấy được màu sắc/bố cục.
4. **Lưu (commit) xong mới đẩy (push)** — chắc chắn mới đưa lên.
5. **Không bao giờ đưa `.env` và file `.db` lên GitHub** — chứa mật khẩu và
   dữ liệu thật. (Máy đã tự chặn sẵn, nhưng luôn để ý.)
