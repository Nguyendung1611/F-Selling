# F&B Safety Hotfix R1 — Exit Gate / UAT

Ngày kiểm tra: 2026-09-06

Baseline kiểm tra: `d4e99a2b457030ba6c54bb74faf1378891467913` (`fix: invalidate stale cancellation approvals`)

Kết luận: **PASS trong phạm vi Safety Hotfix R1, với giới hạn bằng chứng được ghi bên dưới**

## Safety Hotfix R1

- Cash checkout từ chối tender trống trước khi tạo order hoặc thay đổi check,
  shift, voucher, loyalty, allocation hay receipt.
- Số `0` vẫn là dữ liệu nhập rõ ràng và chỉ thành công nếu đủ thanh toán tổng
  tiền cuối cùng.
- Hủy món đang chế biến mở lại đúng dialog quyết định tồn kho và duyệt quản lý,
  không để service session mắc ở trạng thái pending.
- Xung đột hủy tải snapshot mới, đóng/xóa dialog và buộc người dùng quyết định
  lại; không đổi thành cập nhật line và không tự hủy.
- Kết quả mạng không rõ không hiển thị thành công giả. Controller giữ nguyên
  request body và operation ID cho retry; backend replay/collision bảo vệ tính
  idempotent.

Không deploy, không dùng dữ liệu thật, không bật payment/provider. Hai biến
`GEMINI_ENABLED` và `TTS_SERVER_ENABLED` đều absent trước runtime và không bị
set, clear hay thay đổi trong quá trình UAT.

## Bằng chứng tự động

Focused gate tại working tree cuối:

```text
node --check static/js/fnb-r1a.js                         exit 0
node --check static/js/locales/fnb.js                    exit 0
node tests/js/fnb-r1a.test.js                            fnb-r1a controller ok; exit 0
pytest checkout/cancel/UI                                27 passed, 1 warning in 28.03s
```

Broader F&B/shared-money regression gồm 12 file:

```text
115 passed, 1 warning in 151.95s (0:02:31); exit 0
```

Cảnh báo duy nhất ở hai nhóm pytest là `StarletteDeprecationWarning` từ
`fastapi.testclient`; không có skipped failure.

Full repository suite được chủ dự án chạy bằng:

```powershell
.\test-commit.ps1 -TestOnly
```

Người chạy xác nhận PASS rồi commit. Dòng tổng kết passed/skipped/warning không
được lưu và chủ dự án chỉ định bỏ qua số đếm; báo cáo không suy diễn từ lần
chạy cũ và Codex không chạy lại full suite.

`git diff --check` exit 0, chỉ có thông báo LF/CRLF hiện hữu trên Windows.
Secret scan trả `SECRET_SCAN_CLEAR`. Không có thay đổi chưa commit khi bắt đầu
ghi báo cáo.

## UAT checkout tiền mặt

Ma trận hành vi tiền mặt chạy tại 390×844 trên runtime/database giả cô lập.
Checkout sau đó được kiểm tra lại về hiển thị/control tại 1024×768 và
1366×768; hai viewport lớn không lặp lại toàn bộ mutation tài chính:

- Tender trống focus đúng input, hiện lỗi inline, không có success; snapshot
  order/check/shift/voucher/loyalty/allocation/receipt không đổi.
- Tender `0` và tender thiếu trả short-cash, controls được bật lại, không có
  side effect.
- Nút tiền đủ điền đúng 4.500đ; order `92` ghi total/tender 4.500đ, change 0.
- Order `93` ghi total 12.000đ, tender 20.000đ, change 8.000đ.
- Voucher `CHAOBANMOI` làm vô hiệu nút tiền đủ và đổi helper. Các ca thiếu tiền
  có voucher/điểm giữ nguyên usage và số dư loyalty.
- Transfer trên session/check `8` tạo order `96` ở `PENDING`, không tạo payment
  hay thay shift. Debt trên session/check `9` thiếu customer bị từ chối; có
  customer tạo order `97` ở `DEBT`, vẫn không tạo payment hay thay shift.

## UAT hủy món và tồn kho

- Direct cancellation tại session `12`, line `12`, Kitchen ticket `NEW` không
  cần approval; tồn product `10` phục hồi từ 72 lên 73 đúng một lần và
  allocation `13` thành `RESTOCKED`.
- Tại session `15`, line Bar `16` và Kitchen `17` được đưa vào `IN_PROGRESS`.
  Reason trống không tạo durable cancellation. PIN sai chỉ tạo audit approval
  `5` loại `PIN_FAILED`, giữ resolution/reason và xóa riêng PIN.
- WASTE hợp lệ dùng approval `6`: một cancel log, allocation `17` thành
  `WASTE`, tồn product `17` không tăng.
- RESTOCK hợp lệ dùng approval `7`: một cancel log, allocation `18` thành
  `RESTOCKED`, tồn product `10` tăng đúng một lần từ 72 lên 73.
- Conflict sau polling tại session `11`, line `11`: thiết bị thứ hai tăng
  revision 3 → 4; dialog tự đóng/xóa, snapshot mới hiển thị, không có approval
  hay cancel mới và target line vẫn còn.
- Khi backend bị dừng đúng PID, UI giữ target line, hiện `Chưa đồng bộ... thử
  lại` và không báo thành công. Phiên giữ secret chỉ trong RAM bị mất khi task
  hỗ trợ hết quota, nên continuity retry end-to-end trong browser không được
  tuyên bố. Test Node khóa việc retry dùng nguyên body/operation ID; backend
  exact replay, one-use approval và operation-ID collision đều pass.

Bar/Kitchen fixed views và server view đều được kiểm tra ở mobile; dialog và
controls sử dụng được. Không dùng tài khoản, order, ticket hay credential thật.

## Runtime cô lập và dữ liệu

- URL local: `http://127.0.0.1:5701`; server đã dừng và port không còn listener.
- Temp root: `C:\Users\nguye\AppData\Local\Temp\fselling-r1-uat-8202a9e76afc49ada5fe86e3dd8a75e3`.
- Temp DB: `...\uat.db`; source/copy SHA-256 trước migration cùng bằng
  `6A2CC15FF9CD1AC7634FFD9195C89D8AED373E9CEECB743B512D0BEA351BD32C`.
- Migration/readiness ở revision `0011_fnb_checkout_r1c`.
- Chỉ bind `127.0.0.1`; secret ngẫu nhiên chỉ nằm trong RAM và không được ghi
  vào repo/report/log. Upload, cache và request log nằm ngoài repository.

## Commit và phạm vi thay đổi

Các commit triển khai sau plan `687189f`:

```text
0610835 fix: require explicit F&B cash tender
c3118e6 test: cover F&B tender method invariants
8856579 fix: require explicit cash intent in F&B checkout
5e1b15d fix: clear F&B cash tender when bill changes
5d708c1 fix: classify F&B cancellation recovery states
3d0fcee fix: clear persisted F&B cancellation drafts
a366377 fix: recover in-progress F&B cancellation
c8de051 fix: isolate F&B approval attempts
9fbe30b fix: recover F&B checkout after payment rejection
acb49c8 fix: refresh F&B checkout recovery asset
d4e99a2 fix: invalidate stale cancellation approvals
```

File triển khai/test trong R1:

```text
fselling/services/fnb_service.py
static/css/fnb-r1a.css
static/fnb.html
static/js/fnb-r1a.js
static/js/locales/fnb.js
tests/js/fnb-r1a.test.js
tests/test_fnb_r1a_ui.py
tests/test_fnb_r1b_cancel.py
tests/test_fnb_r1c_checkout.py
```

Không có migration, dependency, contract Retail, quyền/role, KDS state machine
hay table-close expansion. Các file Seller được bảo vệ không bị sửa hoặc
commit: `static/css/seller.css`, `static/js/locales/seller.js`,
`static/js/seller.js`, `static/seller.html`, `tests/test_seller_sidebar_ui.py`.

## P2/P3 và điều kiện production chưa xác minh

- P2: menu tồn có thể giữ số cũ ngay sau RESTOCK trong session đang mở; DB đã
  đúng và lần mở/refresh mới hiển thị 73. Chỉ nâng cấp nếu cần cập nhật tồn
  tức thời ngay trong cùng session.
- Giới hạn verifier: exact browser retry qua một lần restart không hoàn tất vì
  secret cố ý không lưu và phiên RAM bị mất; automated controller + backend
  idempotency là bằng chứng thay thế, không được trình bày như manual pass.
- Chưa xác minh payment/webhook thật, độ trễ đa thiết bị production, máy in thật,
  deploy, rollback hay monitoring production. Các điều kiện này cần release
  checklist riêng trước khi vận hành thật.

Khuyến nghị: review và merge Safety Hotfix R1 trước khi bắt đầu thiết kế chi
tiết Plan 2.
