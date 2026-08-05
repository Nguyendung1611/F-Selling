"""Khởi tạo FastAPI app: middleware, routers, static mount, scheduler."""
from __future__ import annotations

import zoneinfo
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .core import bootstrap
from .core.config import (
    ORDER_PENDING_TIMEOUT_MINUTES,
    STATIC_DIR,
    UPLOAD_DIR,
    get_allowed_origins,
)
from .core.i18n import LocaleMiddleware, tr
from .routers import (
    admin,
    auth,
    categories,
    cron,
    customers,
    orders,
    pages,
    products,
    reports,
    shifts,
    shops,
    staff,
    tts,
    vouchers,
    webhooks,
)
from .services.maintenance_service import (
    cancel_expired_pending_orders,
    cleanup_expired_unverified_users,
)

CLEANUP_INTERVAL_MINUTES = 1
AUTO_CANCEL_INTERVAL_MINUTES = 5

# Tạo bảng ngay khi import module (giữ đúng thời điểm như app.py cũ).
bootstrap.create_tables()


def _validation_message(error: dict) -> str:
    """Biến lỗi kỹ thuật của Pydantic thành câu ngắn theo ngôn ngữ request."""
    error_type = error.get("type", "")
    context = error.get("ctx") or {}
    if error_type == "missing":
        return tr("Trường này là bắt buộc")
    if error_type == "greater_than":
        return tr("Giá trị phải lớn hơn {minimum}", minimum=context.get("gt", ""))
    if error_type == "greater_than_equal":
        minimum = context.get("ge", "")
        return tr("Giá trị phải lớn hơn hoặc bằng {minimum}", minimum=minimum)
    if error_type == "less_than":
        return tr("Giá trị phải nhỏ hơn {maximum}", maximum=context.get("lt", ""))
    if error_type == "less_than_equal":
        maximum = context.get("le", "")
        return tr("Giá trị phải nhỏ hơn hoặc bằng {maximum}", maximum=maximum)
    if error_type == "string_too_short":
        return tr(
            "Nội dung phải có ít nhất {minimum} ký tự",
            minimum=context.get("min_length", ""),
        )
    if error_type == "string_too_long":
        return tr(
            "Nội dung chỉ được tối đa {maximum} ký tự",
            maximum=context.get("max_length", ""),
        )
    if error_type in {"enum", "literal_error"}:
        return tr("Giá trị không nằm trong danh sách được phép")
    return tr("Dữ liệu không hợp lệ. Vui lòng kiểm tra lại")


async def localized_validation_error_handler(
    _request, exc: RequestValidationError
) -> JSONResponse:
    errors = jsonable_encoder(exc.errors())
    for error in errors:
        error["msg"] = _validation_message(error)
    return JSONResponse(status_code=422, content={"detail": errors})


@asynccontextmanager
async def lifespan(app: FastAPI):
    bootstrap.initialize()

    scheduler = BackgroundScheduler(timezone=zoneinfo.ZoneInfo("UTC"))
    scheduler.add_job(
        cleanup_expired_unverified_users, "interval", minutes=CLEANUP_INTERVAL_MINUTES
    )
    print("[SCHEDULER] Background cleanup task started - runs every 1 minute")

    if ORDER_PENDING_TIMEOUT_MINUTES > 0:
        scheduler.add_job(
            cancel_expired_pending_orders, "interval", minutes=AUTO_CANCEL_INTERVAL_MINUTES
        )
        print(
            f"[SCHEDULER] Auto-cancel of stale PENDING orders is ON "
            f"(timeout {ORDER_PENDING_TIMEOUT_MINUTES} minutes)"
        )
    else:
        print(
            "[SCHEDULER] Auto-cancel of stale PENDING orders is OFF "
            "(set ORDER_PENDING_TIMEOUT_MINUTES to enable)"
        )

    scheduler.start()

    yield

    scheduler.shutdown()
    print("[SCHEDULER] Background cleanup task stopped")


def create_app(lifespan_handler=lifespan) -> FastAPI:
    application = FastAPI(title="F-Selling Backend", lifespan=lifespan_handler)
    application.add_exception_handler(
        RequestValidationError,
        localized_validation_error_handler,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=get_allowed_origins(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept-Language"],
    )
    application.add_middleware(LocaleMiddleware)

    application.include_router(auth.router)
    application.include_router(shops.router)
    application.include_router(categories.router)
    application.include_router(products.router)
    # webhooks PHẢI đứng trước orders: /api/orders/webhook vs /api/orders/{shop_id}
    application.include_router(webhooks.router)
    application.include_router(orders.router)
    application.include_router(shifts.router)
    application.include_router(staff.router)
    application.include_router(customers.router)
    application.include_router(vouchers.router)
    application.include_router(reports.router)
    application.include_router(admin.router)
    application.include_router(tts.router)
    application.include_router(cron.router)
    application.include_router(pages.router)

    # Phục vụ ảnh upload từ UPLOAD_DIR (volume) — phải mount trước mount "/"
    application.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
    application.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return application


app = create_app()
