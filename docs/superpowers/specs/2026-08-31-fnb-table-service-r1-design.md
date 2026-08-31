# F&B Table Service R1 — Đặc tả thiết kế

Ngày: 2026-08-31

Trạng thái: Các quyết định sản phẩm đã được khách hàng duyệt trong hội thoại;
tài liệu chính thức đang chờ khách hàng đọc và xác nhận trước khi lập kế hoạch
triển khai.

## 1. Bối cảnh

F-Selling hiện là POS bán lẻ: người dùng chọn hàng rồi tạo `Order`; service tạo
đơn đồng thời xử lý tồn kho, giá vốn, ca bán hàng và trạng thái thanh toán. Mô
hình này phù hợp bán tại quầy nhưng không thể đại diện an toàn cho một bàn đang
phục vụ trong nhiều giờ, gọi thêm nhiều đợt và thanh toán thành nhiều bill.

Các sản phẩm F&B được khảo sát đều đặt một lớp order/bill đang mở trước hóa đơn
thanh toán cuối. Sapo FnB dùng luồng chọn bàn, lưu order, gửi bếp, phục vụ rồi
thanh toán; KiotViet, MISA CUKCUK và iPOS đều có chuyển/gộp bàn, phiếu bếp và
tách bill. Square gọi khái niệm trung tâm này là `open ticket` và chỉ cho tách,
gộp khi ticket còn mở.

R1 bổ sung chế độ phục vụ tại bàn nhưng giữ nguyên hành vi POS bán lẻ. Hệ thống
phải phù hợp quán ăn/quán nhậu nhỏ, nhiều nhân viên dùng điện thoại hoặc tablet,
chủ quán ít am hiểu công nghệ và cần kiểm soát thất thoát.

## 2. Mục tiêu

- Cho shop bật chế độ `Bán tại bàn` mà không làm thay đổi `Bán tại quầy`.
- Quản lý khu vực, bàn và một phiên phục vụ kéo dài qua nhiều lần gọi món.
- Đồng bộ một bàn giữa nhiều thiết bị mà không mất món hoặc ghi đè im lặng.
- Tự chuyển món đến đúng màn hình Bếp hoặc Bar và trừ tồn đúng một lần.
- Phân biệt phiếu tạm tính với hóa đơn thanh toán cuối.
- Cho thanh toán toàn bàn hoặc tách bill bằng món và số lượng.
- Dùng lại thanh toán, ca, khách hàng, voucher, điểm, lịch sử và hóa đơn hiện có
  ở ranh giới phù hợp.
- Lưu vết mọi thao tác nhạy cảm và cho quản lý duyệt ngay bằng PIN riêng.
- Tạo nền tảng xác định để sau này trợ lý AI có thể đề xuất thao tác; R1 không
  phụ thuộc AI.

## 3. Ngoài phạm vi R1

- Máy in bếp và định tuyến nhiều máy in.
- Công thức/định lượng nguyên liệu và trừ kho theo công thức.
- Topping, combo, món theo cân hoặc giá thời điểm.
- Chia đều bill theo số người, theo ghế hoặc một bill dùng nhiều phương thức.
- Đặt bàn, đặt cọc, giao hàng, FoodApp và QR khách tự gọi món.
- Hóa đơn điện tử, VAT tự động hoặc tích hợp cơ quan thuế.
- KDS nâng cao như course, ưu tiên, SLA chế biến hoặc dự đoán thời gian.
- Chế độ offline nhiều thiết bị. R1 bảo toàn draft chưa gửi trên thiết bị và
  phục hồi request idempotent, nhưng không cho xác nhận bếp hoặc thanh toán khi
  server không phản hồi.
- Bật Gemini, server TTS, billing, deployment hoặc provider khác.

## 4. Quyết định sản phẩm đã duyệt

1. Ưu tiên quán ăn/quán nhậu phục vụ tại bàn; bán nhanh tại quầy tiếp tục dùng
   POS hiện có.
2. Nhiều nhân viên được dùng nhiều thiết bị cùng lúc.
3. R1 có màn hình Bếp và Bar trên điện thoại/tablet, không có máy in bếp.
4. Mỗi món được gán `Bếp`, `Bar` hoặc `Không gửi`; người phục vụ không chọn lại
   nơi nhận ở mỗi lần order.
5. Tồn thành phẩm bị trừ khi món được gửi, không chờ đến lúc thanh toán.
6. Khách có thể thanh toán toàn bàn hoặc tách bill bằng món và số lượng.
7. Có giảm giá bill và phụ thu/phí phục vụ theo phần trăm hoặc số tiền.
8. Hủy món đã gửi, hoàn tồn, giảm giá vượt ngưỡng và mở lại bill cần PIN quản
   lý. PIN được nhập ngay trên thiết bị nhân viên, không đổi tài khoản.
9. UI dùng khu vực + lưới bàn đơn giản; không có trình kéo-thả sơ đồ trong R1.
10. Thứ tự giao hàng là R1A Bàn/Phiên phục vụ, R1B Bếp-Bar/Tồn kho, R1C
    Tạm tính/Tách bill/Thanh toán. Mỗi mốc có demo và gate riêng.

## 5. Thuật ngữ và ranh giới nghiệp vụ

- **Phiên phục vụ (`ServiceSession`)**: lần phục vụ một nhóm khách từ lúc mở
  bàn đến khi mọi bill được tất toán và bàn đóng.
- **Dòng món (`SessionLine`)**: một lần thêm món với ảnh chụp tên, giá, ghi chú,
  trạm chế biến và số lượng. Hai dòng cùng sản phẩm nhưng khác ghi chú không
  được tự gộp.
- **Phiếu chế biến (`KitchenTicket`)**: ảnh chụp bất biến của một lần `Gửi
  Bếp/Bar`; retry cùng operation ID không tạo phiếu mới.
- **Bill (`ServiceCheck`)**: phần tiền phải thanh toán. Phiên luôn có bill chính;
  tách bill chuyển lượng món đã chọn sang bill phụ, không sao chép món.
- **Phiếu tạm tính**: nội dung kiểm tra trước thanh toán, phải mang nhãn lớn
  `TẠM TÍNH — CHƯA THANH TOÁN` và không được trình bày như hóa đơn đã thu tiền.
- **Order**: chứng từ bán hàng cuối hiện có. Một bill đã tất toán tạo đúng một
  Order; một phiên có thể tạo nhiều Order do tách bill.
- **Đã tất toán**: bill `PAID` hoặc `DEBT` theo ngữ nghĩa hiện có. Bill chuyển
  khoản chưa được xác nhận vẫn là `PAYMENT_PENDING` và chưa cho đóng bàn.

## 6. Kiến trúc tổng thể

Phương án đã duyệt là thêm lớp F&B trong cùng ứng dụng và dùng lại các module
hiện có tại ranh giới thanh toán:

```text
Khu vực/Bàn
    -> Phiên phục vụ
        -> Dòng món
            -> Phiếu Bếp/Bar + phân bổ tồn
        -> Một hoặc nhiều Bill
            -> Order + OrderItem + Payment hiện có
```

Không mở rộng `Order` thành bill đang phục vụ. `Order` tiếp tục là chứng từ bán
hàng có trạng thái tiền và tồn kho nghiêm ngặt. Mọi route POS bán lẻ tiếp tục
đi qua service hiện tại mà không biết đến F&B.

Shop có cờ `fnb_enabled`, mặc định `false`. Khi tắt, route và điều hướng F&B
không xuất hiện; dữ liệu lịch sử vẫn được giữ, không bị xóa.

## 7. Mô hình dữ liệu

Tên bảng có thể được điều chỉnh theo convention hiện có trong kế hoạch, nhưng
hợp đồng và invariant dưới đây là bắt buộc.

### 7.1 Khu vực và bàn

`fnb_areas`:

- `id`, `shop_id`, `name`, `sort_order`, `active`, timestamps.
- Tên duy nhất trong phạm vi shop sau khi trim/canonicalize.

`fnb_tables`:

- `id`, `shop_id`, `area_id`, `name`, `sort_order`, `active`, `state_version`.
- Tên duy nhất trong một khu vực.
- Không xóa vật lý bàn đã từng có phiên; chỉ chuyển `active=false`.

`fnb_session_tables`:

- Liên kết nhiều-nhiều giữa phiên và bàn để hỗ trợ gộp bàn.
- Một bàn chỉ thuộc tối đa một phiên chưa đóng tại một thời điểm; DB phải có
  invariant/lock tương ứng, không dựa vào kiểm tra frontend.

### 7.2 Phiên phục vụ và dòng món

`fnb_service_sessions`:

- `id`, `shop_id`, `status`, `revision`, `opened_by_user_id`, `opened_at`,
  `closed_by_user_id`, `closed_at`, `operation_id` mở phiên.
- Trạng thái: `OPEN`, `PARTIALLY_SETTLED`, `PAYMENT_PENDING`, `CLOSED`,
  `CANCELLED`.
- Mọi mutation thành công tăng `revision` trong cùng transaction.

`fnb_session_lines`:

- `id`, `session_id`, `product_id`, ảnh chụp `product_name`, `unit_price_vnd`,
  `station`, `note`, `quantity`, `cancelled_quantity`, `created_by_user_id`,
  `created_at`, `state_version`.
- `station`: `KITCHEN`, `BAR`, `DIRECT`.
- Giá, station và ghi chú của phần đã gửi không được sửa tại chỗ. Thay đổi phải
  hủy lượng cũ và thêm dòng/lượng mới để audit và tồn kho không nhập nhằng.

### 7.3 Phiếu Bếp/Bar và trạng thái chế biến

`fnb_kitchen_tickets`:

- `id`, `shop_id`, `session_id`, `station`, `sequence`, `status`,
  `operation_id`, `created_by_user_id`, timestamps.
- `operation_id` duy nhất theo shop và purpose.
- Trạng thái: `NEW`, `IN_PROGRESS`, `DONE`, `CANCELLED`.

`fnb_kitchen_ticket_items`:

- `ticket_id`, `session_line_id`, `quantity`, ảnh chụp tên/ghi chú.
- Một lần gửi tạo tối đa một ticket cho Bếp và một ticket cho Bar. `DIRECT`
  không sinh ticket nhưng vẫn thực hiện phân bổ tồn.
- `Báo hết món` là một event có lý do/trạng thái riêng; không tự xóa món và
  không tự hoàn tồn.

### 7.4 Phân bổ tồn và giá vốn

Không được gọi `create_order` hiện tại theo cách làm trừ tồn lần hai.

`fnb_stock_allocations` ghi nguồn tồn bất biến khi gửi món:

- `session_line_id`, `ticket_item_id` nullable với `DIRECT`, `product_id`,
  `batch_id`, `quantity`, phần giá vốn đã biết/chưa biết, `cost_basis_vnd`,
  `state`, `operation_id`.
- `state`: `CONSUMED`, `RESTOCKED`, `TRANSFERRED_TO_ORDER`, `WASTE`.

Khi gửi món, service khóa sản phẩm/lô, phân bổ theo quy tắc tồn hiện có, trừ
Product và batch đúng một lần, rồi tạo allocation trong cùng transaction.

Khi hủy:

- Chưa `IN_PROGRESS`: mặc định hoàn đúng allocation nguồn; retry không hoàn hai
  lần.
- `IN_PROGRESS` hoặc `DONE`: cần PIN và lựa chọn `Hoàn tồn` hay `Không hoàn`.
- `Không hoàn` chuyển allocation thành `WASTE` và lưu lý do; món bị hủy không
  được tính tiền nhưng hao hụt vẫn còn bằng chứng.

Khi thanh toán, allocation của lượng món thuộc check được chuyển thành
`OrderItemBatch`/cost provenance tương ứng mà không thay đổi tồn lần nữa. Nếu
một dòng bị chia cho nhiều check, service chia lượng và cost basis theo thứ tự
allocation ổn định; tổng các phần phải bằng allocation nguồn.

### 7.5 Bill và phân bổ món

`fnb_service_checks`:

- `id`, `session_id`, `label`, `status`, `revision`, `order_id`,
  `discount_kind/value`, `service_charge_kind/value`, `total_vnd`, timestamps.
- Trạng thái: `OPEN`, `PAYING`, `PAYMENT_PENDING`, `PAID`, `DEBT`, `CANCELLED`.
- `order_id` nullable cho đến khi tạo chứng từ cuối và không được đổi sang
  Order khác sau khi gắn.

`fnb_check_lines`:

- `check_id`, `session_line_id`, `quantity`.
- Tổng lượng đang phân bổ qua các check không vượt lượng billable của dòng.
- Bill chính giữ phần còn lại. Tách bill là thao tác chuyển lượng trong một
  transaction, không nhân bản dòng.

Giảm giá và phụ thu áp dụng theo từng check. Nếu người dùng tách một check đã
có giảm/phụ thu, hệ thống hiển thị preview và phân bổ giá trị theo thành tiền
dòng bằng thuật toán largest remainder hiện có; người dùng xác nhận trước khi
ghi. Voucher chỉ gắn với một check và không được sao chép sang check mới.

`fnb_action_log` là append-only, ghi shop, session, actor, action, before/after
summary, reason, manager approver và operation ID. Không ghi PIN hoặc secret.

## 8. PIN quản lý và phân quyền

Mỗi nhân viên dùng tài khoản riêng. Quyền logic tối thiểu:

- `FNB_SERVICE`: xem bàn, mở phiên, thêm và gửi món.
- `FNB_KITCHEN`/`FNB_BAR`: xem đúng queue và đổi trạng thái chế biến.
- `FNB_CHECKOUT`: tạm tính, tách check và bắt đầu thanh toán.
- `FNB_MANAGE`: chuyển/gộp bàn nhạy cảm, hủy món đã gửi, hoàn tồn, giảm giá
  vượt ngưỡng và mở lại check theo policy.

PIN quản lý là credential riêng được hash bằng cơ chế mật khẩu an toàn hiện có,
không lưu rõ và không dùng thay mật khẩu đăng nhập. API xác nhận PIN trả token
một lần, thời hạn ngắn, ràng buộc shop + actor + action + session/check +
revision. Token không dùng cho action khác hoặc sau khi dữ liệu đã đổi.

Sai PIN bị rate-limit theo shop, approver và thiết bị/request origin; UI báo số
lần còn lại theo policy nhưng không tiết lộ tài khoản quản lý nào tồn tại. Mọi
lần duyệt thành công/thất bại được audit không chứa PIN.

## 9. Hợp đồng API dự kiến

Prefix: `/api/fnb`.

Thiết lập:

- `GET/POST/PATCH /areas`
- `GET/POST/PATCH /tables`
- `PATCH /menu-items/{product_id}/station`
- `POST /manager-approvals`

Phiên phục vụ:

- `GET /floor?shop_id=...&after_revision=...`
- `POST /sessions`
- `GET /sessions/{session_id}`
- `POST /sessions/{session_id}/lines`
- `POST /sessions/{session_id}/send`
- `POST /sessions/{session_id}/move-table`
- `POST /sessions/{session_id}/merge-table`
- `POST /sessions/{session_id}/cancel-line`

Bếp/Bar:

- `GET /stations/{station}/tickets?after_revision=...`
- `POST /tickets/{ticket_id}/start`
- `POST /tickets/{ticket_id}/done`
- `POST /tickets/{ticket_id}/out-of-stock`

Bill:

- `GET /sessions/{session_id}/checks`
- `POST /checks/{check_id}/split-preview`
- `POST /checks/{check_id}/split`
- `PATCH /checks/{check_id}/adjustments`
- `GET /checks/{check_id}/provisional-receipt`
- `POST /checks/{check_id}/pay`
- `POST /sessions/{session_id}/close`

Mọi mutation nhận:

- `operation_id`: định danh retry duy nhất.
- `expected_revision`: phiên bản client đang nhìn.
- approval token khi action cần quản lý.

Sai revision trả HTTP 409 với code ổn định `FNB_SESSION_CHANGED`, revision và
snapshot tối thiểu mới nhất. Retry cùng operation ID và cùng fingerprint trả
kết quả cũ; cùng ID nhưng payload khác bị từ chối.

## 10. Đồng bộ nhiều thiết bị

R1 dùng polling HTTP khoảng 2 giây khi màn hình đang foreground, chậm lại khi
tab nền. Không thêm WebSocket. Response có revision; không đổi thì trả payload
tối thiểu/304 theo khả năng framework.

UI không dùng optimistic success cho gửi bếp, hủy món, hoàn tồn hoặc thanh
toán. Thêm draft có thể hiện ngay trên thiết bị nhưng phải mang nhãn `Chưa đồng
bộ` đến khi server xác nhận.

Mutation dựa trên `expected_revision`; service khóa phiên và tài nguyên tiền/
tồn cần thiết trong transaction. Nếu xung đột, UI giữ draft của người dùng,
tải snapshot mới và cho `Áp dụng lại` khi còn hợp lệ, không tự ghi đè.

Đổi shop, đăng xuất, đóng màn hình hoặc request mới phải làm kết quả cũ mất
quyền cập nhật UI. Server luôn kiểm shop/permission; không tin shop ID từ trạng
thái frontend.

## 11. Luồng trải nghiệm

### 11.1 Bàn

POS có hai điểm vào rõ ràng: `Bán tại quầy` và `Bán tại bàn`. Màn bàn có tab
khu vực và lưới thẻ. Mỗi thẻ hiện tên bàn, trạng thái bằng chữ + màu, thời gian
phục vụ, tổng tạm tính và dấu món mới/chờ thanh toán khi có.

Trạng thái người dùng thấy: `Trống`, `Đang phục vụ`, `Có món mới`, `Chờ tính
tiền`, `Còn bill chưa trả`. Không hiển thị enum kỹ thuật.

### 11.2 Gọi món

Màn gọi món dùng lại ngôn ngữ và bố cục POS: menu bên trái, bill bàn bên phải.
Món mới nằm ở `Chưa gửi`; CTA duy nhất là `Gửi Bếp/Bar`. Sau khi server xác
nhận, món chuyển sang khu đã gửi với trạng thái Bếp/Bar.

Không cho sửa giá/ghi chú/số lượng của phần đã gửi. Nhân viên hủy lượng cũ rồi
thêm lượng đúng. Nút hủy giải thích rõ tác động tồn và có luồng PIN khi cần.

### 11.3 Bếp và Bar

Hai route/view lọc station. Mỗi ticket hiện bàn, thời gian chờ, món, lượng, ghi
chú và người gửi. CTA lớn: `Nhận làm`, `Xong`, `Báo hết món`. Thiết bị Bar không
thấy món Bếp và ngược lại, trừ người có quyền quản lý chọn xem tất cả.

### 11.4 Tạm tính, tách bill và thanh toán

Luồng: `Tạm tính -> khách kiểm tra -> Tách bill nếu cần -> Thanh toán`.

Tách bill cho phép chọn dòng và số lượng nguyên. Preview luôn hiện bill nguồn,
bill mới, giảm giá, phụ thu và tổng sau phân bổ trước khi xác nhận.

Thanh toán gọi orchestration F&B riêng để tạo Order/payment và chuyển provenance
tồn, không gọi mù luồng bán lẻ làm trừ tồn lại. Cash và debt có thể tất toán
ngay theo contract hiện có. Transfer giữ check/bàn ở `PAYMENT_PENDING` đến khi
server xác nhận trạng thái phù hợp.

Chỉ khi mọi check là `PAID`, `DEBT` hoặc `CANCELLED` hợp lệ thì `Đóng bàn` mới
bật. Đóng thành công giải phóng toàn bộ bàn trong phiên.

## 12. State inventory và phục hồi

| Tình huống | Người dùng thấy | Phục hồi/quy tắc |
| --- | --- | --- |
| Shop chưa có bàn | `Chưa có bàn` và CTA `Tạo khu vực đầu tiên` | Chỉ owner/manager thiết lập |
| Bàn trống | Tên bàn + `Trống` | Mở phiên hoặc quay lại |
| Phiên chưa có món | `Bàn chưa gọi món` | Thêm món hoặc đóng phiên rỗng |
| Draft chưa sync | Nhãn `Chưa đồng bộ` trên đúng dòng | Tự retry; giữ draft khi reload cục bộ |
| Gửi bếp timeout | Không đổi sang `Đã gửi` | `Thử lại`; dùng cùng operation ID |
| Bếp/Bar mất kết nối | `Bếp chưa nhận phiếu` | Không giả thành công; retry/kiểm tra thiết bị |
| Hai người cùng sửa | `Bàn vừa được cập nhật bởi ...` | Tải mới, giữ draft, áp dụng lại có kiểm tra |
| Hết tồn lúc gửi | Chỉ rõ món và lượng còn | Sửa lượng/báo khách; không gửi phần thất bại |
| Báo hết món | Cảnh báo đến waiter/cashier | Hủy/đổi món bằng thao tác rõ ràng |
| Hủy món đang làm | PIN + lý do + hoàn tồn/không hoàn | Audit cả quyết định và approver |
| Tách bill xung đột | Preview hết hiệu lực | Tải bill mới và tách lại |
| Thanh toán timeout | `Đang kiểm tra thanh toán` | Đọc server trước khi cho retry |
| QR chờ xác nhận | `Chờ xác nhận chuyển khoản` | Giữ bàn/check mở |
| Còn bill chưa trả | `Còn X ₫ chưa thanh toán` | Mở bill còn lại; chặn đóng bàn |
| PIN sai/khóa | Lý do và thời gian thử lại | Không mất thao tác đang soạn |
| Mất quyền/đổi shop | Đóng dữ liệu cũ, không lộ snapshot | Đăng nhập đúng quyền/chọn shop |

Không có lỗi chung chung. Mỗi lỗi nói điều gì xảy ra, dữ liệu nào được giữ và
hành động tiếp theo. Thanh toán, tồn kho và hủy món không dùng optimistic UI.

## 13. Tính tiền, làm tròn và invariant

- Mọi tiền là integer VND; client không gửi tổng đáng tin cậy.
- Server tính lại line total, giảm giá, phụ thu và tổng check.
- Giảm/phụ thu phần trăm có quy tắc làm tròn duy nhất; phân bổ dùng helper
  largest remainder hiện có để tổng dòng bằng tổng check.
- Tổng quantity trên các check cộng quantity đã hủy phải khớp quantity phiên.
- Tổng Order của các check phải bằng tổng đã tất toán của phiên theo snapshot
  điều chỉnh đã duyệt.
- Một stock allocation chỉ được `RESTOCKED`, `TRANSFERRED_TO_ORDER` hoặc
  `WASTE` một lần.
- Một check chỉ gắn một Order. Retry không tạo Order/payment/ticket thứ hai.
- Không đóng phiên khi còn draft chưa gửi, check chưa tất toán hoặc transfer
  đang chờ, trừ luồng hủy có quyền và audit riêng.

## 14. Khả dụng và nội dung

- Vùng chạm tối thiểu 44px; input tối thiểu 16px trên mobile.
- Trạng thái không chỉ dựa vào màu; mọi icon quan trọng có nhãn chữ.
- Một CTA chính mỗi màn hình: `Gửi Bếp/Bar`, `Xong`, hoặc `Thanh toán`.
- Tổng tiền và trạng thái thanh toán luôn nhìn thấy, không bị thanh sticky che.
- Màn 320px, 390px, desktop và zoom 200% không tràn ngang/mất CTA.
- Loading/error/status dùng live region phù hợp; focus quay về điểm mở sau modal.
- Tên món/ghi chú dài được wrap/truncate có đường xem đủ; không làm vỡ ticket.
- Chuỗi mới có tiếng Việt và tiếng Anh; tiếng Việt là nội dung chính.

## 15. Phân kỳ và gate

### R1A — Bàn và phiên phục vụ

- Feature flag, khu vực/bàn, sơ đồ bàn.
- Mở/chuyển/gộp phiên, draft món, revision/idempotency và polling nhiều thiết bị.
- Chưa gửi bếp, chưa trừ tồn, chưa thanh toán F&B.

Gate: ba thiết bị sửa cùng phiên không mất dữ liệu; hai request mở cùng bàn chỉ
một request thắng; POS bán lẻ không đổi.

### R1B — Bếp/Bar và tồn kho

- Station món, gửi theo đợt, queue Bếp/Bar, trạng thái chế biến.
- Phân bổ/trừ tồn khi gửi, hủy/hoàn tồn/waste và manager PIN.

Gate: retry không trùng ticket/trừ tồn; station isolation; hủy ở mọi trạng thái
giữ đúng stock/cost/audit.

### R1C — Tạm tính, tách bill và thanh toán

- Check chính/phụ, split preview, giảm/phụ thu, phiếu tạm tính.
- Orchestration tạo Order/payment không trừ tồn hai lần; đóng phiên/bàn.

Gate: tổng check bảo toàn; split/payment retry an toàn; mọi phương thức hiện có
đúng contract; không đóng bàn còn tiền.

## 16. Tiêu chí chấp nhận và kiểm thử

### 16.1 Dữ liệu, tenant và quyền

- Shop khác không xem/sửa được khu vực, bàn, phiên, ticket, check hoặc audit.
- User thiếu quyền bị từ chối trước mutation; approval token bị ràng buộc đúng
  actor/shop/action/entity/revision.
- PIN không xuất hiện trong log, response, DB rõ hoặc telemetry.
- Bàn không thể thuộc hai phiên mở dù hai request chạy đồng thời.

### 16.2 Đồng bộ và idempotency

- Ba client thêm món, gửi bếp và mở check cùng phiên mà không mất update.
- Stale revision trả 409 ổn định và không mutation một phần.
- Retry cùng operation/fingerprint trả kết quả cũ; payload khác bị từ chối.
- Response đến muộn sau đổi shop/đóng màn hình không ghi lên UI mới.

### 16.3 Bếp/Bar và tồn kho

- Ticket chỉ chứa đúng station, snapshot món/lượng/ghi chú và đúng bàn.
- Một lần gửi trừ Product/batch/cost đúng một lần; payment không trừ lần nữa.
- Hủy trước/sau `IN_PROGRESS`, có/không hoàn tồn tạo đúng provenance và audit.
- Hết hàng giữa hai thiết bị không làm âm tồn hoặc gửi ticket không có nguồn.

### 16.4 Bill và thanh toán

- Split theo dòng/lượng không trùng hoặc bỏ lượng; preview stale bị từ chối.
- Giảm/phụ thu và phân bổ làm tròn bảo toàn tổng VND.
- Cash, transfer, debt, voucher và loyalty tuân theo contract hiện có.
- Transfer timeout/retry không thu hai lần; pending không giải phóng bàn.
- Phiếu tạm tính không có dấu hiệu `đã thanh toán`; hóa đơn cuối lấy dữ liệu
  server và không cho nhân viên sửa nội dung chia sẻ.

### 16.5 Browser và resilience QA

- Owner, phục vụ, Bếp, Bar, thu ngân và user thiếu quyền.
- Desktop, tablet, 390x844, 320px, keyboard, zoom 200%, reduced motion.
- Mất kết nối khi draft, gửi bếp, đổi trạng thái, split và thanh toán.
- Double-click, hai tab, hai thiết bị, request đảo thứ tự, phiên hết hạn.
- 0/1/50 bàn, bàn tên dài, 0/1/100 dòng món và ghi chú dài.
- Xác nhận POS bán lẻ, ca, order, receipt, QR, offline retail, return và sales
  history không hồi quy.

## 17. Ranh giới vận hành

R1 chỉ triển khai và kiểm thử local cho đến khi có phê duyệt riêng về deploy.
`GEMINI_ENABLED=false` và `TTS_SERVER_ENABLED=false` tiếp tục là gate. Không có
provider call, billing change hoặc dữ liệu khách thật trong demo/UAT.

Demo dùng dữ liệu giả cho quán nhậu: ít nhất hai khu vực, mười bàn, menu có món
Bếp/Bar/Direct, hai nhân viên phục vụ, một Bếp, một Bar, một thu ngân và một
quản lý có PIN.

## 18. Cơ sở nghiên cứu

- Sapo FnB — tạo hóa đơn: https://help.sapo.vn/huong-dan-tao-hoa-don-ban-hang-tren-sapo-fnb
- Sapo FnB — thiết lập bán hàng: https://help.sapo.vn/thiet-lap-ban-hang-tai-cua-hang-fnb
- Sapo FnB — tạm tính/thanh toán: https://help.sapo.vn/huong-dan-thanh-toan-hoa-don-fnb
- KiotViet F&B: https://www.kiotviet.vn/bar-cafe-nha-hang
- MISA CUKCUK: https://www.cukcuk.vn/ld/cukcuk-misa
- iPOS FABi: https://huongdan.ipos.vn/docs/bang-tinh-nang-phan-mem-ipos-vn/tinh-nang-phan-mem-fabi/
- Square open tickets: https://squareup.com/help/us/en/article/8439-split-and-merge-open-tickets

Không còn quyết định sản phẩm mở trong phạm vi tài liệu này. Mọi yêu cầu ngoài
phạm vi phải được phân loại thành R1.x hoặc R2 và được duyệt trước khi triển khai.
