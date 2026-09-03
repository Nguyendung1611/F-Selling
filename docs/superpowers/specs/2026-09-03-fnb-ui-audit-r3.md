# Audit giao diện F&B R3 — F-Selling

Ngày audit: 2026-09-03  
Phạm vi: sơ đồ bàn, gọi món, bill/thanh toán, thiết lập khu vực-bàn, màn hình Bếp/Bar và các trạng thái lỗi.  
Đối tượng chính: chủ quán và nhân viên ít am hiểu công nghệ, thao tác nhanh trong giờ đông khách.

## 1. Kết luận điều hành

**Điểm hiện tại: 5,5/10 — dùng được về nghiệp vụ, chưa sẵn sàng cho ca bán đông.**

Phần F&B hiện có nền nghiệp vụ tốt: bàn, món nháp, gửi bếp, chuyển/gộp bàn, tách bill, thanh toán, tồn kho và biến thể đã kết nối. Vấn đề lớn nằm ở kiến trúc thông tin và thứ bậc thị giác:

- “Sơ đồ bàn” hiện là lưới thẻ tự dàn, chưa cho người dùng thấy tình trạng toàn quán trong một lần nhìn.
- Chọn bàn mở một panel hẹp nhưng phải chứa cả menu, món nháp, món đã gửi, ghi chú, chuyển/gộp bàn và thanh toán.
- Thiết lập khu vực, bàn, luồng Bếp/Bar và PIN quản lý bị gom vào một hộp thoại.
- Chữ phụ và trạng thái quan trọng quá nhỏ đối với người dùng lớn tuổi; nhiều mức font-weight lạ làm chữ thiếu đồng đều.
- Màn hình Bếp/Bar thiếu bộ đếm thời gian và thứ tự ưu tiên trực quan — hai tín hiệu quan trọng nhất trong vận hành bếp.

**Không cần thêm ảnh món để giải quyết các vấn đề trên.** Ảnh chỉ hữu ích ở màn gọi món khi menu dài hoặc tên món dễ nhầm. Cần sửa luồng và thứ bậc thông tin trước.

## 2. Đối thủ sắp xếp như thế nào

| Sản phẩm | Cách bố trí đáng học | Áp dụng phù hợp cho F-Selling |
|---|---|---|
| CUKCUK | Sơ đồ bàn có tổng hợp số bàn trống/đang phục vụ/đặt trước theo khu vực; màu trạng thái rõ. Quy trình thiết lập nhanh hỏi số khu vực, tên khu vực và số bàn rồi tự tạo, sau đó mới cho chỉnh vị trí/hình dạng. | Thêm thanh tổng quan trạng thái, danh sách khu vực bên trái; đổi Thiết lập thành từng bước và tự sinh bàn. |
| Sapo FnB | Luồng phục vụ tách rõ: chọn bàn trống → chọn món → lưu/gửi bếp → phục vụ → thanh toán. Chọn bàn mở màn gọi món chuyên dụng. | Không nhồi toàn bộ thao tác vào panel cạnh sơ đồ bàn; bàn chỉ là điểm bắt đầu của một màn gọi món riêng. |
| iPOS KDS | Phiếu bếp chia trạng thái Chờ làm/Đang làm/Hoàn tất/Đã phục vụ; cảnh báo màu theo thời gian, định tuyến Bếp/Bar, ghi chú từng món và đồng bộ món hết. | KDS nên có 2 cột thao tác chính “Mới” và “Đang làm”, thời gian chờ lớn, màu cảnh báo và nút hành động thống nhất. |
| Square Restaurants | Floor plan chia khu vực, kéo/thả và đổi hình dạng bàn; modifier đi theo từng bước; luồng gửi món hỗ trợ “send-and-stay”. | Giữ sơ đồ vật lý là R3.2; R3.1 chỉ cần danh sách bàn vận hành tốt. Biến thể nên mở theo bước, không bày mọi lựa chọn trên card. |

Nguồn chính thức:

- [CUKCUK — Thiết lập sơ đồ bàn](https://helpv2.cukcuk.vn/vi/kb/thiet-lap-so-do-ban-3)
- [CUKCUK — Thiết lập sơ đồ nhà hàng](https://helpv2.cukcuk.vn/vi/kb/lam-the-nao-de-thiet-lap-so-do-nha-hang)
- [Sapo FnB — Tạo hóa đơn bán hàng](https://help.sapo.vn/huong-dan-tao-hoa-don-ban-hang-tren-sapo-fnb)
- [iPOS KDS — Quản lý chế biến](https://ipos.vn/san-pham/ipos-kds-giai-phap-quan-ly-che-bien/)
- [Square — Building your floor plan](https://squareup.com/help/us/en/article/6427-building-your-floor-plan)
- [Square Restaurants — POS features](https://squareup.com/us/en/point-of-sale/software/pricing)

## 3. Phát hiện ưu tiên

Thang mức độ: **S3** = cản trở ca bán hoặc dễ gây sai; **S2** = gây chậm/khó hiểu; **S1** = tinh chỉnh thẩm mỹ.

| Mức | Khu vực | Phát hiện | Tác động | Đề xuất |
|---|---|---|---|---|
| S3 | Gọi món | Menu, món nháp, món đã gửi, chuyển/gộp bàn và thanh toán cùng nằm trong panel hẹp. | Nhân viên phải cuộn và đổi ngữ cảnh liên tục; mobile thành một bottom sheet rất dài. | Chọn bàn mở **màn gọi món toàn trang**. Desktop dùng 3 cột: danh mục, món, bill. Mobile dùng một màn hình với bill/checkout cố định phía dưới. |
| S3 | Sơ đồ bàn | Lưới card tự dàn không thể hiện bố cục quán và không có tổng quan tình trạng. | Chủ quán khó nhìn bàn nào cần xử lý trước. | R3.1 gọi đúng là “Danh sách bàn”, thêm thanh tổng quan và bộ lọc khu vực/trạng thái. R3.2 mới làm sơ đồ kéo-thả. |
| S3 | Thiết lập | Khu vực, bàn, định tuyến từng sản phẩm và PIN quản lý nằm chung một modal hai cột. | Quá tải nhận thức, danh sách dài nhanh chóng mất kiểm soát. | Wizard 3 bước: (1) khu vực & số bàn, (2) xem/chỉnh bàn, (3) luồng chế biến theo **danh mục**; PIN tách sang mục Quản lý. |
| S3 | Thanh toán | Sau khi đã trả tiền, phần tổng vẫn có thể hiện nhãn “TẠM TÍNH — CHƯA THANH TOÁN”. | Mất niềm tin vào trạng thái bill và dễ thao tác lặp. | Trạng thái thanh toán là nguồn sự thật: sau trả tiền đổi sang “ĐÃ THANH TOÁN”, khóa sửa và hiện hành động xem/chia sẻ hóa đơn. |
| S3 | KDS | Phiếu bếp là lưới phẳng, không có thời gian chờ lớn hoặc cảnh báo già hóa đơn. | Bếp không biết phiếu nào cần làm trước khi đông khách. | Hai làn “Mới”/“Đang làm”; thời gian chờ lớn; màu trung tính → vàng → đỏ; CTA “Nhận làm”/“Hoàn tất”. |
| S3 | KDS/lỗi | Khi phiên/API lỗi, màn hình có thể hiện thông báo kỹ thuật `t is not defined`. | Màn hình bếp bị mắc kẹt, người dùng không biết cách phục hồi. | Sửa phụ thuộc i18n hoặc fallback lỗi dùng chung; hiển thị “Phiên đã hết” + “Đăng nhập lại”, hoặc “Mất kết nối” + “Thử lại”. |
| S3 | Trạng thái lỗi | Lỗi tải sơ đồ chỉ báo “Chưa cập nhật được”, không chỉ rõ mất mạng hay hết phiên và không có hành động nổi bật. | Người ít công nghệ không biết nên chờ, thử lại hay đăng nhập. | Tên lỗi bằng ngôn ngữ đời thường, một nguyên nhân có thể hiểu và một nút phục hồi chính. Giữ dữ liệu lần cuối nếu có cache. |
| S2 | Font chữ | Meta/eyebrow/status khoảng 12–13 px; weight 750/850 không nhất quán với Segoe UI. | Khó đọc với chủ quán lớn tuổi, chữ đậm hiển thị không đều theo máy. | Chỉ dùng 400/600/700; chữ phụ tối thiểu 13 px, ưu tiên 14 px trong KDS; số tiền và thời gian dùng tabular numerals. |
| S2 | Card bàn | Tên bàn, thời gian, tổng tiền và món chưa gửi có cấp bậc gần nhau; phần khuyết trang trí không mang ý nghĩa. | Người dùng phải đọc từng card thay vì quét nhanh. | Tên bàn 18 px, badge trạng thái góc phải, tổng tiền 18–20 px, thời gian/món chờ là chip; bỏ khuyết trang trí. |
| S2 | Card món | Mỗi món lặp chip Bếp/Bar; menu bị giới hạn trong vùng cuộn thấp. | Nhiễu thị giác và ít món nhìn thấy cùng lúc. | Danh mục/Món thường gọi ở trên; card chỉ giữ tên, giá, hết hàng và biến thể cần chọn. Routing là cấu hình, không phải thông tin bán hàng mặc định. |
| S2 | Sửa món | Số lượng là input thô, nhãn bị ẩn, ghi chú và mỗi dòng có nút “Lưu”. | Dễ quên lưu và khó thao tác nhanh bằng chạm. | Dùng `−  1  +`, nút “Thêm ghi chú”, tự lưu thay đổi; có Undo khi xóa/hủy. |
| S2 | Hành động khóa | “Tính tiền” bị khóa khi còn món chưa gửi nhưng lý do chỉ nằm trong tooltip. | Tooltip không xuất hiện trên thiết bị cảm ứng. | Hiện dòng lý do ngay bên dưới: “Gửi 2 món vào bếp trước khi tính tiền”, kèm hành động gửi. |
| S2 | Header | Lưới 4 cột tạo khoảng trống lớn; tên cửa hàng có thể xuống hai dòng; ngôn ngữ và thao tác quản trị tranh chỗ với nghiệp vụ. | Header dài nhưng không giúp xử lý đơn. | Một service bar gọn: F-Selling / Bán tại bàn, tên cửa hàng, trạng thái mạng/ca, tài khoản; ngôn ngữ và thiết lập vào menu quản lý. |

## 4. Kiến trúc màn hình đề xuất

### 4.1 Danh sách bàn

```text
[Bán tại bàn]  [Ca đang mở • Online]  [Tên quán]  [Tài khoản]

[12 bàn] [Trống 5] [Đang phục vụ 4] [Chờ món 2] [Chờ thanh toán 1]

[Tất cả khu vực]
[Tầng trệt]        [Bàn 01   ĐANG PHỤC VỤ] [Bàn 02   TRỐNG]
[Lầu 1]            [120.000đ · 18 phút]    [Mở bàn]
                   [2 món chưa gửi]
```

Không làm drag/drop trong R3.1. Danh sách có thứ bậc tốt đã giải quyết phần lớn nhu cầu với ít code và ít rủi ro hơn.

### 4.2 Màn gọi món sau khi chọn bàn

```text
[← Bàn 02] [3 khách] [18 phút]                 [Đổi bàn  ⋯]

[Danh mục]        [Tìm món...]                 [BILL BÀN 02]
[Thường gọi]      [Cà phê sữa] [Bia]           [2x Bia      40.000]
[Đồ uống]         [Lẩu bò]      [Khăn lạnh]     [1x Lẩu bò  220.000]
[Món chính]                                      [Ghi chú...]
[Món thêm]                                       [Món nháp: 2]
                                                 [GỬI BẾP]
                                                 [Tổng: 260.000]
                                                 [THANH TOÁN]
```

- Bill rộng cố định 380–420 px trên desktop.
- Footer bill dính đáy; không để tổng tiền và CTA trôi khỏi màn hình.
- Chuyển/gộp/tách bill nằm trong menu phụ, không cạnh tranh với “Gửi bếp” và “Thanh toán”.

### 4.3 KDS

```text
[BẾP] [Online] [Âm báo: Bật]                   [Món hết]

MỚI (4)                         ĐANG LÀM (2)
[Bàn 02 · 03:12  VÀNG]          [Bàn 05 · 08:40  ĐỎ]
[2  Lẩu bò]                     [1  Cơm chiên]
[1  Rau thêm]                   [Không hành]
[NHẬN LÀM]                      [HOÀN TẤT]
```

## 5. Hệ chữ và token đề xuất

Giữ font hệ thống offline-safe trong R3.1; chưa cần thêm webfont hoặc dependency.

| Vai trò | Cỡ / line-height | Weight |
|---|---:|---:|
| Body | 16 / 1.5 | 400 |
| Label, badge dễ đọc | 14 / 1.4 | 600 |
| Meta nhỏ nhất | 13 / 1.4 | 400–600 |
| H1 | 24 / 1.2 | 700 |
| H2 | 22 / 1.25 | 700 |
| Tên bàn/card | 18 / 1.35 | 700 |
| Tổng tiền | 20–22 / 1.2 | 700 |
| KDS số lượng | 26 / 1.1 | 700 |
| KDS tên món | 20 / 1.3 | 600–700 |
| KDS ghi chú | 16 / 1.4 | 600 |

Quy tắc tối thiểu:

- Chỉ dùng weight 400, 600 và 700.
- `font-variant-numeric: tabular-nums` cho tiền, số lượng và thời gian.
- Khoảng cách dùng thang 4/8/12/16/24 px; radius chính 8–10 px.
- Cam chỉ dùng cho hành động chính hoặc điểm cần chú ý; xanh/navy cho cấu trúc, xanh lá/xanh dương cho trạng thái thành công/đang xử lý.
- Không thêm gradient, animation trang trí hoặc ảnh stock vào giao diện vận hành.

## 6. Trạng thái bắt buộc trước khi coi là hoàn thiện

Mỗi màn cần được kiểm tra ở các trạng thái: mới dùng/chưa có bàn, đang tải, thành công, không có món, hết hàng, mất mạng, API chậm, hết phiên đăng nhập, không đủ quyền, món nháp chưa gửi, bill đã thanh toán, danh sách rất dài và màn hình 320 px.

Riêng KDS phải kiểm tra thêm: mất kết nối giữa ca, phiếu mới đến khi âm báo tắt, nhiều hơn 20 phiếu, ghi chú dài, món hết và thao tác trùng từ hai thiết bị.

## 7. Thứ tự triển khai khuyến nghị

### R3.1 — nên làm trước

1. Tách “Danh sách bàn” và “Màn gọi món toàn trang”.
2. Chuẩn hóa typography và card bàn/card món.
3. Làm lại bill/checkout và trạng thái đã thanh toán.
4. Tách Thiết lập thành wizard đơn giản; routing theo danh mục.
5. Làm lại KDS theo Mới/Đang làm, timer và trạng thái phục hồi lỗi.

### R3.2 — chỉ làm sau khi R3.1 được UAT

- Sơ đồ bàn vật lý kéo-thả, hình dạng bàn và background tầng.
- Tuỳ biến ngưỡng màu/âm báo KDS.
- Ảnh món theo danh mục nếu thử nghiệm thực tế cho thấy nhân viên tìm món nhanh hơn.

## 8. Khuyến nghị chốt

Chọn **R3.1 vận hành tối giản** trước, chưa làm sơ đồ kéo-thả và chưa thêm ảnh hàng loạt. Đây là phần thay đổi ít rủi ro nhất nhưng giải quyết đúng nguyên nhân: người dùng không nhìn thấy “việc tiếp theo” đủ nhanh.

Không thay đổi code trong vòng audit này. Chỉ triển khai sau khi khách hàng duyệt hướng R3.1.
