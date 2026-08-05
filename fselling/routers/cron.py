"""Endpoint cho dịch vụ cron BÊN NGOÀI gọi vào.

Vì sao không để APScheduler lo: `fly.toml` đặt `min_machines_running = 0`, máy
TỰ TẮT khi không có traffic. Scheduler trong tiến trình chỉ chạy khi máy đang
thức, nên một job "2 giờ sáng" gần như không bao giờ nổ — lúc đó chẳng ai truy
cập để giữ máy thức cả. Đồng hồ phải nằm ngoài, và chính request của nó đánh
thức máy.

Dùng dịch vụ miễn phí như cron-job.org, gọi mỗi ngày một lần:

    POST https://<app>.fly.dev/api/cron/backup
    Header: X-Cron-Secret: <BACKUP_CRON_SECRET>
"""
from typing import Optional

from fastapi import APIRouter, Header, HTTPException

from ..core.config import BACKUP_CRON_SECRET
from ..core.security import compare_secret
from ..services import backup_service

router = APIRouter(prefix="/api/cron", tags=["cron"])


@router.post("/backup")
def chay_sao_luu(x_cron_secret: Optional[str] = Header(None)):
    """Chụp DB và tải lên R2. Trả 200 kèm thông tin bản sao.

    **Thất bại thì PHẢI trả mã lỗi**, và đây là chỗ khác hẳn webhook ngân hàng.
    Webhook trả 200 cho cả giao dịch bị từ chối vì 4xx/5xx làm ngân hàng retry
    vô hạn. Ở đây ngược lại: người gọi là dịch vụ cron của chính mình, nó retry
    vài lần là chuyện tốt, và mã lỗi chính là **cách duy nhất bạn biết bản sao
    hỏng**. Nuốt lỗi rồi trả 200 là biến trang theo dõi cron thành đèn xanh giả.
    """
    # Fail-closed: chưa cấu hình secret thì không mở cửa cho ai cả.
    if not BACKUP_CRON_SECRET:
        raise HTTPException(
            status_code=503, detail="Chua cau hinh BACKUP_CRON_SECRET"
        )

    # Kiểm secret TRƯỚC khi kiểm cấu hình R2: người chưa xác thực không cần biết
    # server đã cắm R2 hay chưa.
    if not compare_secret(x_cron_secret, BACKUP_CRON_SECRET):
        raise HTTPException(status_code=401, detail="Cron secret khong hop le")

    if not backup_service.dang_bat():
        raise HTTPException(
            status_code=503,
            detail=(
                "Chua cau hinh R2 (can R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, "
                "R2_SECRET_ACCESS_KEY, R2_BUCKET)"
            ),
        )

    try:
        return {"ok": True, **backup_service.chay_sao_luu()}
    except Exception as e:  # noqa: BLE001 - xem docstring: lỗi phải nổi lên ngoài
        raise HTTPException(status_code=500, detail=f"Sao luu that bai: {e}") from e
