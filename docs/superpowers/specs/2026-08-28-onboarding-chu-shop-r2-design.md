# Onboarding Chủ shop R2 — Đặc tả thiết kế

Ngày: 2026-08-28
Trạng thái: Đã duyệt thiết kế trong hội thoại; chờ duyệt tài liệu trước khi lập kế hoạch triển khai.

## 1. Bối cảnh

F-Selling phục vụ chủ tiệm tạp hóa truyền thống, đặc biệt là người lớn tuổi hoặc
chưa từng dùng POS. Sau đăng ký và xác minh, tài khoản SELLER hiện đi thẳng vào
`/seller`. Nếu chưa có cửa hàng, trang tự mở form cấu hình đầy đủ với nhiều
trường pháp lý và ngân hàng. Người mới chưa thấy rõ việc tối thiểu cần làm để
bán được đơn đầu tiên.

Backend đã có `GET /api/onboarding/{shop_id}`. Endpoint chỉ đọc dữ liệu nghiệp
vụ bền vững và trả năm sự kiện: cửa hàng đã tạo, có sản phẩm, từng mở ca, từng
có đơn `PAID`/`DEBT`, và từng đóng ca. UI checklist năm dòng trước đây đã bị gỡ
vì chen vào dashboard và tạo quá nhiều lựa chọn cùng lúc. R2 không khôi phục
checklist đó; R2 tạo một đường bắt đầu riêng, mỗi lần chỉ giao một việc.

## 2. Mục tiêu

- Đưa một chủ shop hoàn toàn mới từ lần đăng nhập đầu tiên tới đơn bán đầu tiên.
- Chỉ hỏi thông tin cần thiết ngay lúc đó; phần cấu hình nâng cao để sau.
- Luôn dùng dữ liệu thật do người dùng xác nhận, không tạo sản phẩm hoặc tồn kho
  mẫu.
- Cho phép bỏ qua và quay lại mà không bật màn chào ở mỗi lần đăng nhập.
- Làm nổi bật Trợ lý như nơi hỗ trợ đúng ngữ cảnh, nhưng không biến chat thành
  cổng bắt buộc và không cho Trợ lý tự thay đổi nghiệp vụ.
- Không làm gián đoạn tài khoản cũ, STAFF, ADMIN hoặc luồng demo chung.

## 3. Ngoài phạm vi

- Không tạo ứng dụng hoặc route onboarding riêng.
- Không thêm bảng database, migration, framework tour hay dependency frontend.
- Không tự mở ca, tự tạo đơn, tự hoàn tất thanh toán hoặc tự đóng ca.
- Không tạo sản phẩm mẫu, tồn kho mẫu hoặc social proof giả.
- Không bắt người dùng đóng ca để được xem là hoàn tất bước bắt đầu.
- Không bật Gemini, server-side TTS, billing, deployment hoặc provider call.

## 4. Quyết định đã duyệt

1. Onboarding được nhúng trong `/seller` và tái sử dụng auth, quyền, form, API
   cùng POS hiện tại.
2. Màn chào tự xuất hiện chỉ khi vai trò là `SELLER`, `GET /shops` trả danh sách
   rỗng và trình duyệt chưa ghi nhận lựa chọn “Để sau” cho đúng tài khoản.
3. Luồng có ba bước cấp cao: tạo cửa hàng, thêm mặt hàng thật đầu tiên, mở POS
   và bán đơn đầu tiên. Mở ca được hướng dẫn bên trong POS, không tách thành một
   màn cấp cao.
4. Mốc hoàn tất R2 là `sale_completed === true`, tức đã có đơn `PAID` hoặc
   `DEBT`. Không dùng trường `complete` của endpoint R1 vì trường đó còn yêu cầu
   đóng ca.
5. Bỏ qua được ghi ở trình duyệt theo tài khoản, không ghi database và không
   được tính là hoàn thành nghiệp vụ.
6. Tạo cửa hàng ban đầu chỉ bắt buộc tên cửa hàng và số điện thoại.
7. Sản phẩm đầu tiên chỉ hỏi tên, giá bán và số lượng thực đang có. Không đặt
   sẵn tồn kho `100` hoặc bất kỳ số lượng nào khác.
8. Khi sản phẩm đầu tiên không có danh mục, server tạo hoặc dùng lại danh mục hệ
   thống `Chưa phân loại` trong cùng transaction với sản phẩm.
9. Trợ lý chỉ giải thích hoặc điều hướng. Trước khi có shop, nội dung trợ giúp
   là hướng dẫn xác định sẵn trên máy cùng kênh Zalo/điện thoại; không giả vờ
   phân tích dữ liệu cửa hàng.

## 5. Kiến trúc trạng thái

### 5.1 Điểm vào

Khởi động `/seller` vẫn gọi `GET /shops` như hiện tại, sau đó áp dụng bảng quyết
định:

| Điều kiện | Kết quả |
| --- | --- |
| Vai trò không phải SELLER | Luồng hiện tại, không tải hoặc hiện onboarding R2 |
| SELLER, không có shop, chưa bỏ qua | Hiện shell onboarding ở bước tạo cửa hàng |
| SELLER, không có shop, đã bỏ qua | Hiện dashboard rỗng cùng thẻ “Tiếp tục thiết lập” |
| SELLER, có shop | Vào dashboard bình thường, đọc trạng thái onboarding của shop hiện tại |
| `sale_completed` là `false` | Hiện một thẻ “Tiếp tục thiết lập” với đúng hành động kế tiếp |
| `sale_completed` là `true` | Ẩn thẻ; onboarding R2 đã hoàn tất |

Tài khoản demo chung đã có dữ liệu nên tiếp tục đi theo luồng demo tới POS,
không bị màn chào R2 chặn.

### 5.2 Trạng thái bỏ qua

Khóa local storage được tạo chính xác bằng:

`fselling.onboarding.r2.dismissed:${encodeURIComponent(username)}`

Giá trị là chuỗi `1`; không lưu bước hoàn thành hoặc dữ liệu nghiệp vụ. Khóa
được tách theo username để hai tài khoản dùng chung trình duyệt không ảnh hưởng
nhau. Đổi máy hoặc xóa dữ liệu trình duyệt có thể làm màn chào xuất hiện lại;
dữ liệu nghiệp vụ và tiến độ thật không bị mất.

### 5.3 Tiến độ bền vững

- Không có shop: dùng kết quả `GET /shops`; chưa gọi endpoint onboarding.
- Có shop: dùng `GET /api/onboarding/{shop_id}`.
- Có shop nhưng chưa có sản phẩm: hành động tiếp theo là thêm sản phẩm.
- Có sản phẩm nhưng chưa có đơn hoàn tất: hành động tiếp theo là mở POS. Trạng
  thái mở ca được POS tự kiểm tra và yêu cầu người dùng thao tác nếu cần.
- Có đơn `PAID` hoặc `DEBT`: ẩn toàn bộ nhắc việc R2.

Mọi lần reload, đổi shop hoặc quay về từ POS đều đọc lại trạng thái server. UI
không suy diễn hoàn thành từ số nút đã bấm.

## 6. Thiết kế trải nghiệm

Shell onboarding thay phần nội dung quản trị chính trong `/seller`, nhưng giữ
nhận diện F-Selling, chọn ngôn ngữ và đường thoát. Điều hướng quản trị đầy đủ
không chiếm ưu thế thị giác trong shell. Mỗi màn có chỉ báo “Bước n/3”, một tiêu
đề, một đoạn giải thích ngắn, một hành động chính, đường bỏ qua và nút hỗ trợ.

### 6.1 Bước 1 — Tạo cửa hàng

- Tiêu đề: `Bắt đầu với cửa hàng của mình`
- Giải thích: `Chỉ cần hai thông tin để mở quầy. Những phần còn lại có thể bổ
  sung sau.`
- Trường bắt buộc: `Tên cửa hàng`, `Số điện thoại`.
- CTA chính: `Tạo cửa hàng và tiếp tục`.
- CTA phụ: `Để sau, vào quản lý`.
- Hỗ trợ: `Không biết điền gì? Hỏi Trợ lý`.

Sau khi lưu thành công, shop mới trở thành `currentShopId`, danh sách shop được
cập nhật và shell chuyển sang bước 2. Không tự reload trước khi người dùng thấy
kết quả thành công.

### 6.2 Bước 2 — Thêm mặt hàng đầu tiên

- Tiêu đề: `Thêm một món đang có trong cửa hàng`.
- Trường bắt buộc: `Tên sản phẩm`, `Giá bán`, `Số lượng đang có`.
- Không hiện mã nội bộ, mã vạch, giá vốn, ảnh, biến thể, theo dõi lô hoặc danh
  mục.
- Không có giá trị tồn kho mặc định. Số lượng phải do người dùng nhập.
- CTA chính: `Lưu mặt hàng`.

Nếu request không gửi `category_id`, server tìm danh mục hệ thống `Chưa phân
loại` trong đúng shop hoặc tạo nó rồi tạo sản phẩm trong cùng transaction.
Trong locale tiếng Anh, UI phải ánh xạ đúng tên hệ thống này thành
`Uncategorized`; dữ liệu lưu canonical vẫn là `Chưa phân loại`.

### 6.3 Bước 3 — Mở quầy bán hàng

Màn hình nhắc lại tên, giá và tồn kho của sản phẩm vừa tạo để người dùng kiểm
tra. CTA chính là `Mở quầy và bán đơn đầu tiên`; CTA phụ là `Sửa lại mặt hàng`.

CTA mở POS bằng URL `/pos?tour=sale&onboarding=r2`. POS giữ quyền kiểm soát cho
người dùng:

1. Chọn đúng cửa hàng và mở ca nếu chưa có ca.
2. Chọn hoặc quét mặt hàng.
3. Kiểm tra giỏ, hình thức thanh toán và số tiền.
4. Người dùng tự bấm hoàn tất.

Sau khi tạo đơn `PAID` hoặc `DEBT` thành công trong đúng phiên onboarding, POS
hiện thông báo: `Xong rồi — bạn đã bán đơn đầu tiên bằng F-Selling.` Hai hành
động là `Xem tổng quan cửa hàng` và `Bán thêm đơn nữa`.

### 6.4 Thẻ tiếp tục trên dashboard

Thẻ không liệt kê toàn bộ checklist. Nó chỉ có:

- Tiêu đề `Tiếp tục thiết lập`.
- Một câu mô tả hành động kế tiếp.
- Một CTA duy nhất.
- Nút đóng/để sau không thay đổi trạng thái nghiệp vụ.

Với shop chưa có sản phẩm, CTA mở bước 2. Với shop có sản phẩm nhưng chưa có đơn
hoàn tất, CTA mở POS ở chế độ hướng dẫn. Thẻ biến mất ngay khi server trả
`sale_completed: true`.

## 7. Thay đổi hợp đồng nghiệp vụ tối thiểu

### 7.1 Cửa hàng

`ShopCreate` cho phép địa chỉ, mã số thuế, email và ba trường ngân hàng để trống.
Service tạo/cập nhật chỉ luôn bắt buộc tên và số điện thoại. Cấu hình ngân hàng
tuân theo quy tắc tất-cả-hoặc-không-có: nếu người dùng khai một trong ba trường
`bank_code`, `bank_account_no`, `bank_account_name`, cả ba phải hợp lệ.

Không cần migration vì các cột Shop hiện tại không khai `nullable=False`.
Luồng cấu hình đầy đủ vẫn gửi và lưu các trường như trước.

### 7.2 VietQR

Tạo cửa hàng không có tài khoản ngân hàng không được tạo QR intent. Khi chọn
chuyển khoản, POS phải báo rõ `Chưa thiết lập tài khoản nhận chuyển khoản` và
đưa chủ shop tới phần Cài đặt phù hợp. Tiền mặt và ghi nợ vẫn dùng được.

Kiểm tra này phải tồn tại ở server; ẩn hoặc khóa nút ở frontend chỉ là hỗ trợ
trải nghiệm, không phải ranh giới an toàn.

### 7.3 Sản phẩm và danh mục mặc định

Chỉ endpoint tạo sản phẩm cho phép thiếu `category_id`. Service resolve danh
mục mặc định theo đúng `shop_id`, tạo mới nếu chưa có, rồi tạo sản phẩm trong
cùng transaction. Update sản phẩm vẫn yêu cầu một `category_id` hợp lệ như hiện
tại. Không cho phép đoán hoặc dùng danh mục của shop khác.

Nếu tạo sản phẩm thất bại, transaction rollback cả danh mục vừa tạo. Nếu request
bị gửi lặp, quy tắc trùng tên/mã hiện có tiếp tục ngăn sản phẩm trùng; UI khóa
nút trong lúc request đang chạy.

## 8. Trợ lý trong onboarding

Mỗi bước có nút `Không biết làm? Hỏi Trợ lý`.

- Trước khi có shop: mở help sheet cục bộ với giải thích đúng bước và thông tin
  hỗ trợ Zalo/điện thoại. Không gọi endpoint shop-scoped.
- Sau khi có shop: help sheet vẫn giải thích bước hiện tại và thêm CTA `Mở Trợ
  lý`; CTA này mở tab Trợ lý hiện có, không tự gửi câu hỏi.
- Trợ lý không điền form, không gửi request thay người dùng, không mở ca và
  không hoàn tất đơn.
- Gemini và server TTS giữ OFF. Hướng dẫn cơ bản vẫn đọc được khi mất mạng.

## 9. Lỗi, offline và phục hồi

- Trong lúc lưu, CTA đổi sang trạng thái đang xử lý và bị khóa.
- Lỗi validation đặt sát trường liên quan; dữ liệu đã nhập được giữ nguyên.
- Lỗi mạng hiển thị `Chưa lưu vì máy đang mất mạng` và nút `Thử lại`.
- Không xếp hàng offline thao tác tạo shop, danh mục hoặc sản phẩm; không thể bảo
  đảm quyền và tính duy nhất nếu mutation setup được replay ngầm.
- Mọi retry phải an toàn trước thao tác bấm lặp và response cũ; chỉ response của
  request hiện tại được đổi màn.
- Refresh hoặc nhiều tab không dùng state UI cũ để ghi đè dữ liệu server.
- Nếu shop hoặc sản phẩm đã được tạo ở tab khác, lần tải lại danh sách và trạng
  thái sẽ đưa người dùng tới đúng hành động kế tiếp.
- Người dùng luôn có đường về dashboard; không có modal bắt buộc hoặc countdown.

## 10. Khả dụng và nội dung

- Font nội dung và input tối thiểu 16px trên mobile; vùng bấm tối thiểu 44px.
- Thứ tự focus đi theo nội dung; sau lỗi, focus trường lỗi đầu tiên.
- Trạng thái loading/error/success dùng `aria-live` phù hợp và không chỉ dựa vào
  màu sắc.
- Hỗ trợ bàn phím, reduced motion, màn hình hẹp và phóng to 200%.
- Tất cả chuỗi mới có Việt/Anh; tiếng Việt là nội dung sản phẩm chính.
- Copy dùng từ quen thuộc: `cửa hàng`, `mặt hàng`, `số lượng đang có`, `mở quầy`;
  tránh thuật ngữ như wizard, catalog hoặc configuration.

## 11. Kiểm thử và tiêu chí chấp nhận

### 11.1 Backend

- Tạo shop chỉ với tên và số điện thoại thành công, tạo trial như hiện tại.
- Tạo/cập nhật shop với bộ thông tin đầy đủ tiếp tục thành công.
- Cấu hình ngân hàng khai thiếu một phần bị từ chối rõ ràng.
- Không có ngân hàng: cash/debt vẫn hoạt động; VietQR bị từ chối ở server với
  thông báo an toàn, không tạo intent một phần.
- Tạo sản phẩm thiếu category tạo/dùng lại `Chưa phân loại` đúng shop.
- Category và product cùng commit hoặc cùng rollback.
- Giá là số VND nguyên dương; tồn là số nguyên dương trong luồng onboarding.
- Ranh giới owner/shop và quy tắc category thuộc shop không bị nới lỏng.

### 11.2 Frontend contract

- Shell chỉ hiện cho SELLER không có shop và chưa dismiss theo đúng username.
- STAFF, ADMIN, owner cũ và demo chung không bị chặn.
- Ba màn chỉ có đúng các trường và CTA đã duyệt; không còn tồn mặc định `100`
  trong luồng R2.
- Resume card luôn chỉ có một next action và dùng `sale_completed`, không dùng
  `complete`.
- Trợ lý trước-shop không gọi provider hoặc endpoint shop-scoped.
- Query POS R2 chỉ kích hoạt hướng dẫn khi được yêu cầu; POS bình thường không
  hiện onboarding.
- Locale Việt/Anh đầy đủ, không thiếu khóa hoặc trùng ID.

### 11.3 Trình duyệt và regression

- Smoke desktop và mobile cho happy path, bỏ qua/quay lại, validation, offline,
  retry, refresh, đổi tài khoản và nhiều tab.
- Xác nhận sau đơn PAID và DEBT; card ẩn khi quay về dashboard.
- Kiểm tra 200% zoom, keyboard, focus, `aria-live`, không tràn ngang và không có
  console error.
- Chạy regression auth, shops, subscription trial, products/categories, POS,
  orders, offline, QR, onboarding R1, i18n và landing/demo entry.

## 12. Ranh giới phát hành

R2 được triển khai local trước. Không bật billing, deploy hoặc AI provider. Sau
khi test tự động và browser QA đạt, chủ dự án duyệt trải nghiệm local trước khi
bất kỳ thay đổi phát hành nào được cân nhắc.

Không còn quyết định sản phẩm mở trong phạm vi đặc tả này.
