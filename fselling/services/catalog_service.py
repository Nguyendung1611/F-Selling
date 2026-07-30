"""Nghiệp vụ danh mục & sản phẩm (gồm kiểm tra file ảnh upload)."""
from __future__ import annotations

import os
import pathlib
import re
import uuid
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, UploadFile
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models
from ..core.config import (
    ALLOWED_IMAGE_EXTS,
    ALLOWED_IMAGE_MIMES,
    MAX_IMAGE_SIZE,
    UPLOAD_DIR,
)
from ..dependencies import (
    PERMISSION_INVENTORY,
    PERMISSION_SALE,
    has_shop_operator_access,
    require_any_staff_permission,
    require_shop_access,
    require_staff_permission,
)
from ..schemas.catalog import CategoryUpdate
from .log_service import log_system_action

DEFAULT_PRODUCT_IMAGE = "https://placehold.co/150x150/1E293B/FFF?text=SP"

# Chữ, số và dấu gạch ngang. CỐ Ý không kiểm checksum EAN-13/UPC: rất nhiều shop
# tự in mã nội bộ dạng Code128 không theo chuẩn EAN, ép checksum sẽ chặn oan.
_BARCODE_PATTERN = re.compile(r"^[A-Z0-9\-]{4,64}$")


def normalize_barcode(raw: Optional[str]) -> Optional[str]:
    """Chuẩn hóa mã vạch về dạng lưu trong DB, hoặc None nếu bỏ trống.

    Viết hoa toàn bộ để tra cứu không phụ thuộc hoa/thường: người dùng gõ tay
    'abc-123' và máy quét bắn ra 'ABC-123' phải khớp cùng một sản phẩm.
    Khoảng trắng bị loại bỏ vì một số máy quét chèn thêm khi đọc mã dài.
    """
    if raw is None:
        return None
    cleaned = "".join(raw.split()).upper()
    if not cleaned:
        return None
    if not _BARCODE_PATTERN.match(cleaned):
        raise HTTPException(
            status_code=400,
            detail="Mã vạch chỉ gồm chữ, số và dấu gạch ngang, dài 4-64 ký tự",
        )
    return cleaned


def _ensure_barcode_unique(
    db: Session,
    shop_id: int,
    barcode: Optional[str],
    exclude_product_id: Optional[int] = None,
) -> None:
    """Chặn hai sản phẩm cùng shop dùng chung một mã vạch.

    Có unique index ở tầng DB đỡ phía sau, nhưng kiểm ở đây để báo lỗi nêu rõ
    sản phẩm nào đang giữ mã, thay vì để IntegrityError bật lên thành 500.
    """
    if not barcode:
        return
    query = db.query(models.Product).filter(
        models.Product.shop_id == shop_id,
        models.Product.barcode == barcode,
    )
    if exclude_product_id is not None:
        query = query.filter(models.Product.id != exclude_product_id)
    holder = query.first()
    if holder:
        raise HTTPException(
            status_code=400,
            detail=f"Mã vạch '{barcode}' đã được dùng cho sản phẩm '{holder.name}'",
        )


# Ràng buộc duy nhất ở tầng DB -> thông báo cho người dùng. Khóa là mảnh chuỗi
# xuất hiện trong thông báo lỗi của SQLite ("UNIQUE constraint failed: <cột>").
_RANG_BUOC_DUY_NHAT = {
    "products.code": "Mã sản phẩm vừa được sản phẩm khác dùng. Vui lòng thử lại.",
    "products.barcode": "Mã vạch vừa được sản phẩm khác dùng. Vui lòng thử lại.",
    "products.name": "Tên sản phẩm vừa được sản phẩm khác dùng. Vui lòng thử lại.",
}


def _ghi_bat_trung(db: Session, ghi) -> None:
    """Chạy `ghi()` (flush hoặc commit), đổi lỗi ràng buộc duy nhất thành 400.

    Các hàm bên dưới đều kiểm trùng trước khi ghi, nhưng giữa lúc kiểm và lúc
    ghi vẫn có khe: hai request cùng gửi một mã có thể cùng vượt qua bước kiểm.
    Unique index chặn được ở tầng dưới, nhưng nó ném `IntegrityError` nên người
    dùng nhận 500 thay vì biết mình cần đổi mã.

    Phải bọc CẢ `flush()` lẫn `commit()`: `create_product` flush để lấy id nên
    câu INSERT chạy ngay tại đó, còn `update_product` không flush nên câu UPDATE
    chạy lúc commit.

    CHỈ dịch những ràng buộc có tên trong `_RANG_BUOC_DUY_NHAT`; mọi
    `IntegrityError` khác được ném tiếp để vẫn nổ 500 - đó là lỗi lập trình cần
    sửa, không được giấu đi.

    Lưu ý: cách nhận biết dựa vào chuỗi thông báo của SQLite. Nếu sau này đổi
    sang database khác, chuỗi sẽ khác và hàm này lặng lẽ hết tác dụng (quay về
    500) - không sai nghiêm trọng, nhưng phải nhớ mà sửa.
    """
    try:
        ghi()
    except IntegrityError as e:
        db.rollback()
        chi_tiet = str(getattr(e, "orig", e))
        for khoa, thong_bao in _RANG_BUOC_DUY_NHAT.items():
            if khoa in chi_tiet:
                raise HTTPException(status_code=400, detail=thong_bao) from e
        raise


def _flush_bat_trung(db: Session) -> None:
    _ghi_bat_trung(db, db.flush)


def _commit_bat_trung(db: Session) -> None:
    _ghi_bat_trung(db, db.commit)


def _ensure_code_unique(
    db: Session,
    shop_id: int,
    code: Optional[str],
    exclude_product_id: Optional[int] = None,
) -> None:
    """Chặn hai sản phẩm cùng shop dùng chung một mã nội bộ.

    Trước đây không có kiểm tra này, và mã tự sinh dựa trên timestamp theo giây
    nên mọi sản phẩm tạo trong cùng một giây đều trùng mã. Mã trùng làm hỏng
    việc tra cứu: quét/tìm ra mã đó thì không biết là sản phẩm nào.
    """
    if not code:
        return
    query = db.query(models.Product).filter(
        models.Product.shop_id == shop_id,
        models.Product.code == code,
    )
    if exclude_product_id is not None:
        query = query.filter(models.Product.id != exclude_product_id)
    holder = query.first()
    if holder:
        raise HTTPException(
            status_code=400,
            detail=f"Mã sản phẩm '{code}' đã được dùng cho sản phẩm '{holder.name}'",
        )


def find_by_barcode(
    db: Session, shop_id: int, barcode: str
) -> Optional[models.Product]:
    """Tra sản phẩm theo mã vạch, giới hạn trong một shop.

    Chỉ trả sản phẩm đang hiện: quét trúng SP đã ẩn mà vẫn bán được thì việc ẩn
    sản phẩm thành vô nghĩa.
    """
    normalized = normalize_barcode(barcode)
    if not normalized:
        return None
    return (
        db.query(models.Product)
        .filter(
            models.Product.shop_id == shop_id,
            models.Product.barcode == normalized,
            models.Product.is_active == True,  # noqa: E712 - SQLAlchemy cần so sánh ==
        )
        .first()
    )


def is_valid_image(data: bytes) -> bool:
    """Kiểm tra magic bytes để xác nhận file thực sự là JPEG/PNG/WEBP."""
    if len(data) < 12:
        return False
    if data[:3] == b"\xff\xd8\xff":  # JPEG
        return True
    if data[:8] == b"\x89PNG\r\n\x1a\n":  # PNG
        return True
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":  # WEBP
        return True
    return False


def _require_shop_operator_403(
    db: Session,
    shop_id: int,
    current_user: models.User,
    permission: Optional[str] = PERMISSION_INVENTORY,
) -> models.Shop:
    """Cho phép chủ shop / ADMIN / nhân viên của shop thao tác. Nếu không -> 403.
    (Giữ 403 'Not your shop' như hành vi cũ của các endpoint tạo SP/danh mục.)"""
    shop = db.query(models.Shop).filter(models.Shop.id == shop_id).first()
    if not shop or not has_shop_operator_access(shop, current_user):
        raise HTTPException(status_code=403, detail="Not your shop")
    if permission is not None:
        require_staff_permission(current_user, permission)
    return shop


# --- Categories ---
def create_category(
    db: Session, current_user: models.User, name: str, shop_id: int
) -> models.Category:
    _require_shop_operator_403(db, shop_id, current_user)

    name_stripped = name.strip() if name else ""
    if not name_stripped:
        raise HTTPException(status_code=400, detail="Tên danh mục không được để trống")

    cat = models.Category(name=name_stripped, shop_id=shop_id, is_active=True)
    db.add(cat)
    db.commit()
    log_system_action(
        db,
        current_user.id,
        "CREATE_CATEGORY",
        f"Tạo danh mục '{name_stripped}' cho shop #{shop_id}",
    )
    db.refresh(cat)
    return cat


def update_category(
    db: Session, current_user: models.User, category_id: int, cat: CategoryUpdate
) -> models.Category:
    db_cat = db.query(models.Category).filter(models.Category.id == category_id).first()
    if not db_cat:
        raise HTTPException(status_code=404, detail="Danh mục không tồn tại")

    shop = db.query(models.Shop).filter(models.Shop.id == db_cat.shop_id).first()
    if not shop or not has_shop_operator_access(shop, current_user):
        raise HTTPException(
            status_code=403, detail="Không có quyền chỉnh sửa danh mục của cửa hàng này"
        )
    require_staff_permission(current_user, PERMISSION_INVENTORY)

    name_stripped = cat.name.strip() if cat.name else ""
    if not name_stripped:
        raise HTTPException(status_code=400, detail="Tên danh mục không được để trống")

    db_cat.name = name_stripped
    db_cat.is_active = cat.is_active
    db.commit()
    db.refresh(db_cat)
    log_system_action(
        db,
        current_user.id,
        "UPDATE_CATEGORY",
        f"Cập nhật danh mục: '{db_cat.name}' (ID: {db_cat.id}, Active: {db_cat.is_active})",
    )
    db.refresh(db_cat)
    return db_cat


def list_categories(
    db: Session, current_user: models.User, shop_id: int
) -> List[models.Category]:
    require_shop_access(db, shop_id, current_user)
    # POS cần đọc danh mục; kho cũng cần. Chỉ các thao tác ghi mới bắt buộc
    # quyền INVENTORY.
    require_any_staff_permission(
        current_user, PERMISSION_SALE, PERMISSION_INVENTORY
    )
    return db.query(models.Category).filter(models.Category.shop_id == shop_id).all()


# --- Products ---
def save_product_image(image: UploadFile) -> str:
    """Kiểm tra loại file, đuôi file, kích thước, magic bytes;
    tự sinh tên file bằng UUID (tránh path traversal). Trả về URL public."""
    if image.content_type not in ALLOWED_IMAGE_MIMES:
        raise HTTPException(
            status_code=400, detail="Loại file không hợp lệ. Chỉ chấp nhận JPG, PNG, WEBP"
        )

    ext = pathlib.Path(image.filename).suffix.lower()
    if ext not in ALLOWED_IMAGE_EXTS:
        raise HTTPException(status_code=400, detail="Đuôi file không hợp lệ")

    contents = image.file.read()
    if len(contents) > MAX_IMAGE_SIZE:
        raise HTTPException(status_code=400, detail="File quá lớn (tối đa 2MB)")
    if not contents:
        raise HTTPException(status_code=400, detail="File rỗng")

    if not is_valid_image(contents):
        raise HTTPException(status_code=400, detail="Nội dung file không phải ảnh hợp lệ")

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)
    with open(filepath, "wb") as buffer:
        buffer.write(contents)
    return f"/uploads/{filename}"


def lookup_by_barcode(
    db: Session, current_user: models.User, shop_id: int, barcode: str
) -> Dict[str, Any]:
    """Tra sản phẩm theo mã vạch cho màn hình quét. 404 nếu không có mã đó.

    Frontend đã giữ sẵn danh sách sản phẩm trong bộ nhớ nên phần lớn lượt quét
    khớp được ngay tại máy khách. Endpoint này để đối chiếu lại khi máy khách
    không tìm thấy: danh sách có thể đã cũ (nhân viên khác vừa thêm sản phẩm),
    lúc đó câu trả lời "không tìm thấy" phải do server quyết định.
    """
    _require_shop_operator_403(db, shop_id, current_user, permission=None)
    require_any_staff_permission(
        current_user, PERMISSION_SALE, PERMISSION_INVENTORY
    )
    prod = find_by_barcode(db, shop_id, barcode)
    if not prod:
        raise HTTPException(
            status_code=404, detail=f"Không tìm thấy sản phẩm có mã vạch '{barcode}'"
        )
    return {
        "id": prod.id,
        "code": prod.code,
        "barcode": prod.barcode,
        "name": prod.name,
        "price": prod.price,
        "stock": prod.stock,
        "image_url": prod.image_url,
        "is_active": prod.is_active,
        "category_id": prod.category_id,
        "shop_id": prod.shop_id,
    }


def create_product(
    db: Session,
    current_user: models.User,
    shop_id: int,
    name: str,
    price: float,
    stock: int,
    category_id: int,
    code: Optional[str] = None,
    barcode: Optional[str] = None,
    image: Optional[UploadFile] = None,
) -> models.Product:
    _require_shop_operator_403(db, shop_id, current_user)

    existing_prod = (
        db.query(models.Product)
        .filter(models.Product.shop_id == shop_id, models.Product.name == name)
        .first()
    )
    if existing_prod:
        raise HTTPException(
            status_code=400, detail="Sản phẩm với tên này đã tồn tại trong cửa hàng!"
        )

    if price <= 0:
        raise HTTPException(status_code=400, detail="Giá sản phẩm phải lớn hơn 0")
    if stock < 0:
        raise HTTPException(status_code=400, detail="Số lượng tồn kho không được âm")

    barcode_value = normalize_barcode(barcode)
    _ensure_barcode_unique(db, shop_id, barcode_value)

    code_stripped = code.strip() if code else ""
    _ensure_code_unique(db, shop_id, code_stripped)

    image_url = DEFAULT_PRODUCT_IMAGE
    if image and image.filename:
        image_url = save_product_image(image)

    p = models.Product(
        code=code_stripped or None,
        barcode=barcode_value,
        name=name,
        price=price,
        stock=stock,
        image_url=image_url,
        category_id=category_id,
        shop_id=shop_id,
    )
    db.add(p)
    # Mã tự sinh lấy từ chính id của sản phẩm. Bản cũ dùng timestamp theo GIÂY
    # nên hai sản phẩm tạo cách nhau dưới một giây là trùng mã; id thì không bao
    # giờ đụng nhau, kể cả khi hai người tạo cùng lúc. flush() để có id trước
    # khi commit, vẫn nằm trong một transaction duy nhất.
    _flush_bat_trung(db)
    if not p.code:
        p.code = f"SP-{p.id}"
    code = p.code
    _commit_bat_trung(db)
    log_system_action(
        db,
        current_user.id,
        "CREATE_PRODUCT",
        f"Tạo SP: '{name}' ({code}) - Giá: {price:,.0f}đ, Kho: {stock}",
    )
    db.refresh(p)
    return p


def list_products(db: Session, shop_id: int) -> List[Dict]:
    products = db.query(models.Product).filter(models.Product.shop_id == shop_id).all()
    res: List[Dict] = []
    for p in products:
        cat_active = True
        if p.category:
            cat_active = p.category.is_active if p.category.is_active is not None else True
        res.append(
            {
                "id": p.id,
                "code": p.code,
                "barcode": p.barcode,
                "name": p.name,
                "price": p.price,
                "stock": p.stock,
                "image_url": p.image_url,
                "is_active": p.is_active,
                "category_id": p.category_id,
                "shop_id": p.shop_id,
                "category_is_active": cat_active,
            }
        )
    return res


def update_product(
    db: Session,
    current_user: models.User,
    product_id: int,
    name: str,
    price: float,
    category_id: int,
    code: Optional[str] = None,
    barcode: Optional[str] = None,
    image: Optional[UploadFile] = None,
) -> models.Product:
    """Sửa thông tin sản phẩm: tên, giá, mã, mã vạch, danh mục, ảnh.

    `barcode` phân biệt hai trường hợp mà `code` không phân biệt:
    - `None` (form không gửi field) -> giữ nguyên mã vạch cũ.
    - `""` (form gửi field rỗng)    -> xóa mã vạch, đặt về NULL.
    Cần tách như vậy để sửa được lỗi gán nhầm mã vạch cho sản phẩm.

    CỐ Ý KHÔNG đụng vào `stock`. Ghi đè tồn kho từ form sửa gây mất hàng khi
    có bán song song (seller mở form thấy tồn 100, POS bán vài đơn, seller bấm
    Lưu -> tồn quay lại 100). Thay đổi tồn kho đi qua `adjust_stock` (nhập/xuất
    theo delta, cập nhật nguyên tử).
    """
    prod = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not prod:
        raise HTTPException(status_code=404, detail="Sản phẩm không tồn tại")
    require_shop_access(db, prod.shop_id, current_user)
    require_staff_permission(current_user, PERMISSION_INVENTORY)

    name_stripped = name.strip() if name else ""
    if not name_stripped:
        raise HTTPException(status_code=400, detail="Tên sản phẩm không được để trống")
    if price <= 0:
        raise HTTPException(status_code=400, detail="Giá sản phẩm phải lớn hơn 0")

    category = (
        db.query(models.Category)
        .filter(
            models.Category.id == category_id,
            models.Category.shop_id == prod.shop_id,
        )
        .first()
    )
    if not category:
        raise HTTPException(status_code=400, detail="Danh mục không thuộc cửa hàng này")

    duplicate = (
        db.query(models.Product)
        .filter(
            models.Product.shop_id == prod.shop_id,
            models.Product.name == name_stripped,
            models.Product.id != product_id,
        )
        .first()
    )
    if duplicate:
        raise HTTPException(
            status_code=400,
            detail="Sản phẩm với tên này đã tồn tại trong cửa hàng!",
        )

    if barcode is not None:
        barcode_value = normalize_barcode(barcode)
        _ensure_barcode_unique(db, prod.shop_id, barcode_value, exclude_product_id=product_id)
        prod.barcode = barcode_value

    # Để trống ô mã thì giữ mã cũ (hành vi sẵn có, có test bảo vệ).
    code_stripped = code.strip() if code and code.strip() else None
    if code_stripped and code_stripped != prod.code:
        _ensure_code_unique(db, prod.shop_id, code_stripped, exclude_product_id=product_id)
        prod.code = code_stripped
    prod.name = name_stripped
    prod.price = price
    prod.category_id = category_id
    if image and image.filename:
        prod.image_url = save_product_image(image)

    _commit_bat_trung(db)
    log_system_action(
        db,
        current_user.id,
        "UPDATE_PRODUCT",
        f"Cập nhật SP: '{prod.name}' ({prod.code}) - Giá: {price:,.0f}đ",
    )
    db.refresh(prod)
    return prod


def apply_stocktake(
    db: Session, current_user: models.User, shop_id: int, items: List[Any]
) -> Dict[str, Any]:
    """Áp dụng kết quả kiểm kê: đặt tồn kho bằng số đếm được thực tế.

    Ba nguyên tắc an toàn:

    1. CHỈ đụng vào sản phẩm có trong danh sách gửi lên. Sản phẩm không đếm tới
       được giữ nguyên, KHÔNG coi là tồn 0 - quên quét một kệ hàng mà bị xóa
       sạch tồn kho thì tai hại hơn nhiều so với việc kiểm kê thiếu.

    2. Dòng nào có tồn kho đã đổi so với lúc bắt đầu đếm thì BỎ QUA và báo lại.
       Bán hàng vẫn chạy song song khi đang kiểm kê; ghi đè lúc đó sẽ nuốt mất
       số hàng vừa bán. Không đoán - trả về để người dùng đếm lại đúng sản phẩm
       đó.

    3. Không cho số đếm âm.
    """
    _require_shop_operator_403(db, shop_id, current_user)

    if not items:
        raise HTTPException(status_code=400, detail="Chưa có sản phẩm nào được đếm")

    ids = [it.product_id for it in items]
    if len(set(ids)) != len(ids):
        raise HTTPException(
            status_code=400, detail="Một sản phẩm xuất hiện nhiều lần trong phiếu kiểm kê"
        )
    for it in items:
        if it.counted < 0:
            raise HTTPException(status_code=400, detail="Số đếm không được âm")

    san_pham = {
        p.id: p
        for p in db.query(models.Product)
        .filter(models.Product.shop_id == shop_id, models.Product.id.in_(ids))
        .all()
    }

    da_dieu_chinh: List[Dict[str, Any]] = []
    bo_qua: List[Dict[str, Any]] = []
    khong_doi = 0

    for it in items:
        prod = san_pham.get(it.product_id)
        if prod is None:
            bo_qua.append({
                "product_id": it.product_id,
                "name": None,
                "ly_do": "Sản phẩm không còn tồn tại trong cửa hàng",
            })
            continue

        ton_hien_tai = prod.stock or 0
        if ton_hien_tai != it.stock_snapshot:
            bo_qua.append({
                "product_id": prod.id,
                "name": prod.name,
                "ly_do": (
                    f"Tồn kho đã đổi từ {it.stock_snapshot} thành {ton_hien_tai} "
                    "trong lúc kiểm kê. Vui lòng đếm lại sản phẩm này."
                ),
            })
            continue

        if ton_hien_tai == it.counted:
            khong_doi += 1
            continue

        lech = it.counted - ton_hien_tai
        prod.stock = it.counted
        da_dieu_chinh.append({
            "product_id": prod.id,
            "name": prod.name,
            "truoc": ton_hien_tai,
            "sau": it.counted,
            "lech": lech,
        })

    db.commit()

    if da_dieu_chinh:
        tong_lech = sum(d["lech"] for d in da_dieu_chinh)
        # Liệt kê tối đa 10 sản phẩm để một phiếu kiểm kê lớn không sinh ra
        # dòng log dài vô hạn; con số tổng vẫn phản ánh đủ.
        chi_tiet = ", ".join(
            f"{d['name']}: {d['truoc']}->{d['sau']}" for d in da_dieu_chinh[:10]
        )
        if len(da_dieu_chinh) > 10:
            chi_tiet += f" (và {len(da_dieu_chinh) - 10} SP khác)"
        log_system_action(
            db,
            current_user.id,
            "STOCKTAKE",
            f"Kiểm kê shop {shop_id}: điều chỉnh {len(da_dieu_chinh)} SP, "
            f"lệch tổng {tong_lech:+d}. {chi_tiet}",
        )

    return {
        "da_dieu_chinh": da_dieu_chinh,
        "bo_qua": bo_qua,
        "khong_doi": khong_doi,
        "tong_lech": sum(d["lech"] for d in da_dieu_chinh),
    }


_ADJUST_STOCK = text(
    "UPDATE products SET stock = stock + :delta "
    "WHERE id = :product_id AND stock + :delta >= 0"
)


def adjust_stock(
    db: Session, current_user: models.User, product_id: int, delta: int
) -> Dict[str, Any]:
    """Nhập (delta > 0) hoặc xuất (delta < 0) kho theo số lượng thay đổi.

    Dùng UPDATE nguyên tử `stock = stock + delta` thay vì đọc-rồi-ghi, nên
    nhiều thao tác kho / bán hàng chạy song song không ghi đè lẫn nhau. Điều
    kiện `stock + delta >= 0` nằm ngay trong câu UPDATE -> tồn kho không bao
    giờ âm; nếu xuất quá số đang có, rowcount = 0 và ta báo lỗi.
    """
    prod = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not prod:
        raise HTTPException(status_code=404, detail="Sản phẩm không tồn tại")
    require_shop_access(db, prod.shop_id, current_user)
    require_staff_permission(current_user, PERMISSION_INVENTORY)

    if delta == 0:
        raise HTTPException(status_code=400, detail="Số lượng thay đổi phải khác 0")

    result = db.execute(_ADJUST_STOCK, {"delta": delta, "product_id": product_id})
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail=f"Không đủ tồn kho để xuất {abs(delta)} (hiện còn {prod.stock})",
        )
    db.commit()
    db.refresh(prod)

    hanh_dong = "Nhập" if delta > 0 else "Xuất"
    log_system_action(
        db,
        current_user.id,
        "ADJUST_STOCK",
        f"{hanh_dong} kho SP '{prod.name}' ({prod.code}): "
        f"{'+' if delta > 0 else ''}{delta} -> tồn {prod.stock}",
    )
    return {"id": prod.id, "stock": prod.stock, "delta": delta}


def toggle_product_status(
    db: Session, current_user: models.User, product_id: int
) -> Dict[str, bool]:
    prod = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not prod:
        raise HTTPException(status_code=404, detail="Sản phẩm không tồn tại")
    require_shop_access(db, prod.shop_id, current_user)
    require_staff_permission(current_user, PERMISSION_INVENTORY)
    prod.is_active = not prod.is_active
    db.commit()
    log_system_action(
        db,
        current_user.id,
        "TOGGLE_PRODUCT_STATUS",
        f"Đổi trạng thái SP '{prod.name}' ({prod.code}): {'Hiện' if prod.is_active else 'Ẩn'}",
    )
    return {"is_active": prod.is_active}


def delete_product(db: Session, current_user: models.User, product_id: int) -> Dict[str, str]:
    prod = db.query(models.Product).filter(models.Product.id == product_id).first()
    if not prod:
        raise HTTPException(status_code=404, detail="Sản phẩm không tồn tại")
    require_shop_access(db, prod.shop_id, current_user)
    require_staff_permission(current_user, PERMISSION_INVENTORY)
    name, code = prod.name, prod.code
    db.delete(prod)
    db.commit()
    log_system_action(db, current_user.id, "DELETE_PRODUCT", f"Xóa SP '{name}' ({code})")
    return {"msg": "Deleted"}
