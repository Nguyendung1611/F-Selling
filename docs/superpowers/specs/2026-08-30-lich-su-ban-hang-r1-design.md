# Lịch sử bán hàng R1 — Đặc tả thiết kế

Ngày: 2026-08-30

Trạng thái: Đặc tả đã được khách hàng duyệt ngày 2026-08-30; kế hoạch triển khai đã được lập.

## 1. Bối cảnh

POS đã có luồng `Tìm hóa đơn cũ` theo đúng mã đơn và có thể dựng lại bản sao
hóa đơn từ dữ liệu server. Hóa đơn dùng ảnh chụp dòng hàng lúc bán, hỗ trợ in
và chia sẻ ảnh; nhân viên không được sao chép rồi sửa nội dung văn bản.

Luồng hiện tại chưa giúp người dùng nhớ lại mã đơn. Nhân viên cần một danh sách
đơn gần đây và một cách tìm đơn bằng thông tin quen thuộc như tên hoặc số điện
thoại khách. API dashboard đã có danh sách đơn nhưng yêu cầu quyền `REPORT` và
có dữ liệu báo cáo; không phù hợp để mở cho mọi người có quyền bán hàng.

## 2. Mục tiêu

- Cho người có quyền `SALE` tìm và mở lại đơn đã hoàn tất ngay trong POS.
- Mặc định cho thấy 20 đơn mới nhất hôm nay; có bộ lọc nhanh 7 ngày.
- Cho phép tìm toàn bộ lịch sử bằng mã đơn, tên khách hoặc số điện thoại.
- Dùng lại hóa đơn cố định hiện có để xem, in và gửi lại mà không sửa nội dung.
- Giữ giao diện dễ hiểu cho chủ tiệm và nhân viên ít am hiểu công nghệ.
- Cách ly dữ liệu theo cửa hàng và chỉ trả dữ liệu tối thiểu cho danh sách.

## 3. Ngoài phạm vi

- Không sửa, hủy, hoàn tiền hoặc thay đổi đơn cũ.
- Không xuất Excel, tính tổng doanh thu, biểu đồ hoặc báo cáo quản trị.
- Không chọn khoảng ngày tùy ý trong R1.
- Không đồng bộ hoặc lưu mới lịch sử hóa đơn để dùng ngoại tuyến.
- Không thêm bảng, migration, dependency frontend hoặc framework UI.
- Không bật Gemini, server TTS, billing hoặc deployment.

## 4. Quyết định sản phẩm đã duyệt

1. Mọi người dùng có quyền `SALE` được xem các đơn `PAID` và `DEBT` đã hoàn
   tất trong cửa hàng hiện tại, không giới hạn theo người tạo đơn.
2. Mặc định hiển thị 20 đơn mới nhất hôm nay; có nút `7 ngày`.
3. Một ô tìm kiếm chung nhận mã đơn, tên khách hoặc số điện thoại. Khi có từ
   khóa, tìm kiếm chạy trên toàn bộ lịch sử của cửa hàng.
4. Điểm vào là nút `Lịch sử đơn` ngay trên POS; bảng mở phủ lên POS và không
   chuyển route.
5. Danh sách dùng thẻ tóm tắt. Bấm thẻ mới tải chi tiết sản phẩm.
6. Đơn cũ chỉ có ba hành động: in lại, gửi lại hóa đơn cố định và đóng.
7. Phân trang bằng nút `Xem thêm 20 đơn`, không dùng cuộn vô hạn.
8. Phương án kỹ thuật là API lịch sử riêng cho POS với quyền `SALE`; không tái
   sử dụng hoặc nới quyền API dashboard.

## 5. Kiến trúc và hợp đồng API

### 5.1 Endpoint danh sách

Thêm endpoint chỉ đọc:

`GET /api/orders/{shop_id}/history`

Tham số query:

- `scope`: `today` mặc định hoặc `7d`; giá trị khác bị từ chối.
- `q`: từ khóa tùy chọn, trim khoảng trắng và giới hạn độ dài ở server.
- `page`: số trang bắt đầu từ 1; kích thước trang cố định là 20.

Khi `q` rỗng, `scope` quyết định khoảng ngày. `today` và `7d` dùng ngày địa
phương của cửa hàng theo quy ước hiện tại của hệ thống (UTC+7), không dùng ngày
UTC thô. Khi `q` có nội dung, server bỏ giới hạn `scope` và UI phải ghi rõ
`Đang tìm trong toàn bộ lịch sử`.

Tìm kiếm là xác định, không dùng AI:

- Chuỗi số nguyên dương khớp chính xác `Order.id`.
- Tên khách khớp chuỗi con, không phân biệt hoa thường.
- Số điện thoại khớp chuỗi số người dùng nhập.
- Ký tự wildcard do người dùng nhập được coi là ký tự thường, không làm thay
  đổi cú pháp truy vấn.

Truy vấn luôn lọc `shop_id` và chỉ nhận trạng thái `PAID`, `DEBT`, sắp xếp
`created_at DESC, id DESC`. `PENDING`, `UNRECONCILED`, `CANCELLED` và trạng thái
khác không xuất hiện.

Response tối thiểu:

```json
{
  "orders": [
    {
      "id": 128,
      "created_at": "2026-08-30T03:15:00Z",
      "status": "PAID",
      "payment_method": "cash",
      "total_amount": 125000,
      "customer_name": "Cô Lan",
      "customer_phone_masked": "077 *** 7057"
    }
  ],
  "page": 1,
  "per_page": 20,
  "has_more": true,
  "searching_all_history": false
}
```

Không trả số điện thoại đầy đủ, dòng hàng, doanh thu tổng, giá vốn, lãi hoặc dữ
liệu đối soát trong endpoint danh sách.

### 5.2 Quyền và phạm vi thuê bao

Service phải gọi cả `require_shop_access` và
`require_staff_permission(..., PERMISSION_SALE)` trước khi truy vấn. `shop_id`
không được tin chỉ vì frontend đang chọn cửa hàng đó. ADMIN tuân theo cơ chế
truy cập hiện có; STAFF chỉ xem shop được gán và phải có quyền `SALE`.

Tìm hóa đơn để phục vụ khách là thao tác vận hành, không phải báo cáo. Vì luồng
tìm trực tiếp theo mã đơn hiện đã đọc được đơn cũ, R1 tiếp tục cho phép tìm hóa
đơn toàn lịch sử mà không biến nó thành lối vòng qua tính năng Pro: không tổng
hợp, không export, không khoảng ngày tùy ý và không cấp quyền `REPORT`.

### 5.3 Chi tiết và hóa đơn

Không tạo hợp đồng chi tiết mới. Khi chọn một thẻ, frontend gọi endpoint hiện
có `GET /api/orders/{order_id}/detail`; endpoint này đã kiểm tra quyền `SALE`
và quyền truy cập shop. Frontend vẫn xác nhận `detail.shop_id` trùng cửa hàng
đang chọn và trạng thái là `PAID` hoặc `DEBT` trước khi dựng hóa đơn.

Dòng hàng và giá lấy từ ảnh chụp `OrderItem`, không tra giá sản phẩm hiện tại.
Hóa đơn cũ được đánh dấu bản sao và dùng lại bộ dựng/in/chia sẻ ảnh hiện có.
Nhân viên không có hành động sửa nội dung; quyền sao chép văn bản hiện có không
được nới.

## 6. Thiết kế trải nghiệm

### 6.1 Điểm vào và khung

Nút `Tìm hóa đơn` hiện tại được nâng thành `Lịch sử đơn`, không tạo thêm một
nút trùng chức năng. Trên desktop, bảng lịch sử là modal lớn phủ trên POS. Trên
mobile, bảng chiếm toàn màn hình. Nút `Đóng` luôn nhìn thấy, Escape đóng được
trên desktop và focus được trả về nút mở sau khi đóng.

### 6.2 Thanh tìm và bộ lọc

- Ô tìm: `Tìm mã đơn, tên khách hoặc số điện thoại`.
- Có nút `Tìm` rõ ràng; Enter cũng gửi. Không tự gọi API khi còn đang gõ.
- Hai lựa chọn nhanh: `Hôm nay`, `7 ngày`; trạng thái đang chọn không chỉ thể
  hiện bằng màu.
- Khi tìm kiếm, ẩn/khóa ý nghĩa phạm vi và hiện `Đang tìm trong toàn bộ lịch
  sử` để người dùng không tưởng kết quả chỉ thuộc hôm nay.
- Xóa từ khóa đưa danh sách về phạm vi đang chọn trước đó và trang 1.

### 6.3 Thẻ đơn và chi tiết

Mỗi thẻ hiển thị ngày/giờ, mã đơn, tên khách hoặc `Khách lẻ`, điện thoại đã
che, tổng tiền, hình thức thanh toán và trạng thái. Nội dung dùng từ quen thuộc:
`Đã thanh toán`, `Ghi nợ`, `Tiền mặt`, `Chuyển khoản`; không để mã kỹ thuật là
nội dung chính.

Thẻ là một vùng bấm duy nhất. Chọn thẻ mở chi tiết gồm sản phẩm, số lượng, đơn
giá, thành tiền và tổng cộng. Cuối chi tiết có `In lại`, `Gửi hóa đơn`, `Đóng`.
`Gửi hóa đơn` dùng luồng chia sẻ ảnh cố định hiện có; nếu thiết bị không hỗ trợ,
fallback hiện có tải ảnh xuống để người dùng gửi qua Zalo.

Cuối danh sách chỉ hiện `Xem thêm 20 đơn` khi `has_more=true`. Tải thêm nối kết
quả vào dưới danh sách và không làm đổi vị trí cuộn.

## 7. State inventory và phục hồi

| Trạng thái | Nội dung | Hành động phục hồi |
| --- | --- | --- |
| Tải đầu | Skeleton có hình dạng thẻ đơn | Có thể đóng bảng |
| Không có đơn hôm nay | `Hôm nay chưa có đơn nào` | `Xem 7 ngày gần đây` |
| Không có kết quả tìm | `Không tìm thấy đơn phù hợp` | `Xóa tìm kiếm` |
| Tải thêm | Giữ danh sách cũ; nút thành `Đang tải…` | Chờ hoặc đóng |
| Mất mạng/timeout | `Không tải được lịch sử. Kiểm tra mạng rồi thử lại.` | `Thử lại` |
| Mất mạng sau khi có dữ liệu | Giữ dữ liệu đang xem, báo chưa làm mới | `Thử lại` |
| Hết phiên | `Phiên làm việc đã hết hạn` | Đi tới đăng nhập |
| Mất quyền SALE | Không hiển thị dữ liệu mới | Liên hệ chủ cửa hàng |
| In/chia sẻ lỗi | Giữ hóa đơn trên màn hình | Thử lại hoặc tải ảnh |

Mỗi request danh sách/chi tiết có request token. Kết quả cũ bị bỏ nếu người
dùng đổi shop, đổi bộ lọc, tìm từ khóa khác hoặc đóng bảng. Nút tìm, xem thêm,
in và chia sẻ bị khóa trong đúng lúc thao tác tương ứng đang chạy để ngăn bấm
lặp. Tải thêm lỗi không xóa các trang đã tải.

Không tạo cache ngoại tuyến mới cho lịch sử nhạy cảm. Lỗi hiển thị thông điệp
hành động được, không lộ stack trace, SQL hoặc mã nội bộ.

## 8. Khả dụng và nội dung

- Vùng bấm tối thiểu 44px; input tối thiểu 16px trên mobile.
- Modal có nhãn, trap focus hợp lý, đóng bằng bàn phím và khôi phục focus.
- Loading/error dùng `aria-live`; trạng thái không chỉ dựa vào màu sắc.
- Tên dài được rút gọn ở thẻ nhưng có thể đọc đầy đủ trong chi tiết.
- Tiền hiển thị theo định dạng Việt Nam, ví dụ `125.000 ₫`.
- Màn 320px, phóng to 200% và reduced motion không tràn ngang hoặc mất CTA.
- Tất cả chuỗi mới có tiếng Việt và tiếng Anh; tiếng Việt là nội dung chính.

## 9. Tiêu chí chấp nhận và kiểm thử

### 9.1 Backend

- Người có `SALE` xem được 20 đơn `PAID`/`DEBT` mới nhất của đúng shop.
- Thiếu `SALE`, sai shop hoặc đổi `shop_id` bị từ chối mà không lộ dữ liệu.
- `today` và `7d` đúng ranh giới ngày UTC+7; thứ tự ổn định khi trùng thời gian.
- Trang kế tiếp không lặp hoặc bỏ đơn trong tập dữ liệu không đổi.
- Tìm đúng ID, tên và điện thoại; từ khóa rỗng và ký tự wildcard an toàn.
- Tìm kiếm không trả đơn shop khác hoặc trạng thái chưa hoàn tất.
- Response danh sách che điện thoại và không chứa trường báo cáo nhạy cảm.

### 9.2 Frontend contract

- Nút hiện có trở thành `Lịch sử đơn`; không có hai luồng tìm hóa đơn cạnh nhau.
- Mở/đóng, Hôm nay, 7 ngày, Tìm, xóa tìm và Xem thêm hoạt động đúng.
- Đổi shop/lọc/tìm nhanh không để response cũ ghi đè màn hình mới.
- Bấm thẻ dùng endpoint detail hiện có và chỉ dựng hóa đơn `PAID`/`DEBT` đúng shop.
- In/chia sẻ dùng dữ liệu server; STAFF không được mở lại sao chép văn bản.
- Mọi trạng thái ở mục 7 có copy và đường phục hồi Việt/Anh.

### 9.3 Regression và browser QA

- Chạy test order authorization, POS, receipt actions/lookup, i18n và auth.
- Browser smoke với owner và STAFF có/không có `SALE`, hai shop khác nhau, đơn
  PAID, DEBT và trạng thái bị loại.
- Kiểm tra mobile, keyboard, 200% zoom, mất mạng, timeout, bấm lặp và đổi shop
  khi request đang chạy.
- Xác nhận bán đơn mới, tồn kho và hóa đơn R2 hiện tại không bị ảnh hưởng.

## 10. Ranh giới triển khai

R1 chỉ triển khai và kiểm thử local. Không deploy, bật billing hoặc thay đổi
provider. `GEMINI_ENABLED=false` và `TTS_SERVER_ENABLED=false` phải tiếp tục
được kiểm tra trong vòng regression phù hợp.

Không còn quyết định sản phẩm mở trong phạm vi đặc tả này.
