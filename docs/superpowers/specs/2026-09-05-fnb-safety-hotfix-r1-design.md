# F&B Safety Hotfix R1 — Design Specification

Ngày: 2026-09-05

Trạng thái: Đã duyệt hướng thiết kế; chưa triển khai
Phạm vi: F1 — xác nhận tiền mặt có chủ đích; F2 — phục hồi đúng luồng hủy món đang làm

## 1. Mục tiêu

Loại bỏ hai đường vận hành có thể làm người dùng hiểu sai trạng thái hệ thống:

1. Một bill tiền mặt không được chuyển sang `PAID` nếu thu ngân chưa khai báo rõ số tiền thực nhận.
2. Một yêu cầu hủy món đang làm phải dẫn người dùng tới quyết định tồn kho, lý do và phê duyệt; lỗi nghiệp vụ không được giả thành lỗi đồng bộ hoặc để phiên bị khóa thao tác.

Hotfix phải giữ nguyên các bảo vệ hiện có về operation ID, revision, khóa shop, tồn kho theo allocation, voucher, điểm, ca tiền và manager approval.

## 2. Phạm vi không thực hiện

R1 không:

- thêm migration hoặc thay đổi model database;
- thêm endpoint thanh toán, endpoint preview hoặc endpoint hủy món;
- thay đổi vòng đời phiếu bếp `NEW`/`IN_PROGRESS`/`DONE`;
- thêm trạng thái `READY`/`SERVED`, quy tắc đóng bàn hoặc vai trò phục vụ;
- thiết kế lại toàn bộ checkout, sơ đồ bàn hay KDS;
- xây state machine/framework mutation dùng chung;
- thay đổi Retail POS hoặc hợp đồng thanh toán Retail;
- tự động retry một thao tác hủy có revision đã thay đổi.

Những việc đó thuộc các plan sau và chỉ được thực hiện sau khi R1 đã được tích hợp, kiểm thử và UAT.

## 3. Kiến trúc thay đổi

R1 dùng đúng các biên hiện có:

- `fselling/services/fnb_service.py` là nguồn sự thật cho điều kiện ghi nhận tiền mặt và mọi mutation tài chính.
- `static/js/fnb-r1a.js` tiếp tục điều phối checkout, mutation pending, conflict và dialog phê duyệt.
- `static/fnb.html` tiếp tục chứa form thanh toán và dialog hủy món.
- `static/js/locales/fnb.js` chứa toàn bộ copy Việt/Anh mới.
- Các class CSS hiện có được tái sử dụng; chỉ bổ sung CSS cục bộ nếu class hiện tại không bố trí được nút nhập nhanh.

Không tạo module, abstraction hoặc cấu hình mới cho hai nhánh xử lý này.

## 4. Thanh toán tiền mặt có chủ đích

### 4.1 Hợp đồng request

`FnbCheckPay.cash_tendered_vnd` vẫn là field tùy chọn ở cấp schema vì field này không hợp lệ với `transfer` và `debt`. Kiểm tra conditional nằm trong `pay_check`, sau khi server đã tính tổng cuối cùng gồm:

- giảm giá bill;
- phụ thu;
- voucher;
- điểm khách hàng.

Quy tắc:

| Phương thức | `cash_tendered_vnd` | Kết quả |
|---|---:|---|
| `cash` | thiếu/null | `400 FNB_CASH_TENDERED_REQUIRED` |
| `cash` | nhỏ hơn tổng cuối | `400 FNB_CASH_SHORT` |
| `cash` | bằng/lớn hơn tổng cuối | ghi nhận thanh toán và tính tiền thừa |
| `transfer`/`debt` | có giá trị | giữ `400 FNB_CASH_TENDERED_INVALID` |
| `transfer`/`debt` | thiếu | giữ hành vi hiện tại |

Giá trị `0` là một khai báo có chủ đích và khác chuỗi trống/null. Bill có tổng cuối bằng 0 chỉ được thanh toán tiền mặt khi client gửi rõ `cash_tendered_vnd: 0`.

### 4.2 Lỗi backend mới

Khi thiếu tiền khách đưa:

```json
{
  "detail": {
    "code": "FNB_CASH_TENDERED_REQUIRED",
    "message": "Cần nhập số tiền khách đã đưa",
    "required": 100000
  }
}
```

Lỗi phải xảy ra trước khi:

- lấy hoặc ghi cash shift;
- tạo `Order`;
- tạo payment/ledger/audit của giao dịch thành công;
- tiêu voucher;
- trừ điểm hoặc cộng điểm;
- thay đổi check/session revision;
- tạo receipt.

Mọi thay đổi tạm thời trong transaction phải được rollback theo cơ chế lỗi hiện có.

### 4.3 Hành vi frontend

Form tiền mặt có:

```text
Tiền khách đưa
[________________] [Khách đưa đúng tổng bill]

[Xác nhận đã thu 120.000đ]
```

Quy tắc giao diện:

1. Chọn `cash` và để trống input: không gọi `payCheck`; hiển thị lỗi inline và focus input.
2. Nhập `0` là hợp lệ ở client; server quyết định số tiền đó có đủ hay không.
3. Nút nhập nhanh điền `activeCheck().total_vnd` đang hiển thị, chỉ khi voucher trống và điểm bằng 0.
4. Khi voucher hoặc điểm có giá trị, nút nhập nhanh bị disable và có helper text: người dùng phải nhập số tiền thực nhận sau ưu đãi. R1 không tự tính voucher/điểm ở client.
5. Khi đổi bill đang chọn, mở lại checkout, đổi phương thức, thay voucher hoặc thay điểm, giá trị tiền khách đưa phải được xem lại; không được âm thầm mang số tiền từ bill trước sang bill mới.
6. CTA tiền mặt phản ánh hành động vật lý: `Xác nhận đã thu {cash_tendered_vnd}`. Với phương thức khác, giữ copy phù hợp hiện tại.
7. Chỉ response thành công của server mới được hiển thị là đã thanh toán. Tiền thừa lấy từ response server, không lấy phép tính client làm nguồn sự thật.

### 4.4 Khả năng truy cập và thiết bị

- Nút nhập nhanh dùng `type="button"`, không submit form.
- Input tiếp tục dùng `inputmode="numeric"`, có label thật và không dựa vào placeholder.
- Lỗi inline được liên kết với input bằng `aria-describedby`; vùng lỗi dùng `aria-live="polite"`.
- Trên mobile 390 px và tablet 1024 px, input, nút nhập nhanh, số tiền và CTA không chồng lấp hoặc bị banner PWA che. Việc di chuyển banner toàn cục thuộc Plan 5; R1 chỉ xác nhận form vẫn thao tác được trong điều kiện hiện tại.
- Không dùng màu làm tín hiệu lỗi duy nhất.

## 5. Hủy món đang làm có đường phục hồi

### 5.1 Các lớp kết quả

Controller phân biệt ba lớp:

1. **Thành công:** cập nhật snapshot phiên như hiện tại.
2. **Cần hành động người dùng:**
   - `FNB_CANCELLATION_DECISION_REQUIRED`;
   - `FNB_APPROVAL_REQUIRED`.
3. **Lỗi/conflict:** revision thay đổi, quyền không hợp lệ, token hết hạn, validation khác hoặc lỗi mạng chưa biết kết quả.

Hai code “cần hành động” không phải lỗi đồng bộ và không được lưu làm `recoverableDraft`.

### 5.2 Luồng từ nút Hủy

```text
Bấm Hủy
  → gửi cancel hiện tại không kèm quyết định
  ├─ món chưa chế biến: server hủy trực tiếp như hiện tại
  └─ món IN_PROGRESS/DONE:
       server trả FNB_CANCELLATION_DECISION_REQUIRED
       → controller clear pending trước render
       → render lại phiên ở trạng thái thao tác được
       → mở dialog hiện có
       → chọn RESTOCK/WASTE + nhập lý do + tài khoản/PIN quản lý
       → lấy approval token ràng buộc shop/actor/session/revision
       → gửi cancel với đầy đủ quyết định và token
       → thành công: đóng dialog, xóa dữ liệu nhạy cảm, cập nhật snapshot
```

Dialog hiện có được tái sử dụng. R1 không thêm bước wizard hoặc dialog mới.

### 5.3 Trạng thái pending và copy

Đối với response 4xx dứt khoát, `clearPending()` phải chạy trước khi render trạng thái. Sau `FNB_CANCELLATION_DECISION_REQUIRED`, màn phiên phải ghi rõ:

```text
Chưa hủy — món vẫn đang làm. Chọn cách xử lý tồn kho và cần quản lý duyệt.
```

Không được dùng:

- `Chưa đồng bộ` cho response dứt khoát;
- badge unsynced cho yêu cầu đã bị server từ chối;
- nút retry chung cho thao tác thiếu quyết định;
- trạng thái disabled còn sót lại trên Gửi món/Tính tiền sau khi lỗi kết thúc.

### 5.4 Dialog phê duyệt

Dialog phải giữ đủ bốn dữ liệu:

- `resolution`: `RESTOCK` hoặc `WASTE`;
- `reason`: bắt buộc, sau trim không rỗng;
- `approver_username`;
- `pin`.

Quy tắc lỗi:

| Tình huống | Hành vi UI |
|---|---|
| Thiếu resolution/reason | Chặn tại dialog, focus field đầu tiên chưa hợp lệ |
| Sai tài khoản/PIN | Giữ dialog, resolution và reason; xóa PIN; báo inline |
| Approval token hết hạn/không hợp lệ | Giữ dialog; yêu cầu duyệt lại, không tự gửi cancel mới |
| Thành công | Xóa PIN, reason, pending line ID; đóng dialog |
| Người dùng đóng dialog | Không hủy món; xóa PIN và pending line ID; món giữ trạng thái server |

PIN không được ghi log, giữ trong recoverable draft hoặc local storage.

### 5.5 Conflict và retry

`cancel-line` không được đi qua cơ chế `reapply` dành cho add/update line. Nếu session hoặc line revision thay đổi:

1. nhận snapshot mới từ server;
2. clear pending;
3. không lưu cancel attempt vào `recoverableDraft`;
4. đóng dialog nếu đang mở và xóa approval token/PIN;
5. hiển thị `Món vừa thay đổi; kiểm tra lại trước khi hủy`;
6. yêu cầu người dùng khởi tạo một quyết định hủy mới từ snapshot mới.

Nếu request bị lỗi mạng và chưa biết server có nhận hay không, giữ đúng pending mutation và operation ID hiện tại. Người dùng chỉ được retry exact payload với exact operation ID; không sinh operation ID mới và không chuyển sang offline.

## 6. Tính tương thích

### 6.1 Client nội bộ

Frontend F&B hiện hành phải luôn gửi numeric `cash_tendered_vnd` cho cash. Các test cũ cố tình bỏ field này phải được đổi từ kỳ vọng `200` sang lỗi fail-closed, trừ khi test đang mô tả phương thức không phải cash.

### 6.2 Client ngoài repository

Đây là thay đổi hành vi có chủ đích: client ngoài repository đang thanh toán cash mà bỏ `cash_tendered_vnd` sẽ nhận `400 FNB_CASH_TENDERED_REQUIRED`.

Trước khi phát hành production phải kiểm tra access log/API inventory để xác nhận không có client F&B khác. Nếu có, client đó phải được cập nhật trước hoặc phát hành đồng bộ. Không thêm cờ tương thích cho hành vi không an toàn.

### 6.3 Dữ liệu

Không migration. Các order đã ghi trước R1 không bị sửa hồi tố. Báo cáo/receipt tiếp tục đọc các field cash hiện có.

## 7. File dự kiến thay đổi

| File | Trách nhiệm |
|---|---|
| `fselling/services/fnb_service.py` | Fail-closed khi cash thiếu tender; giữ thứ tự mutation an toàn |
| `static/fnb.html` | Nút nhập nhanh, vùng helper/error và liên kết accessibility |
| `static/js/fnb-r1a.js` | Validate cash; quản lý nút nhập nhanh/CTA; phân loại cancellation action; clear pending; conflict an toàn |
| `static/js/locales/fnb.js` | Copy Việt/Anh cho cash và cancellation recovery |
| `static/css/fnb-r1a.css` | Chỉ bổ sung bố cục cục bộ nếu class hiện tại không đủ |
| `tests/test_fnb_r1c_checkout.py` | Contract tiền mặt và bảo toàn side effects |
| `tests/test_fnb_r1b_cancel.py` | Quyết định, phê duyệt, conflict và tồn kho |
| `tests/js/fnb-r1a.test.js` | Controller pending/recovery và payload thanh toán |
| Test UI tĩnh F&B hiện có | ID, i18n và cấu trúc form nếu cần |

Không sửa các file Seller đang có thay đổi chưa commit trong workspace.

## 8. Chiến lược kiểm thử

### 8.1 API — cash

Phải có test cho:

- cash thiếu tender, tổng dương → `FNB_CASH_TENDERED_REQUIRED` và `required` đúng;
- cash thiếu tender, tổng bằng 0 → vẫn bị từ chối;
- cash tender `0`, tổng bằng 0 → thành công;
- cash thiếu tender với voucher/điểm → rollback toàn bộ, không tiêu quyền lợi;
- cash đủ và cash thừa → PAID, `cash_paid_amount`, `cash_tendered_amount`, `cash_change_amount` đúng;
- cash thiếu → `FNB_CASH_SHORT`, không side effect;
- transfer/debt không gửi tender vẫn giữ hành vi;
- non-cash gửi tender vẫn bị từ chối;
- retry cùng operation ID sau lost response vẫn trả durable winner, không ghi hai lần.

Side-effect assertion tối thiểu gồm số lượng order, payment/ledger, shift totals, voucher usage, loyalty events, check status và revisions.

### 8.2 API — cancellation

Phải giữ và mở rộng test cho:

- sent nhưng chưa progressed được hủy trực tiếp và hoàn đúng allocation;
- IN_PROGRESS thiếu resolution/reason → `FNB_CANCELLATION_DECISION_REQUIRED`;
- đủ decision nhưng thiếu approval → `FNB_APPROVAL_REQUIRED`;
- RESTOCK/WASTE cập nhật đúng tồn và audit;
- token ràng buộc actor/shop/session/revision, một lần dùng và có hạn;
- operation ID retry không hủy/trừ/hoàn tồn hai lần;
- stale session/line revision không consume approval và không thay đổi line;
- rollback nếu commit lỗi.

### 8.3 JavaScript/controller

Phải có test chứng minh:

- form cash trống không gọi request;
- numeric `0` được gửi nguyên vẹn;
- nút nhập nhanh điền đúng total và bị khóa khi voucher/điểm có giá trị;
- đổi bill/phương thức không mang nhầm tender;
- cancellation action-required clear pending trước render;
- action-required không tạo recoverable draft và không hiện unsynced;
- sau lỗi dứt khoát, các control phiên được enable lại;
- cancel conflict không gọi `updateLine` hoặc reapply;
- network ambiguity giữ exact pending request/operation ID.

### 8.4 Browser UAT

Chạy với database demo cô lập, provider ngoài tắt, không dùng QR/ngân hàng thật:

1. Cash blank trên desktop/tablet/mobile: không tạo order, focus đúng input.
2. Nút nhanh với bill thường: payload numeric, receipt và tiền thừa đúng.
3. Voucher/điểm: nút nhanh khóa, cash blank bị chặn, quyền lợi không bị tiêu khi lỗi.
4. Món NEW: hủy trực tiếp.
5. Món IN_PROGRESS: dialog mở, sai PIN phục hồi được, đúng PIN hủy đúng RESTOCK/WASTE.
6. Hai thiết bị cùng thay đổi line: thiết bị stale nhận snapshot, không auto-hủy hoặc update nhầm.
7. Dừng backend tại lúc cancel/pay: không báo thành công giả; retry dùng cùng operation ID.

Viewport bắt buộc: 390×844, 1024×768 và desktop tối thiểu 1366×768.

## 9. Tiêu chí nghiệm thu

R1 chỉ đạt khi đồng thời thỏa:

- Không còn đường API cash nào chuyển bill dương hoặc bằng 0 sang PAID với tender null.
- Mọi cash PAID có `cash_tendered_amount` được client khai báo rõ và server xác thực.
- Không side effect tài chính/tồn/ưu đãi khi validation thất bại.
- IN_PROGRESS cancellation mở đúng dialog từ thao tác đầu tiên.
- Người dùng luôn thấy món chưa hủy và trạng thái hiện tại khi quyết định chưa hoàn tất.
- Response 4xx dứt khoát không để pending hoặc control disabled tồn tại.
- Cancel conflict không được reapply dưới dạng update line và không tự retry destructive action.
- Operation ID/revision/approval protections hiện có vẫn qua regression.
- Test tập trung và browser UAT ở ba viewport qua.
- Git diff không chứa file ngoài phạm vi, không ghi đè năm thay đổi chưa commit của người dùng.

## 10. Phát hành và rollback

Thứ tự phát hành an toàn:

1. Xác nhận không có client F&B ngoài repository đang dựa vào cash tender null.
2. Phát hành backend và frontend cùng một release.
3. Chạy smoke test cash blank/cash đủ và cancellation IN_PROGRESS trên môi trường UAT.
4. Theo dõi số lượng `FNB_CASH_TENDERED_REQUIRED`, lỗi approval và pending mutation trong giai đoạn đầu.

Rollback phải hoàn tác trọn commit R1. Không rollback riêng frontend để tránh client cũ tiếp tục gửi payload thiếu trong khi người dùng tưởng giao diện đã xác nhận tiền. Dữ liệu không cần down migration vì R1 không thay schema.

## 11. Điều kiện chuyển sang Plan 2

Chỉ bắt đầu thiết kế chi tiết vòng đời món–bếp–phục vụ–bàn sau khi:

- R1 đã merge vào base tích hợp;
- UAT cash và cancellation đạt;
- không còn client nào bị vỡ do hợp đồng tender mới;
- test suite F&B liên quan qua trên revision đã merge;
- các quan sát UAT mới được ghi lại để Plan 2 dùng làm đầu vào.
