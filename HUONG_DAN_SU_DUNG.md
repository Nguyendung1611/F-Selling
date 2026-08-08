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

### Nhập hàng và theo dõi công nợ nhà cung cấp

Phần này chứa giá nhập và số tiền cửa hàng còn nợ, nên chỉ **chủ cửa hàng** và
**Admin** nhìn thấy. Nhân viên không thấy tab và server cũng không cho gọi các
chức năng này.

#### 1. Tạo nhà cung cấp

1. Nếu đăng nhập tài khoản chủ shop: chọn đúng cửa hàng ở ô **Cửa hàng** trên
   đầu trang → bấm tab **Nhập Hàng**. Nếu đăng nhập Admin: bấm nút **Nhập
   Hàng** trên thanh đầu trang Admin; màn chuyên biệt sẽ mở ra, chỉ có phần
   nhập hàng và một ô chọn cửa hàng. Bấm **Về Admin** để quay lại.
2. Bấm tab con **Nhà cung cấp** → bấm **Thêm nhà cung cấp**.
3. Nhập tên; số điện thoại, mã số thuế, địa chỉ và ghi chú có thể để trống.
4. Nếu cửa hàng đã nợ nhà cung cấp từ trước khi dùng F-Selling, nhập **Nợ đầu
   kỳ** và hạn thanh toán. Nếu bắt đầu theo dõi từ hôm nay thì giữ số nợ là 0.
5. Bấm **Lưu**. Nhà cung cấp mới sẽ xuất hiện trong bảng cùng số **Còn nợ** và
   **Quá hạn**.

Nhà cung cấp chưa có lịch sử có thể xóa. Khi đã có phiếu nhập, nợ đầu kỳ hoặc
khoản trả, nút xóa chỉ chuyển họ sang **Ngừng sử dụng** để chứng từ cũ không bị
mất; có thể bật lại khi cần.

#### 2. Tạo và kiểm tra phiếu nhập

1. Trong tab **Nhập Hàng**, bấm tab con **Phiếu nhập** → **Tạo phiếu nhập**.
2. Chọn nhà cung cấp, ngày nhận hàng và hạn thanh toán nếu có. Số hóa đơn nhà
   cung cấp và ghi chú là tùy chọn.
3. Tìm một sản phẩm đang có trong cửa hàng → bấm **Thêm vào phiếu**.
4. Điền số lượng và **đơn giá cuối cùng cho một sản phẩm**. Đây là giá đã gồm
   mọi chi phí bạn muốn tính vào giá vốn; bản đầu tiên chưa có ô VAT, vận
   chuyển hay giảm giá riêng. Số tiền chỉ nhập VND nguyên, không nhập số lẻ.
5. Sản phẩm bật theo dõi lô sẽ hiện ô **Hạn sử dụng** bắt buộc. Làm tương tự
   cho các dòng còn lại rồi nhìn lại **Tổng phiếu**. Nếu cùng một sản phẩm
   được giao với hai hạn khác nhau, thêm sản phẩm đó hai lần và khai đúng hạn
   trên từng dòng.
6. Bấm **Lưu nháp**. Bạn sẽ thấy phiếu ở trạng thái **Nháp**; lúc này tồn kho,
   giá vốn và công nợ vẫn chưa thay đổi. Phiếu nháp còn sửa hoặc xóa được.

#### 3. Hoàn tất nhập hàng và ghi khoản đã trả ngay

Ở dòng phiếu nháp, bấm **Hoàn tất nhập hàng**. Hộp xác nhận bắt bạn nhập rõ số
tiền đã trả ngay (nhập 0 nếu chưa trả) và hiển thị **Còn nợ sau khi nhập**.
Khi số đã trả lớn hơn 0, bạn phải tự chọn nguồn tiền; phần mềm không chọn sẵn:

- Chọn **Tiền mặt trong két** khi lấy tiền từ ca đang mở của chính tài khoản
  đang thao tác. Két phải còn đủ tiền dự kiến; hệ thống ghi đúng một khoản chi.
- Chọn **Chuyển khoản** khi trả qua ngân hàng. Có thể điền mã tham chiếu để dễ
  đối soát; không cần mở ca.
- Chọn **Tiền bên ngoài cửa hàng** khi tiền không lấy từ két và cũng không đi
  qua tài khoản cần theo dõi trong F-Selling. Trường hợp này bắt buộc ghi chú.

Số đã trả có thể là 0, một phần hoặc toàn bộ tổng phiếu, nhưng không được lớn
hơn tổng phiếu. Kiểm tra lại rồi bấm **Xác nhận nhập hàng**. Bạn sẽ thấy phiếu
chuyển sang **Đã hoàn tất**; cùng lúc tồn kho, lô hàng, giá vốn bình quân và công
nợ mới được cập nhật. Phiếu đã hoàn tất bị khóa, không sửa, xóa hay hủy được.

#### 4. Trả nợ sau và xem lịch sử

Vào **Nhập Hàng → Nhà cung cấp**, tìm đúng dòng rồi bấm **Trả nợ**. Nhập số
tiền và chọn nguồn tiền giống bước trên; hộp sẽ hiện rõ **Nợ trước → Nợ sau**.
Không thể trả quá số còn nợ. Khi xác nhận, hệ thống tự cấn vào khoản nợ cũ nhất
trước. Bấm **Xem lịch sử** để kiểm tra từng phiếu, nợ đầu kỳ, khoản đã trả và
phần còn lại; khoản quá hạn sẽ được cảnh báo riêng.

Nút nhập/xuất thủ công cũ trong **Kho Hàng** nay tên là **Điều chỉnh kho** và
bắt buộc ghi lý do. Chức năng đó chỉ sửa số tồn, **không** tạo phiếu nhập, không
tạo công nợ và không ghi một khoản trả nhà cung cấp. Hàng mua chịu phải đi qua
tab **Nhập Hàng**.

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
> không phải việc của kiểm kê. Nếu là hàng mua từ nhà cung cấp, tạo phiếu ở
> **Nhập Hàng**; nếu chỉ sửa sai số tồn, dùng **Kho Hàng → Điều chỉnh kho** và
> khai đúng hạn đó.

### Hủy hàng hết hạn

Kho hàng → tab **Hạn sử dụng** → nút **Hủy hàng hết hạn** (chỉ chủ cửa hàng
thấy). Hệ thống liệt kê sẵn các lô đã quá hạn kèm số tiền vốn sẽ mất; xem lại
rồi mới xác nhận.

Số hàng hủy bị trừ khỏi kho và ghi thành **lỗ** trong báo cáo — dòng "Trừ ... hàng
hủy" dưới ô Lãi gộp ở Dashboard. Đây là điểm khác quan trọng so với việc dùng
Xuất kho: xuất kho làm tồn giảm mà lãi vẫn báo như cũ, tức là cao hơn thực tế.

> Thao tác này **không hoàn tác được**, và lô nào chưa khai giá vốn thì phần lỗ
> của nó không tính được — hệ thống sẽ nói rõ thay vì coi như bằng 0.

### Dự báo nhập hàng (hàng nào sắp hết, nên gọi bao nhiêu)

Kho hàng → tab **Dự Báo Nhập Hàng**. Máy nhìn 30 ngày bán gần nhất rồi trả lời
ba câu: món này bán bao nhiêu một ngày, còn đủ bán mấy ngày nữa, và nên gọi về
bao nhiêu.

Hai ô chọn ở đầu màn là để bạn khai thói quen của tiệm mình:

| Ô | Nghĩa | Chọn sao cho đúng |
|---|---|---|
| **Gọi hàng bao lâu thì về** | Từ lúc gọi điện tới lúc hàng nằm trên kệ | Nhà cung cấp giao trong ngày thì chọn 1; đặt Sài Gòn về tỉnh thì 3-5 |
| **Nhập một lần đủ bán** | Bạn muốn một lần nhập xài được bao lâu | Nhập hàng tuần thì 7; tiền eo hẹp thì để 7, dư vốn thì 14-30 |

Cột **Tình trạng** đọc từ trên xuống, gấp nhất nằm trên cùng:

- **Hết sạch hàng** — đang có khách hỏi mà không còn gì để bán. Gọi ngay.
- **Sắp cháy hàng** — sẽ hết TRƯỚC khi hàng mới kịp về. Cũng phải gọi ngay.
- **Nên gọi hàng** — còn đủ qua đợt giao tới, nhưng gọi luôn thể cho đỡ mất công.
- **Còn đủ** — chưa cần làm gì.
- **Đang nằm ế** — 30 ngày qua không bán được món nào. Đây là tiền đang chôn
  trong kho, không phải chuyện nhập hàng.

Ô **Tiền cần chuẩn bị** cộng tổng số tiền cho tất cả mặt hàng cần nhập, để bạn
biết trước phải xoay bao nhiêu. Chỉ chủ cửa hàng thấy ô này — nhân viên kho vẫn
xem được nên gọi món gì, số lượng bao nhiêu, nhưng không thấy tiền.

> **Dấu sao (\*) cạnh cột Bán/ngày** nghĩa là món đó chỉ phát sinh bán vài ngày
> trong cả tháng, nên con số mới là gợi ý chứ chưa đủ để chắc chắn. Hàng theo
> mùa hoặc hàng mới nhập về hay bị vậy.
>
> **Món chưa khai giá vốn** vẫn được gợi ý số lượng, chỉ là không tính được
> thành tiền — hệ thống nói rõ còn bao nhiêu món như vậy thay vì coi như 0đ.
>
> Cột "Gọi cho ai" lấy từ **phiếu nhập gần nhất** của món đó. Chưa từng tạo
> phiếu nhập ở tab Nhập Hàng thì ô này còn trống.

### Xả hàng tồn (hàng nào đang chôn vốn)

Kho hàng → tab **Xả Hàng Tồn**. Chỉ chủ cửa hàng thấy tab này.

Màn này trả lời câu ngược với Dự Báo Nhập Hàng: không phải "sắp hết cái gì" mà
là **"cái gì nằm mãi không đi"**. Hai loại bị gọi ra:

- **Nằm ế** — quá 45 ngày (chỉnh được) không bán được cái nào.
- **Sắp hết hạn** — lô còn dưới 30 ngày, bị gọi ra kể cả khi đang bán chạy.

Ô **Vốn đang nằm chết** là số tiền bạn đã bỏ ra mua số hàng đó và chưa thu lại
được đồng nào. Đây thường là con số làm chủ shop giật mình nhất.

Cột **Nên hạ còn** là giá đề xuất. Hai luật của nó:

1. **Không bao giờ thấp hơn giá vốn.** Máy dừng ở mức hòa vốn. Muốn bán lỗ để
   cắt lỗ thì đó là quyết định của bạn, máy không tự quyết thay.
2. **Càng sát ngày hết hạn càng giảm sâu.** Hàng còn 24 ngày giảm nhẹ; hàng còn
   3 ngày giảm mạnh — vì quá hạn là mất trắng cả tiền vốn.

Cột **Vẫn lãi** cho biết bán ở giá mới thì mỗi cái còn lời bao nhiêu.

Bấm **Hạ giá** → hệ thống mở sẵn form sửa sản phẩm với giá mới đã điền vào ô.
**Nó KHÔNG tự lưu.** Bạn xem lại rồi bấm Cập nhật thì giá mới có hiệu lực.

> **Ô đỏ "Đã hỏng, phải hủy"** chỉ hiện khi thật sự có hàng quá hạn. Số hàng đó
> **không được đem bán, kể cả hạ giá** — nó phải đi qua Kho hàng → Hạn sử dụng →
> Hủy hàng hết hạn để số lỗ vào đúng sổ.
>
> **Món chưa khai giá vốn** vẫn bị gọi ra là đang nằm ế, nhưng không có giá đề
> xuất — không biết mua vào bao nhiêu thì không biết hạ tới đâu là còn lãi.

### Dòng tiền và lợi nhuận ròng

Tab **Dòng Tiền** (chỉ chủ cửa hàng thấy) trả lời câu "cuối tháng túi tôi còn
bao nhiêu". Nó cho **hai con số, và hai con số này khác nhau là chuyện bình
thường**:

| | Nghĩa là gì |
|---|---|
| **Lợi nhuận ròng** | Tiền lời thật: lãi bán hàng trừ hết chi phí vận hành |
| **Dòng tiền thực** | Túi tiền kỳ này dày lên hay mỏng đi |

Vì sao khác nhau? Nhập hàng 10 triệu trả tiền ngay mà chưa bán món nào thì tiền
đã ra 10 triệu, nhưng hàng còn nằm trong kho nên chưa tính lời lỗ. Ngược lại,
bán chịu cho khách thì có lãi mà chưa cầm được đồng nào. Màn hình có sẵn một câu
đọc thẳng ra lý do, bạn không phải tự đoán.

**Khai chi phí cố định một lần.** Bấm **Chi phí cố định** rồi khai tiền thuê,
lương, internet kèm ngày trong tháng. Mỗi tháng ô vàng ở đầu màn sẽ nhắc:

> Lương chị Lan: đã ghi 2.000.000đ trên 6.000.000đ. **Còn thiếu 4.000.000đ.**

Bấm **Ghi nhận** là hộp thoại mở sẵn đúng số còn thiếu — sửa lại được nếu tháng
này có thưởng hoặc phạt. Hệ thống **không bao giờ tự trừ tiền**, luôn phải bạn
bấm xác nhận.

**Trả trước nhiều tháng.** Đóng tiền nhà 3 tháng một lần thì tick ô *"Khoản này
trả trước cho nhiều tháng"* rồi bấm nút **3 tháng**. Màn hình hiện ngay:

> Tính từ 15/08/2026 đến 14/11/2026. Mỗi tháng khoảng 10.000.000đ.

Tiền vẫn ra đủ 30 triệu trong dòng tiền hôm đó, nhưng lợi nhuận chỉ chịu phần
của tháng này — nên tháng đóng tiền không bị báo lỗ oan. Phần chưa tính hiện
ngay cạnh ô lợi nhuận: *"Bạn còn 20.000.000đ tiền thuê mặt bằng đã trả trước"*.

**Nguồn tiền có ba lựa chọn**, chọn đúng thì cuối ca đếm tiền mới khớp:

- **Tiền mặt lấy từ két** — trừ thẳng vào ca đang mở của bạn
- **Chuyển khoản** — không đụng tới két
- **Tiền túi riêng** — không đụng két, bắt buộc ghi rõ lý do

> ⚠️ **Hàng hỏng, hết hạn thì KHÔNG ghi ở đây.** Số đó đã được tính lỗ ở
> Kho hàng → Hủy hàng rồi. Ghi lại lần nữa là cùng một thùng hàng bị trừ hai
> lần và lợi nhuận thấp hơn sự thật.

Khoản ghi nhầm **chuyển khoản hoặc tiền túi riêng** thì gỡ được. Khoản đã lấy
tiền từ két thì không — két là sổ chỉ ghi thêm, và ca có thể đã đóng với số tiền
đếm tay khớp rồi. Ghi nhầm loại đó thì dùng **Thu tiền vào ca** để bù lại, nhớ
ghi chú lý do.

Đường màu xanh trên biểu đồ là **cộng dồn trong kỳ**, bắt đầu từ 0 — nó cho biết
kỳ này bạn dư ra hay hụt đi bao nhiêu, **không phải** số tiền đang có trong két.

### Gói Free và Pro

Gói tính **riêng cho từng cửa hàng**. Mỗi cửa hàng được dùng thử Pro đúng 30
ngày một lần; cửa hàng đã có khi nâng cấp bản này cũng được cấp lần dùng thử đó.
Sau đó shop tự về Free nếu chưa mua. Free vẫn dùng lâu dài để chủ shop bán tiền
mặt/VietQR, bán offline, quản lý sản phẩm và kho cơ bản, khách hàng, trả hàng,
tiếp tục dùng chương trình tích điểm đã cài và xem báo cáo 31 ngày gần nhất.

Pro có giá **99.000đ/30 ngày** hoặc **831.600đ/365 ngày** (gói năm đã giảm đúng
30%). Pro mở nhân viên/phân quyền, toàn bộ lịch sử và xuất Excel, màn **Ai Làm
Gì**, bán ghi nợ, tùy chỉnh chương trình tích điểm, voucher, công nợ nhà cung
cấp/phiếu nhập, kiểm kê, lô/hạn dùng và hủy hàng. Chỉ gói đã trả tiền có thêm 7
ngày gia hạn; thời gian dùng thử và Pro do Admin tặng hết đúng ngày đã ghi.

#### Chủ shop mua Pro

1. Ở trang Seller, chọn đúng cửa hàng trong ô **Cửa hàng** phía trên → bấm tab
   **Gói cước**.
2. Bạn sẽ thấy nhãn Free / Dùng thử / Pro trả phí / Pro được tặng / Gia hạn và
   ngày kết thúc tương ứng.
3. Bấm **Mua Pro tháng** hoặc **Mua Pro năm**. Khi tài khoản nhận phí nền tảng
   đã được cấu hình, màn hình hiện một mã QR, đúng số tiền và nội dung bắt đầu
   bằng `SUB...`.
4. Quét QR và giữ nguyên nội dung. Màn hình tự kiểm tra; khi ngân hàng báo tiền
   về, bạn sẽ thấy **Đã kích hoạt Pro đến...**. Mua sớm được nối tiếp từ ngày
   hết hạn đang có; mua trong 7 ngày gia hạn nối từ hạn trả phí cũ.

Mã thanh toán sống 24 giờ. Chuyển thiếu được cộng dồn vào cùng mã nhưng chỉ đủ
tiền mới cấp Pro. Chuyển thừa chỉ cấp đúng một kỳ; phần dư và tiền đến sai/hết
mã sẽ hiện trong bảng Admin để xử lý, không tự đổi thành thêm ngày và không tự
hoàn tiền.

#### Admin tặng hoặc thu hồi Pro

1. Ở trang Admin, bấm **Gói cước Shop**.
2. Tìm đúng cửa hàng → bấm **Tặng Pro** hoặc **Gia hạn** → chọn **Dùng đến hết
   ngày**, nhập lý do bắt buộc → bấm xác nhận. Gói tặng là 0đ và không đi vào
   doanh thu.
3. Nếu dòng có quà tặng đang còn hiệu lực, bấm **Thu hồi** và nhập lý do. Nút
   này chỉ gỡ phần Admin đã tặng; không thể cắt thời gian khách đã trả tiền.
4. Bảng **Thanh toán gói cần xử lý** cho biết khoản không mã, sai mã, sai tài
   khoản, đến trễ, chuyển thiếu hoặc chuyển thừa.

Khi Pro hết hạn, F-Selling không xóa dữ liệu. Phiếu nhập nháp cũ vẫn xem được
nhưng không sửa/chốt; voucher cũ vẫn dùng được. Các việc giải quyết tiền đã phát
sinh vẫn mở: đồng bộ đơn offline, hoàn/trả hàng, thu nợ khách, trả nợ nhà cung
cấp và đóng ca. Báo cáo quá 31 ngày, xuất file và màn **Ai Làm Gì** sẽ mở lại
khi gia hạn Pro; dữ liệu của các màn đó vẫn được giữ nguyên trong thời gian Free.

## 6. File cấu hình `.env`

| Biến | Ý nghĩa |
|---|---|
| `SECRET_KEY` | Khóa ký JWT. Bắt buộc, giữ bí mật. |
| `ADMIN_INITIAL_PASSWORD` | Mật khẩu admin (app tự đồng bộ khi khởi động). |
| `PAYMENT_WEBHOOK_SECRET` | Secret cho webhook thanh toán (thiếu thì webhook trả 503). |
| `SUBSCRIPTION_BANK_CODE` | Mã ngân hàng nhận phí F-Selling (tài khoản nền tảng, không phải tài khoản của shop). |
| `SUBSCRIPTION_BANK_ACCOUNT_NO` | Số tài khoản nền tảng nhận phí Pro. |
| `SUBSCRIPTION_BANK_ACCOUNT_NAME` | Tên chủ tài khoản nền tảng nhận phí Pro. |
| `SUBSCRIPTION_WEBHOOK_SECRET` | Secret riêng cho webhook tiền gói Pro; không dùng chung secret đơn bán. |
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
