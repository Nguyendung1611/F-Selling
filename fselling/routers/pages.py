"""Phục vụ các trang HTML + redirect URL .html cũ sang clean URL.

Đường dẫn "static/..." giữ nguyên dạng tương đối như code cũ:
server luôn được khởi động từ thư mục `python_app`.
"""
from fastapi import APIRouter, status
from fastapi.responses import FileResponse, RedirectResponse

router = APIRouter(include_in_schema=False)


def _redirect(target: str) -> RedirectResponse:
    return RedirectResponse(url=target, status_code=status.HTTP_301_MOVED_PERMANENTLY)


# --- Clean URL Routes for HTML Pages ---
@router.get("/admin", response_class=FileResponse)
def get_admin() -> FileResponse:
    return FileResponse("static/admin.html")


@router.get("/pos", response_class=FileResponse)
def get_pos() -> FileResponse:
    return FileResponse("static/pos.html")


@router.get("/register", response_class=FileResponse)
def get_register() -> FileResponse:
    return FileResponse("static/register.html")


@router.get("/seller", response_class=FileResponse)
def get_seller() -> FileResponse:
    return FileResponse("static/seller.html")


@router.get("/verify", response_class=FileResponse)
def get_verify() -> FileResponse:
    return FileResponse("static/verify.html")


# --- Redirect old HTML URLs to Clean URLs ---
@router.get("/admin.html")
def redirect_admin() -> RedirectResponse:
    return _redirect("/admin")


@router.get("/pos.html")
def redirect_pos() -> RedirectResponse:
    return _redirect("/pos")


@router.get("/register.html")
def redirect_register() -> RedirectResponse:
    return _redirect("/register")


@router.get("/seller.html")
def redirect_seller() -> RedirectResponse:
    return _redirect("/seller")


@router.get("/verify.html")
def redirect_verify() -> RedirectResponse:
    return _redirect("/verify")


@router.get("/index.html")
def redirect_index() -> RedirectResponse:
    return _redirect("/")


@router.get("/index")
def redirect_index_clean() -> RedirectResponse:
    return _redirect("/")
