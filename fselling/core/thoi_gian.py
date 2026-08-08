"""Ngày nghiệp vụ của cửa hàng. MỘT nguồn sự thật cho câu hỏi "hôm nay là ngày mấy".

Trước file này, câu hỏi đó có BA câu trả lời khác nhau nằm rải trong services:

    datetime.utcnow().date()   -> lệch 7 tiếng: từ 0h đến 7h sáng giờ Việt Nam
                                  máy vẫn tưởng còn là hôm qua
    date.today()               -> theo múi giờ của MÁY chạy app: đúng trên máy
                                  dev ở Việt Nam, sai ngay khi deploy lên server
                                  đặt ở Mỹ hoặc chạy trong Docker (mặc định UTC)
    datetime.now(VN).date()    -> đúng

Hậu quả không nằm ở chỗ "lệch vài tiếng". Nó nằm ở chỗ **hai màn hình cùng nói
về một lô hàng nhưng dùng hai cái "hôm nay" khác nhau**: lô hết hạn lúc nửa đêm
có thể vừa không bán được, vừa chưa được phép hủy - hoặc tệ hơn, vẫn bán được
trong 7 tiếng sau khi đã quá hạn.

Việt Nam là UTC+7 quanh năm, không có giờ mùa hè, nên ngày nghiệp vụ luôn tính
được từ một mốc thời gian tuyệt đối mà không cần biết máy chủ đặt ở đâu.

Mọi chỗ cần "hôm nay" PHẢI gọi vào đây. Đừng viết lại `datetime.now(...)` trong
service mới - đó đúng là cách bốn bản sao lệch nhau đã ra đời.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

MUI_GIO_VN = ZoneInfo("Asia/Ho_Chi_Minh")


def _bay_gio() -> datetime:
    """Thời điểm hiện tại, có gắn múi giờ.

    Tách riêng để test đứng được ở một mốc cố định: hành vi quanh nửa đêm giờ
    Việt Nam là thứ không thể kiểm bằng cách chờ tới nửa đêm.
    """
    return datetime.now(MUI_GIO_VN)


def hom_nay_vn() -> date:
    """Ngày lịch Việt Nam, không phụ thuộc múi giờ của máy deploy."""
    return _bay_gio().date()


def hom_nay_vn_str() -> str:
    """Ngày lịch Việt Nam dạng 'YYYY-MM-DD'.

    Dùng cho các cột lưu ngày bằng chuỗi (`ProductBatch.expiry_date`,
    `Voucher.expires_at`, `PurchaseReceipt.received_date`): so sánh chuỗi theo
    đúng định dạng này là so sánh đúng thứ tự ngày.
    """
    return hom_nay_vn().isoformat()


def dau_ngay_vn_sang_utc(ngay: date) -> datetime:
    """00:00 của một ngày Việt Nam -> mốc UTC không gắn timezone.

    Đây là dạng mà `created_at` đang lưu (`datetime.utcnow()`), nên mọi phép lọc
    "từ ngày ... đến ngày ..." phải đi qua hàm này thay vì so thẳng với ngày
    lịch - so thẳng là đơn bán lúc 8 giờ tối bị đẩy sang hôm sau.
    """
    local = datetime.combine(ngay, datetime.min.time(), tzinfo=MUI_GIO_VN)
    return local.astimezone(timezone.utc).replace(tzinfo=None)
