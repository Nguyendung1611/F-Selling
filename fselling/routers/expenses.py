"""K1: chi phí vận hành, lợi nhuận ròng và dòng tiền thực.

Mọi endpoint ở đây chỉ dành cho chủ shop và ADMIN - service tự kiểm bằng
`require_cost_visibility`. Đường dẫn cố ý tách ba tiền tố riêng
(`/api/expense-categories`, `/api/expense-templates`, `/api/expenses`) để id
danh mục và id khoản chi không bao giờ rơi vào cùng khuôn với `shop_id`.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import models
from ..dependencies import get_current_user, get_db
from ..schemas.expense import (
    ExpenseCategoryCreate,
    ExpenseCategoryUpdate,
    ExpenseCreate,
    ExpenseTemplateCreate,
    ExpenseTemplateUpdate,
)
from ..services import expense_service, report_service

router = APIRouter(tags=["expenses"])


# --- Danh mục chi phí -------------------------------------------------------

@router.get("/api/expense-categories/{shop_id}")
def danh_sach_loai_chi_phi(
    shop_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return expense_service.list_categories(db, current_user, shop_id)


@router.post("/api/expense-categories/{shop_id}")
def them_loai_chi_phi(
    shop_id: int,
    request: ExpenseCategoryCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return expense_service.create_category(db, current_user, shop_id, request)


@router.put("/api/expense-categories/{shop_id}/{category_id}")
def sua_loai_chi_phi(
    shop_id: int,
    category_id: int,
    request: ExpenseCategoryUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Đổi tên hoặc ẩn/hiện. CỐ Ý không có DELETE: xem docstring service."""
    return expense_service.update_category(
        db, current_user, shop_id, category_id, request
    )


# --- Mẫu chi phí cố định ----------------------------------------------------

@router.get("/api/expense-templates/{shop_id}")
def danh_sach_chi_phi_co_dinh(
    shop_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return expense_service.list_templates(db, current_user, shop_id)


@router.post("/api/expense-templates/{shop_id}")
def them_chi_phi_co_dinh(
    shop_id: int,
    request: ExpenseTemplateCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return expense_service.create_template(db, current_user, shop_id, request)


@router.put("/api/expense-templates/{shop_id}/{template_id}")
def sua_chi_phi_co_dinh(
    shop_id: int,
    template_id: int,
    request: ExpenseTemplateUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return expense_service.update_template(
        db, current_user, shop_id, template_id, request
    )


@router.get("/api/expense-reminders/{shop_id}")
def nhac_chi_phi_co_dinh(
    shop_id: int,
    thang: Optional[str] = Query(None, description="Tháng cần nhắc (YYYY-MM)"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Chi phí cố định tháng này còn thiếu bao nhiêu (so theo TỔNG đã ghi)."""
    return expense_service.reminders(db, current_user, shop_id, thang)


# --- Sổ chi phí -------------------------------------------------------------

@router.get("/api/expenses/{shop_id}")
def danh_sach_chi_phi(
    shop_id: int,
    tu_ngay: Optional[str] = Query(None, description="Lọc từ ngày (YYYY-MM-DD)"),
    den_ngay: Optional[str] = Query(None, description="Lọc đến ngày (YYYY-MM-DD)"),
    page: int = Query(1, ge=1),
    per_page: int = Query(
        expense_service.DEFAULT_PAGE_SIZE, ge=1, le=expense_service.MAX_PAGE_SIZE
    ),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return expense_service.list_expenses(
        db,
        current_user,
        shop_id,
        tu_ngay=tu_ngay,
        den_ngay=den_ngay,
        page=page,
        per_page=per_page,
    )


@router.post("/api/expenses/{shop_id}")
def ghi_chi_phi(
    shop_id: int,
    request: ExpenseCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Ghi một khoản đã chi. Tiền mặt từ ca sinh đúng một chuyển động két."""
    return expense_service.create_expense(db, current_user, shop_id, request)


@router.post("/api/expenses/{shop_id}/{expense_id}/void")
def go_chi_phi(
    shop_id: int,
    expense_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Gỡ khoản ghi nhầm. Khoản đã rút tiền từ ca thì bị từ chối (409)."""
    return expense_service.void_expense(db, current_user, shop_id, expense_id)


# --- Báo cáo ----------------------------------------------------------------

@router.get("/api/reports/cashflow/{shop_id}")
def bao_cao_dong_tien(
    shop_id: int,
    tu_ngay: Optional[str] = Query(None, description="Lọc từ ngày (YYYY-MM-DD)"),
    den_ngay: Optional[str] = Query(None, description="Lọc đến ngày (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    """Lợi nhuận ròng + dòng tiền thực + lý do hai con số đó khác nhau."""
    return report_service.net_cashflow_report(
        db, current_user, shop_id, tu_ngay=tu_ngay, den_ngay=den_ngay
    )
