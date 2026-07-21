"""Dashboard, thống kê và xuất Excel."""
from __future__ import annotations

import io
from datetime import datetime, timedelta
from typing import Any, Dict, List

import openpyxl
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models
from ..core.config import log_to_file
from ..dependencies import require_shop_access

TREND_DAYS = 7


def _paid_revenue(db: Session, shop_id: int) -> float:
    return (
        db.query(func.sum(models.Order.total_amount))
        .filter(models.Order.shop_id == shop_id, models.Order.status == "PAID")
        .scalar()
        or 0
    )


def seller_dashboard(db: Session, current_user: models.User, shop_id: int) -> Dict[str, Any]:
    require_shop_access(db, shop_id, current_user)
    total_rev = _paid_revenue(db, shop_id)
    orders = (
        db.query(models.Order)
        .filter(models.Order.shop_id == shop_id)
        .order_by(models.Order.created_at.desc())
        .all()
    )
    return {
        "total_revenue": total_rev,
        "orders": [
            {"id": o.id, "total": o.total_amount, "status": o.status, "date": o.created_at}
            for o in orders
        ],
    }


def admin_dashboard(db: Session) -> List[Dict[str, Any]]:
    shops = db.query(models.Shop).all()
    log_to_file(f"get_admin_dashboard: Found {len(shops)} shops in DB")
    return [
        {"shop_name": s.name, "total_revenue": _paid_revenue(db, s.id)} for s in shops
    ]


def shop_stats(db: Session, current_user: models.User, shop_id: int) -> Dict[str, Any]:
    require_shop_access(db, shop_id, current_user)

    total_rev = _paid_revenue(db, shop_id)
    total_orders = db.query(models.Order).filter(models.Order.shop_id == shop_id).count()

    paid_orders_subquery = (
        db.query(models.Order.id)
        .filter(models.Order.shop_id == shop_id, models.Order.status == "PAID")
    )
    total_sold = (
        db.query(func.sum(models.OrderItem.quantity))
        .filter(models.OrderItem.order_id.in_(paid_orders_subquery))
        .scalar()
        or 0
    )

    top_products_query = (
        db.query(
            models.OrderItem.product_name,
            func.sum(models.OrderItem.quantity).label("total_qty"),
        )
        .filter(models.OrderItem.order_id.in_(paid_orders_subquery))
        .group_by(models.OrderItem.product_name)
        .order_by(func.sum(models.OrderItem.quantity).desc())
        .limit(5)
        .all()
    )
    top_products = [{"name": r[0], "qty": r[1]} for r in top_products_query]

    seven_days_ago = datetime.utcnow() - timedelta(days=TREND_DAYS - 1)
    recent_orders = (
        db.query(models.Order)
        .filter(
            models.Order.shop_id == shop_id,
            models.Order.status == "PAID",
            models.Order.created_at >= seven_days_ago,
        )
        .all()
    )

    revenue_by_date = {
        (datetime.utcnow() - timedelta(days=i)).strftime("%Y-%m-%d"): 0
        for i in range(TREND_DAYS)
    }
    for o in recent_orders:
        d_str = o.created_at.strftime("%Y-%m-%d")
        if d_str in revenue_by_date:
            revenue_by_date[d_str] += o.total_amount

    trend_labels = sorted(revenue_by_date.keys())
    trend_data = [revenue_by_date[k] for k in trend_labels]

    return {
        "total_revenue": total_rev,
        "total_orders": total_orders,
        "total_sold": total_sold,
        "top_products": top_products,
        "trend_labels": trend_labels,
        "trend_data": trend_data,
    }


def _workbook_to_stream(wb: "openpyxl.Workbook") -> io.BytesIO:
    out = io.BytesIO()
    wb.save(out)
    out.seek(0)
    return out


def admin_excel(db: Session) -> io.BytesIO:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Doanh thu Shops"
    ws.append(["Tên Shop", "Tổng Doanh Thu"])
    for s in db.query(models.Shop).all():
        ws.append([s.name, _paid_revenue(db, s.id)])
    return _workbook_to_stream(wb)


def seller_excel(db: Session, current_user: models.User, shop_id: int) -> io.BytesIO:
    require_shop_access(db, shop_id, current_user)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Lịch sử giao dịch"
    ws.append(["Mã đơn", "Ngày tạo", "Trạng thái", "Thành tiền"])

    orders = db.query(models.Order).filter(models.Order.shop_id == shop_id).all()
    total_rev = 0
    for o in orders:
        ws.append([o.id, str(o.created_at), o.status, o.total_amount])
        if o.status == "PAID":
            total_rev += o.total_amount

    ws.append([])
    ws.append(["Tổng Doanh Thu (Đã thanh toán)", total_rev])
    return _workbook_to_stream(wb)
