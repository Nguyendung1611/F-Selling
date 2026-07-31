"""Đọc tiền: sinh audio tiếng Việt khi thiết bị không có sẵn giọng."""
from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from .. import models
from ..dependencies import get_current_user
from ..services import tts_service

router = APIRouter(prefix="/api/tts", tags=["tts"])


class DocText(BaseModel):
    text: str


@router.get("/status")
def tts_status(current_user: models.User = Depends(get_current_user)):
    """Frontend hỏi trước để biết có nên trông cậy vào server hay không."""
    return {"enabled": tts_service.dang_bat()}


@router.post("")
def doc_thanh_tieng(
    payload: DocText,
    current_user: models.User = Depends(get_current_user),
):
    """Trả về mp3 cho đoạn chữ.

    BẮT BUỘC đăng nhập: endpoint này tiêu hạn mức trả phí của chủ shop, để mở
    thì thành dịch vụ đọc chữ miễn phí cho cả internet.
    """
    du_lieu, tu_cache = tts_service.tao_audio(payload.text)
    return Response(
        content=du_lieu,
        media_type="audio/mpeg",
        headers={
            "Cache-Control": "public, max-age=86400",
            "Content-Language": "vi",
            "X-TTS-Cache": "hit" if tu_cache else "miss",
        },
    )
