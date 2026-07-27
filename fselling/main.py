"""Khởi tạo FastAPI app: middleware, routers, static mount, scheduler."""
from __future__ import annotations

import zoneinfo
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .core import bootstrap
from .core.config import (
    ORDER_PENDING_TIMEOUT_MINUTES,
    STATIC_DIR,
    UPLOAD_DIR,
    get_allowed_origins,
)
from .routers import (
    admin,
    auth,
    categories,
    customers,
    orders,
    pages,
    products,
    reports,
    shops,
    staff,
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

    application.add_middleware(
        CORSMiddleware,
        allow_origins=get_allowed_origins(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    application.include_router(auth.router)
    application.include_router(shops.router)
    application.include_router(categories.router)
    application.include_router(products.router)
    # webhooks PHẢI đứng trước orders: /api/orders/webhook vs /api/orders/{shop_id}
    application.include_router(webhooks.router)
    application.include_router(orders.router)
    application.include_router(staff.router)
    application.include_router(customers.router)
    application.include_router(vouchers.router)
    application.include_router(reports.router)
    application.include_router(admin.router)
    application.include_router(pages.router)

    # Phục vụ ảnh upload từ UPLOAD_DIR (volume) — phải mount trước mount "/"
    application.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
    application.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return application


app = create_app()
