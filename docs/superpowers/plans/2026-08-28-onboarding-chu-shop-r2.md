# Onboarding Chủ shop R2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Use `superpowers:test-driven-development` for every behavior change and `superpowers:verification-before-completion` before claiming completion.

**Goal:** Đưa một tài khoản SELLER mới từ lần vào `/seller` đầu tiên tới một đơn `PAID` hoặc `DEBT` bằng ba bước ngắn, có thể bỏ qua và quay lại, không tạo dữ liệu mẫu và không làm gián đoạn tài khoản cũ.

**Architecture:** Giữ onboarding trong Seller/POS hiện tại. Backend nới hợp đồng tạo cửa hàng tối thiểu, tạo danh mục hệ thống trong cùng transaction với sản phẩm đầu tiên và chặn VietQR khi chưa đủ tài khoản ngân hàng. Frontend thêm một controller nhỏ, state bền vững lấy từ `GET /api/onboarding/{shop_id}`, còn lựa chọn “Để sau” chỉ nằm trong `localStorage` theo tài khoản. Không thêm route, bảng, migration, framework hay dependency.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, vanilla HTML/CSS/JavaScript, pytest, Node `assert`/`vm`.

**Approved spec:** `docs/superpowers/specs/2026-08-28-onboarding-chu-shop-r2-design.md`

## Guardrails

- Giữ `GEMINI_ENABLED=false` và `TTS_SERVER_ENABLED=false`; không gọi provider, bật billing hay deploy.
- Không tạo shop, sản phẩm, tồn kho, ca hoặc đơn mẫu.
- Không tự mở ca, tự bán hàng hay để Trợ lý thực hiện mutation nghiệp vụ.
- Chỉ SELLER có `GET /shops == []` và chưa bấm “Để sau” mới tự thấy màn chào.
- Completion R2 là `sale_completed === true`, không dùng `complete` của Onboarding R1.
- Mọi mutation setup khi offline phải thất bại rõ ràng, giữ nguyên dữ liệu nhập và cho retry; không đưa vào hàng đợi offline.
- Worktree đã bẩn trước khi bắt đầu. Trước mỗi commit phải dùng `git diff --` với đúng các path liệt kê trong mục **Files** của task; không sửa hoặc stage thay đổi ngoài phạm vi.
- Sau mỗi task hoàn tất, cập nhật `C:\Users\nguye\OneDrive\Desktop\FSellingV2\PROGRESS.md`. File này nằm ngoài Git repo ứng dụng nên không stage vào commit.

## File and Responsibility Map

### Create

- `static/js/onboarding-r2.js` — controller Seller R2, state machine, dismissal key, submit/retry và resume card.
- `static/css/onboarding-r2.css` — style có scope cho màn chào Seller, resume card, POS success và VietQR hint.
- `tests/test_onboarding_r2.py` — hợp đồng backend và static integration R2.
- `tests/js/onboarding-r2-ui.test.js` — kiểm thử state/dismissal và chống double-submit bằng Node, không thêm test framework.

### Modify

- `fselling/schemas/shop.py` — cho phép các trường ngân hàng vắng mặt trong request.
- `fselling/services/shop_service.py` — chỉ bắt buộc tên + điện thoại; nhóm ngân hàng all-or-none.
- `fselling/services/payment_service.py` — capability helper và mã lỗi VietQR ổn định.
- `fselling/services/order_service.py` — fail trước mutation cho transfer thiếu ngân hàng; không sinh QR cho cash/debt.
- `fselling/routers/products.py` — `category_id` tùy chọn duy nhất ở create endpoint.
- `fselling/services/catalog_service.py` — resolve/tạo `Chưa phân loại` trong transaction tạo sản phẩm.
- `static/seller.html` — shell ba bước, resume card, local help và asset links có version.
- `static/js/seller.js` — hook controller vào `init`, callback cập nhật shop, POS query và deep-link cài đặt ngân hàng.
- `static/js/locales/seller.js` — nội dung `seller.first_run.*` tiếng Việt/Anh.
- `static/pos.html` — VietQR hint, first-sale success và asset links.
- `static/js/pos.js` — khóa phương thức VietQR khi thiếu cấu hình và hiện success sau hóa đơn.
- `static/js/locales/pos.js` — nội dung VietQR/setup/success tiếng Việt/Anh.

### Explicitly unchanged

- `GET /api/onboarding/{shop_id}` và năm fact durable của R1.
- Database schema và migration.
- Auth/permission model, offline order queue, Assistant mutation boundary.

---

## Task 1: Minimum Shop Contract

**Files:**

- Modify: `fselling/schemas/shop.py`
- Modify: `fselling/services/shop_service.py`
- Test: `tests/test_onboarding_r2.py`

- [ ] **Step 1: Write failing API tests for the approved minimum and bank-group rule**

```python
import pytest

from conftest import SHOP_PAYLOAD, auth, new_seller


@pytest.fixture
def minimum_shop(client):
    username, token = new_seller(client)
    response = client.post(
        "/api/shops",
        json={"name": "Tạp hóa An", "phone": "0774867057"},
        headers=auth(token),
    )
    assert response.status_code == 200, response.text
    return {
        "username": username,
        "token": token,
        "shop_id": response.json()["id"],
    }


def test_owner_can_create_minimum_real_shop(client):
    _, token = new_seller(client)
    response = client.post(
        "/api/shops",
        json={"name": "Tạp hóa An", "phone": "0774867057"},
        headers=auth(token),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == "Tạp hóa An"
    assert body["phone"] == "0774867057"
    assert body["bank_code"] == ""
    assert body["bank_account_no"] == ""
    assert body["bank_account_name"] == ""


def test_full_shop_payload_remains_compatible(client):
    _, token = new_seller(client)
    response = client.post("/api/shops", json=SHOP_PAYLOAD, headers=auth(token))
    assert response.status_code == 200, response.text
    assert response.json()["bank_code"] == SHOP_PAYLOAD["bank_code"]


def test_partial_bank_group_is_rejected(client):
    _, token = new_seller(client)
    response = client.post(
        "/api/shops",
        json={
            "name": "Tạp hóa An",
            "phone": "0774867057",
            "bank_code": "VCB",
        },
        headers=auth(token),
    )
    assert response.status_code == 400
    assert "ngân hàng" in str(response.json()["detail"]).lower()
```

- [ ] **Step 2: Run the focused tests and confirm the minimum payload fails first**

Run: `python -m pytest tests/test_onboarding_r2.py -k "minimum_real_shop or full_shop_payload or partial_bank_group" -q`

Expected: minimum request fails with `422`; compatibility test passes; partial group is not yet validated as one group.

- [ ] **Step 3: Make bank fields optional at the schema boundary**

```python
class ShopCreate(BaseModel):
    name: str
    business_address: Optional[str] = None
    tax_code: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    bank_account_no: Optional[str] = None
    bank_account_name: Optional[str] = None
    bank_code: Optional[str] = None
```

- [ ] **Step 4: Validate only name/phone and require bank fields all-or-none**

```python
_REQUIRED_FIELDS = [
    ("name", "Tên cửa hàng không được để trống"),
    ("phone", "Số điện thoại không được để trống"),
]
_BANK_FIELDS = frozenset({"bank_code", "bank_account_no", "bank_account_name"})


def _clean_and_validate(shop: ShopCreate) -> Dict[str, str]:
    data = {
        "name": (shop.name or "").strip(),
        "business_address": (shop.business_address or "").strip(),
        "tax_code": (shop.tax_code or "").strip(),
        "phone": (shop.phone or "").strip(),
        "email": (shop.email or "").strip(),
        "bank_account_no": (shop.bank_account_no or "").strip(),
        "bank_account_name": (shop.bank_account_name or "").strip(),
        "bank_code": (shop.bank_code or "").strip(),
    }
    for field, message in _REQUIRED_FIELDS:
        if not data[field]:
            raise HTTPException(status_code=400, detail=tr(message))
    bank_values = [data[field] for field in _BANK_FIELDS]
    if any(bank_values) and not all(bank_values):
        raise HTTPException(
            status_code=400,
            detail=tr("Vui lòng nhập đủ ngân hàng, số tài khoản và tên chủ tài khoản"),
        )
    return data
```

- [ ] **Step 5: Run shop/authorization/QR account-fence regressions**

Run: `python -m pytest tests/test_onboarding_r2.py tests/test_authorization.py tests/test_qr_account_change_fence.py tests/test_subscriptions.py -q`

Expected: all pass; full existing shop setup and account-change fence remain intact.

- [ ] **Step 6: Record progress and commit only Task 1 files**

```powershell
git diff -- fselling/schemas/shop.py fselling/services/shop_service.py tests/test_onboarding_r2.py
git add fselling/schemas/shop.py fselling/services/shop_service.py tests/test_onboarding_r2.py
git commit -m "Allow minimum owner shop setup"
```

---

## Task 2: Fail-Closed VietQR Capability

**Files:**

- Modify: `fselling/services/payment_service.py`
- Modify: `fselling/services/order_service.py`
- Modify: `tests/test_onboarding_r2.py`

- [ ] **Step 1: Add failing tests for transfer, cash and durable non-mutation**

```python
from fselling import models
from fselling.core.database import SessionLocal
from conftest import create_category, create_product


@pytest.fixture
def minimum_shop_with_product(client, minimum_shop):
    category_id = create_category(
        client,
        minimum_shop["token"],
        minimum_shop["shop_id"],
        "Đồ ăn nhanh",
    )
    product = create_product(
        client,
        minimum_shop["token"],
        minimum_shop["shop_id"],
        "Mì gói",
        15000,
        7,
        category_id,
    )
    return {
        **minimum_shop,
        "product_id": product["id"],
        "product_name": product["name"],
        "opening_stock": 7,
    }


def test_transfer_without_bank_fails_before_order_or_stock_mutation(
    client, minimum_shop_with_product
):
    ctx = minimum_shop_with_product
    response = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={
            "items": [{"product_name": ctx["product_name"], "price": 1, "quantity": 1}],
            "payment_method": "transfer",
        },
        headers=auth(ctx["token"]),
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "QR_BANK_ACCOUNT_NOT_CONFIGURED"
    with SessionLocal() as db:
        product = db.query(models.Product).filter_by(id=ctx["product_id"]).one()
        assert product.stock == ctx["opening_stock"]
        assert db.query(models.Order).filter_by(shop_id=ctx["shop_id"]).count() == 0


def test_cash_without_bank_still_creates_order_without_qr(client, minimum_shop_with_product):
    ctx = minimum_shop_with_product
    response = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={
            "items": [{"product_name": ctx["product_name"], "price": 1, "quantity": 1}],
            "payment_method": "cash",
        },
        headers=auth(ctx["token"]),
    )
    assert response.status_code == 200, response.text
    assert response.json()["qr_url"] is None


def test_debt_without_bank_still_creates_order_without_qr(client, minimum_shop_with_product):
    ctx = minimum_shop_with_product
    customer = client.post(
        f"/api/customers/{ctx['shop_id']}",
        json={"name": "Cô Lan", "phone": "0900000001"},
        headers=auth(ctx["token"]),
    )
    assert customer.status_code == 200, customer.text
    response = client.post(
        f"/api/orders/{ctx['shop_id']}",
        json={
            "items": [{"product_name": ctx["product_name"], "price": 1, "quantity": 1}],
            "payment_method": "debt",
            "customer_id": customer.json()["id"],
        },
        headers=auth(ctx["token"]),
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "DEBT"
    assert response.json()["qr_url"] is None
```

- [ ] **Step 2: Run and observe the unsafe legacy QR behavior**

Run: `python -m pytest tests/test_onboarding_r2.py -k "without_bank" -q`

Expected: transfer incorrectly succeeds and/or cash receives an invalid VietQR URL.

- [ ] **Step 3: Add one canonical capability guard**

```python
from fastapi import HTTPException

from ..core.i18n import tr

ERROR_QR_BANK_ACCOUNT_NOT_CONFIGURED = "QR_BANK_ACCOUNT_NOT_CONFIGURED"
_TRANSFER_FIELDS = ("bank_code", "bank_account_no", "bank_account_name")


def has_transfer_account(shop: models.Shop) -> bool:
    return all((getattr(shop, field, None) or "").strip() for field in _TRANSFER_FIELDS)


def require_transfer_account(shop: models.Shop) -> None:
    if has_transfer_account(shop):
        return
    raise HTTPException(
        status_code=409,
        detail={
            "code": ERROR_QR_BANK_ACCOUNT_NOT_CONFIGURED,
            "message": tr("Chưa thiết lập tài khoản nhận chuyển khoản"),
        },
    )
```

- [ ] **Step 4: Guard transfer after the shop write lock but before inventory/order mutation**

In `create_order`, immediately after the locked shop is refreshed and before resolving products, vouchers, loyalty or stock:

```python
if order.payment_method == "transfer":
    payment_service.require_transfer_account(shop)
```

Change only the v0 response fallback; QR intents keep their current contract:

```python
"qr_url": (
    None
    if (
        qr_intent is not None
        or existing.payment_method != "transfer"
        or not payment_service.has_transfer_account(shop)
    )
    else payment_service.build_qr_url(shop, total, existing.id)
),
```

`build_qr_url` has only this production caller. Do not add a second guard there:
the order write boundary produces the stable 409 for new transfer attempts,
while an old/idempotent order whose current shop account was later cleared
returns `qr_url: null` instead of manufacturing a broken URL.

- [ ] **Step 5: Verify payment, intent and order regressions**

Run: `python -m pytest tests/test_onboarding_r2.py tests/test_orders.py tests/test_qr_intent_issuance.py tests/test_qr_account_change_fence.py -q`

Expected: all pass; configured transfer continues returning its existing v0/v1 contract, cash/debt do not generate QR.

- [ ] **Step 6: Record progress and commit only Task 2 files**

```powershell
git diff -- fselling/services/payment_service.py fselling/services/order_service.py tests/test_onboarding_r2.py
git add fselling/services/payment_service.py fselling/services/order_service.py tests/test_onboarding_r2.py
git commit -m "Guard VietQR until bank setup"
```

---

## Task 3: Transactional Default Category for the First Product

**Files:**

- Modify: `fselling/routers/products.py`
- Modify: `fselling/services/catalog_service.py`
- Modify: `tests/test_onboarding_r2.py`

- [ ] **Step 1: Add failing tests for omitted category, reuse and rollback**

```python
DEFAULT_CATEGORY_NAME = "Chưa phân loại"


def _post_product_without_category(client, ctx, name, stock=7):
    return client.post(
        "/api/products",
        params={"shop_id": ctx["shop_id"]},
        data={"name": name, "price": 15000, "stock": stock},
        headers=auth(ctx["token"]),
    )


def test_first_product_without_category_creates_and_reuses_default(client, minimum_shop):
    first = _post_product_without_category(client, minimum_shop, "Mì gói", stock=7)
    second = _post_product_without_category(client, minimum_shop, "Nước suối", stock=3)
    assert first.status_code == second.status_code == 200
    assert first.json()["category_id"] == second.json()["category_id"]
    with SessionLocal() as db:
        categories = db.query(models.Category).filter_by(
            shop_id=minimum_shop["shop_id"], name=DEFAULT_CATEGORY_NAME
        ).all()
        assert len(categories) == 1


def test_failed_first_product_rolls_back_lazy_default_category(client, minimum_shop):
    explicit_id = create_category(
        client, minimum_shop["token"], minimum_shop["shop_id"], "Đồ uống"
    )
    create_product(
        client, minimum_shop["token"], minimum_shop["shop_id"],
        "Trùng tên", 10000, 2, explicit_id,
    )
    failed = _post_product_without_category(client, minimum_shop, "Trùng tên")
    assert failed.status_code == 400
    with SessionLocal() as db:
        assert db.query(models.Category).filter_by(
            shop_id=minimum_shop["shop_id"], name=DEFAULT_CATEGORY_NAME
        ).count() == 0
```

- [ ] **Step 2: Run the focused tests and confirm FastAPI rejects missing category**

Run: `python -m pytest tests/test_onboarding_r2.py -k "product_without_category or failed_first_product" -q`

Expected: create requests fail with `422`; no default category exists.

- [ ] **Step 3: Make category optional only on product creation**

```python
from typing import Optional

category_id: Optional[int] = Form(None)
```

Keep update-product `category_id: int = Form(...)` unchanged.

- [ ] **Step 4: Resolve the category inside the existing product transaction**

```python
DEFAULT_CATEGORY_NAME = "Chưa phân loại"


def _resolve_create_category_id(
    db: Session, shop_id: int, category_id: Optional[int]
) -> int:
    if category_id is not None:
        _kiem_danh_muc_thuoc_shop(db, shop_id, category_id)
        return category_id
    category = (
        db.query(models.Category)
        .filter(
            models.Category.shop_id == shop_id,
            models.Category.name == DEFAULT_CATEGORY_NAME,
        )
        .first()
    )
    if category is None:
        category = models.Category(
            shop_id=shop_id,
            name=DEFAULT_CATEGORY_NAME,
            is_active=True,
        )
        db.add(category)
        db.flush()
    return category.id
```

In `create_product`, replace the direct membership check with:

```python
resolved_category_id = _resolve_create_category_id(db, shop_id, category_id)
```

Use `resolved_category_id` in the `Product`. Do not commit the category separately; the existing `_commit_bat_trung(db)` must atomically commit or roll back both records.

- [ ] **Step 5: Verify catalog ownership, duplicate and import regressions**

Run: `python -m pytest tests/test_onboarding_r2.py tests/test_product_update.py tests/test_product_code_unique.py tests/test_integrity_400.py tests/test_authorization.py tests/test_product_import_r1.py -q`

Expected: all selected tests pass; explicit category ownership stays enforced.

- [ ] **Step 6: Record progress and commit only Task 3 files**

```powershell
git diff -- fselling/routers/products.py fselling/services/catalog_service.py tests/test_onboarding_r2.py
git add fselling/routers/products.py fselling/services/catalog_service.py tests/test_onboarding_r2.py
git commit -m "Create first product without category setup"
```

---

## Task 4: Seller R2 Shell and Pure State Model

**Files:**

- Create: `static/js/onboarding-r2.js`
- Create: `static/css/onboarding-r2.css`
- Create: `tests/js/onboarding-r2-ui.test.js`
- Modify: `static/seller.html`
- Modify: `static/js/locales/seller.js`
- Modify: `tests/test_onboarding_r2.py`

- [ ] **Step 1: Add failing static-contract and pure-state tests**

```python
def test_seller_hosts_r2_assets_and_accessible_shell():
    html = open("static/seller.html", encoding="utf-8").read()
    assert 'id="firstRunShell"' in html
    assert 'id="firstRunResumeCard"' in html
    assert 'id="firstRunShopForm"' in html
    assert 'id="firstRunProductForm"' in html
    assert "/css/onboarding-r2.css?v=20260828-r2" in html
    assert "/js/onboarding-r2.js?v=20260828-r2" in html
    assert html.index("/js/onboarding-r2.js") < html.index("/js/seller.js")


def test_r2_uses_new_keys_without_restoring_r1_checklist():
    locale = open("static/js/locales/seller.js", encoding="utf-8").read()
    assert "seller.first_run.step_shop.title" in locale
    assert "seller.onboarding." not in locale
```

Create `tests/js/onboarding-r2-ui.test.js` with these assertions:

```javascript
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const source = fs.readFileSync('static/js/onboarding-r2.js', 'utf8');
const start = source.indexOf('// ONBOARDING_R2_STATE_START');
const end = source.indexOf('// ONBOARDING_R2_STATE_END');
assert(start >= 0 && end > start);
const context = {};
vm.runInNewContext(`${source.slice(start, end)}; this.key = firstRunDismissKey; this.next = firstRunNextAction;`, context);

assert.strictEqual(
  context.key('chu shop a'),
  'fselling.onboarding.r2.dismissed:chu%20shop%20a'
);
assert.strictEqual(context.next([], null), 'shop');
assert.strictEqual(context.next([{ id: 9 }], null), null);
assert.strictEqual(context.next([{ id: 9 }], { product_created: false }), 'product');
assert.strictEqual(context.next([{ id: 9 }], { product_created: true, sale_completed: false }), 'sale');
assert.strictEqual(context.next([{ id: 9 }], { product_created: true, sale_completed: true }), null);
```

- [ ] **Step 2: Run and confirm the assets/state model do not exist yet**

Run: `python -m pytest tests/test_onboarding_r2.py -k "seller_hosts or new_keys" -q; node tests/js/onboarding-r2-ui.test.js`

Expected: failing tests for missing files/markup/functions.

- [ ] **Step 3: Add the minimal pure state block and controller boundary**

At the top of `static/js/onboarding-r2.js`:

```javascript
// ONBOARDING_R2_STATE_START
function firstRunDismissKey(username) {
    return `fselling.onboarding.r2.dismissed:${encodeURIComponent(username || '')}`;
}

function firstRunNextAction(shops, progress) {
    if (!Array.isArray(shops) || shops.length === 0) return 'shop';
    if (!progress) return null;
    if (progress.product_created !== true) return 'product';
    if (progress.sale_completed !== true) return 'sale';
    return null;
}
// ONBOARDING_R2_STATE_END

window.FSellingOnboardingR2 = (() => {
    let context = null;
    let progress = null;
    let loadError = null;
    let submitting = false;

    async function initialize(nextContext) {
        context = nextContext;
        await refresh();
        return shouldOwnFirstRunScreen();
    }

    async function refresh() {
        try {
            progress = context.shopId
                ? await apiCall(`/onboarding/${context.shopId}`)
                : null;
            loadError = null;
        } catch (error) {
            progress = null;
            loadError = error;
        }
        render();
    }

    function rerender() { render(); }

    return Object.freeze({ initialize, refresh, rerender });
}());
```

The implementation may add private helpers inside the IIFE, but the public API remains exactly `initialize`, `refresh`, `rerender`. When an existing shop's progress request fails, render a compact localized error with a retry button. Never infer `product` or `sale` from missing progress, and never reopen the dedicated welcome shell for that failure.

- [ ] **Step 4: Add semantic HTML for one visible task at a time**

Add a hidden `section#firstRunShell` before the normal management shell and add
`id="sellerAppShell"` to the existing `.seller-app-shell`. The screen must contain:

- `aria-live="polite"` progress text (“Bước 1/3”, “Bước 2/3”, “Bước 3/3”).
- `form#firstRunShopForm` with only `firstRunShopName` and `firstRunShopPhone`.
- `form#firstRunProductForm` with only `firstRunProductName`, `firstRunProductPrice`, `firstRunProductStock`; stock has no `value="100"` or other default.
- `section#firstRunProductSummary` and button `firstRunOpenPos`.
- always-visible `button#firstRunSkip` and `button#firstRunHelp`.
- `section#firstRunLocalHelp` with deterministic help plus Zalo/phone, never an AI answer.
- a hidden `aside#firstRunResumeCard` inside the dashboard, containing exactly one action button.

- [ ] **Step 5: Add scoped responsive/accessibility CSS and bilingual copy**

Use only `.first-run-*` selectors. Required behavior:

```css
.first-run-shell[hidden], .first-run-resume[hidden] { display: none !important; }
.first-run-shell { min-height: calc(100dvh - 4rem); }
.first-run-card { max-width: 44rem; margin-inline: auto; }
.first-run-actions { display: flex; flex-wrap: wrap; gap: .75rem; }
.first-run-actions button { min-height: 44px; }
@media (max-width: 640px) {
  .first-run-actions > * { width: 100%; }
}
@media (prefers-reduced-motion: reduce) {
  .first-run-shell * { scroll-behavior: auto; transition: none !important; }
}
```

Locale keys are under `seller.first_run.*`; exact Vietnamese titles follow the approved spec. English maps stored category name `Chưa phân loại` to visible “Uncategorized” without changing the stored value.

- [ ] **Step 6: Preserve existing asset-version assertions while adding an R2 suffix**

Keep existing Seller asset version prefixes and append `&amp;onboarding=20260828-r2`; add new files with `?v=20260828-r2`. This lets legacy tests continue matching the old prefix while invalidating browser caches for the integration.

- [ ] **Step 7: Run syntax, Node, i18n and static contract tests**

Run:

```powershell
node --check static/js/onboarding-r2.js
node tests/js/onboarding-r2-ui.test.js
python -m pytest tests/test_onboarding_r2.py tests/test_onboarding_r1.py tests/test_i18n.py tests/test_contract.py -q
```

Expected: all pass; R1 board remains absent.

- [ ] **Step 8: Record progress and commit only Task 4 files**

```powershell
git diff -- static/js/onboarding-r2.js static/css/onboarding-r2.css static/seller.html static/js/locales/seller.js tests/test_onboarding_r2.py tests/js/onboarding-r2-ui.test.js
git add static/js/onboarding-r2.js static/css/onboarding-r2.css static/seller.html static/js/locales/seller.js tests/test_onboarding_r2.py tests/js/onboarding-r2-ui.test.js
git commit -m "Add owner onboarding R2 shell"
```

---

## Task 5: Connect Seller Data and Real Mutations

**Files:**

- Modify: `static/js/onboarding-r2.js`
- Modify: `static/js/seller.js`
- Modify: `static/seller.html`
- Modify: `tests/js/onboarding-r2-ui.test.js`
- Modify: `tests/test_onboarding_r2.py`

- [ ] **Step 1: Add failing integration contracts**

```python
def test_seller_initializes_r2_after_shop_discovery():
    source = open("static/js/seller.js", encoding="utf-8").read()
    assert "FSellingOnboardingR2.initialize" in source
    assert "onboarding=r2" in source
    assert "setup=bank" in source


def test_seller_minimum_shop_validation_replaces_full_required_list():
    source = open("static/js/seller.js", encoding="utf-8").read()
    save_chunk = source[source.index("async function saveShop"):source.index("async function toggleShop")]
    assert "shopName" in save_chunk and "shopPhone" in save_chunk
    assert "Vui lòng nhập đầy đủ thông tin" not in save_chunk


def test_default_category_is_localized_only_at_render_time():
    source = open("static/js/seller.js", encoding="utf-8").read()
    assert "function displayCategoryName" in source
    assert "Chưa phân loại" in source
    assert "seller.first_run.default_category" in source
```

Extend the Node source-contract test with the exact single-flight and recovery
guards; the browser acceptance in Task 7 proves their runtime behavior:

```javascript
const controllerSource = fs.readFileSync('static/js/onboarding-r2.js', 'utf8');
assert(controllerSource.includes('if (submitting) return;'));
assert(controllerSource.includes('submitting = true;'));
assert(controllerSource.includes('finally {'));
assert(controllerSource.includes('submitting = false;'));
assert(controllerSource.includes('showInlineError(form'));
assert(!controllerSource.includes('form.reset()'));
```

- [ ] **Step 2: Run the tests and confirm integration hooks are absent**

Run: `python -m pytest tests/test_onboarding_r2.py -k "seller_initializes or minimum_shop_validation" -q; node tests/js/onboarding-r2-ui.test.js`

Expected: missing hook/query and submission behavior failures.

- [ ] **Step 3: Lock the controller context passed by `seller.js`**

After `/shops` resolves, call:

```javascript
const firstRunOwnsScreen = await window.FSellingOnboardingR2.initialize({
    role: MY_ROLE,
    username: localStorage.getItem('username') || '',
    shops: allShops,
    shopId: currentShopId,
    onShopCreated(shop) {
        allShops = [shop];
        currentShopId = shop.id;
        dashboardShopId = shop.id;
        localStorage.setItem('currentShopId', shop.id);
        renderShopsList();
        renderShopSelectors();
    },
    onOpenPos(shopId) {
        goToPOS(shopId, true);
    },
    onOpenAssistant() {
        switchTab('assistant');
    },
});
if (firstRunOwnsScreen) return;
```

Use the actual existing username variable or derive it from the already decoded auth state; do not add another `/me` request solely for the dismissal key.

- [ ] **Step 4: Implement exact trigger, dismissal and resume rules**

```javascript
function shouldOwnFirstRunScreen() {
    return context.role === 'SELLER'
        && context.shops.length === 0
        && localStorage.getItem(firstRunDismissKey(context.username)) !== '1';
}

function setFirstRunMode(active) {
    document.getElementById('firstRunShell').hidden = !active;
    document.getElementById('sellerAppShell').hidden = active;
}
```

- “Để sau” writes exactly value `"1"`, hides the dedicated shell and shows management/resume.
- Existing owners never get the dedicated shell.
- Resume fetches `/onboarding/{shop_id}` and shows only `product` or `sale`; it hides immediately on `sale_completed === true`.
- No shop + dismissed browser shows resume action “Tạo cửa hàng”.
- `complete` and `shift_closed` never decide R2 completion.

- [ ] **Step 5: Submit real shop/product with field-preserving recovery**

For both forms use this structure:

```javascript
if (submitting) return;
submitting = true;
setBusy(form, true);
try {
    const created = await apiCall(endpoint, options);
    clearInlineError(form);
    advanceWith(created);
} catch (error) {
    showInlineError(form, error.message || t('seller.first_run.retry_error'));
} finally {
    submitting = false;
    setBusy(form, false);
}
```

The exact API calls are:

```javascript
const shop = await apiCall('/shops', 'POST', { name, phone });

const formData = new FormData();
formData.set('name', name);
formData.set('price', price);
formData.set('stock', stock);
const product = await apiCall(
    `/products?shop_id=${context.shopId}`,
    'POST',
    formData
);
```

After shop creation, the controller sets `context.shops = [shop]` and
`context.shopId = shop.id` before rendering step 2 and invoking
`context.onShopCreated(shop)`. Do not reset inputs in `catch`. The product
request deliberately omits `category_id` so Task 3 owns the default-category
transaction.

- [ ] **Step 6: Preserve old management forms under the new backend contract**

Update `saveShop()` to require name + phone only and validate the bank group all-or-none before POST/PUT. Do not remove advanced fields. Change `goToPOS` to:

```javascript
function goToPOS(id, onboardingR2 = false) {
    localStorage.setItem('currentShopId', id);
    window.location.href = onboardingR2
        ? '/pos?tour=sale&onboarding=r2'
        : '/pos';
}
```

In `static/seller.html`, keep `required` and the `*` label only for shop name
and phone. Address, tax code, email and all three bank fields remain visible
but must lose both the `required` attribute and required wording. The bank
group is optional as a whole and is rejected by `saveShop()`/backend only when
partially filled.

On `?setup=bank`, after a valid current shop loads: open Settings, open the existing edit-shop form, focus `bankCode`, then remove only `setup` from the URL with `history.replaceState` so refresh does not reopen it.

Add one display-only helper and use it in Seller category options/table:

```javascript
function displayCategoryName(name) {
    return name === 'Chưa phân loại'
        ? t('seller.first_run.default_category')
        : name;
}
```

Never rewrite the stored category name or prefill the edit form with the
localized label.

- [ ] **Step 7: Implement contextual help without provider calls**

- Before a shop exists, “Hỏi Trợ lý” expands local, deterministic instructions plus Zalo/phone.
- After a shop exists, it may additionally offer “Mở Trợ lý” using `onOpenAssistant`; it never submits a prompt automatically.
- Offline/error help remains local and available.

- [ ] **Step 8: Verify Seller behavior and surrounding frontend contracts**

Run:

```powershell
node --check static/js/seller.js
node --check static/js/onboarding-r2.js
node tests/js/onboarding-r2-ui.test.js
python -m pytest tests/test_onboarding_r2.py tests/test_onboarding_r1.py tests/test_seller_sidebar_ui.py tests/test_assistant_navigation_r1.py tests/test_assistant_guided_tasks_r1.py -q
```

Expected: all pass; no old 5-row onboarding board returns.

- [ ] **Step 9: Record progress and commit only Task 5 files**

```powershell
git diff -- static/js/onboarding-r2.js static/js/seller.js static/seller.html tests/js/onboarding-r2-ui.test.js tests/test_onboarding_r2.py
git add static/js/onboarding-r2.js static/js/seller.js static/seller.html tests/js/onboarding-r2-ui.test.js tests/test_onboarding_r2.py
git commit -m "Connect owner onboarding to real setup"
```

---

## Task 6: POS VietQR Gating and First-Sale Success

**Files:**

- Modify: `static/pos.html`
- Modify: `static/js/pos.js`
- Modify: `static/js/locales/pos.js`
- Modify: `static/css/onboarding-r2.css`
- Modify: `tests/test_qr_pos_ui.py`
- Modify: `tests/test_onboarding_r2.py`

- [ ] **Step 1: Add failing POS contract tests**

```python
def test_pos_exposes_bank_setup_hint_and_first_sale_success():
    html = open("static/pos.html", encoding="utf-8").read()
    source = open("static/js/pos.js", encoding="utf-8").read()
    assert 'id="qrSetupHint"' in html
    assert 'id="firstRunSaleSuccess"' in html
    assert "QR_BANK_ACCOUNT_NOT_CONFIGURED" in source
    assert "onboarding" in source and "sale_completed" not in source
    assert "PAID" in source and "DEBT" in source
    assert "/seller?setup=bank" in source


def test_pos_r2_asset_versions_are_cache_busted():
    html = open("static/pos.html", encoding="utf-8").read()
    assert "/css/onboarding-r2.css?v=20260828-r2" in html
    assert "onboarding=20260828-r2" in html
```

Also extend `tests/test_qr_pos_ui.py` to assert that `setMethod('transfer')` checks current-shop bank capability before applying the method.

- [ ] **Step 2: Run and confirm missing POS behavior**

Run: `python -m pytest tests/test_onboarding_r2.py tests/test_qr_pos_ui.py -q`

Expected: new markup/gating/success assertions fail; existing QR tests still pass.

- [ ] **Step 3: Add current-shop bank capability and safe payment fallback**

```javascript
function currentShopHasTransferAccount() {
    const shop = allShops.find(item => Number(item.id) === Number(currentShopId));
    return ['bank_code', 'bank_account_no', 'bank_account_name']
        .every(field => String(shop?.[field] || '').trim());
}

function displayPosCategoryName(name) {
    return name === 'Chưa phân loại'
        ? dich('pos.category.uncategorized')
        : name;
}

function updateTransferCapability() {
    const available = currentShopHasTransferAccount();
    const button = document.getElementById('btnMethodQR');
    button.disabled = !available;
    button.setAttribute('aria-disabled', String(!available));
    document.getElementById('qrSetupHint').hidden = available;
    if (!available && paymentMethod === 'transfer') {
        apDungPhuongThucThanhToan('cash');
    }
}
```

Call it after `loadShop()` selects a shop and after `changeShopPOS()`. In `setMethod`:

```javascript
if (m === 'transfer' && !currentShopHasTransferAccount()) {
    showToast(dich('pos.payment.bank_setup_required'));
    document.getElementById('qrSetupHint').hidden = false;
    return;
}
```

Use `displayPosCategoryName` only in the POS category buttons/filter; keep the
canonical API value untouched.

The hint links to `/seller?setup=bank`. Cash and debt stay enabled.

- [ ] **Step 4: Handle the backend stable error without losing the cart**

In the checkout error path, when `error.code === 'QR_BANK_ACCOUNT_NOT_CONFIGURED'`, switch the visible capability state to unavailable and show the setup hint. `apiCall` already preserves stable backend codes on `Error.code`; do not parse localized text. Do not clear cart, checkout operation ID or entered cash/customer state.

- [ ] **Step 5: Add success UI only for the explicit R2 journey**

Add hidden `section#firstRunSaleSuccess` with:

- title: “Xong rồi — bạn đã bán đơn đầu tiên bằng F-Selling.”
- primary button: “Xem tổng quan cửa hàng” → `/seller`.
- secondary button: “Bán thêm đơn nữa” → hide success and remain in POS.

After receipt details are rendered in `hienHoaDon`:

```javascript
function showFirstRunSaleSuccess(orderDetail) {
    const query = new URLSearchParams(window.location.search);
    if (query.get('onboarding') !== 'r2') return;
    if (!['PAID', 'DEBT'].includes(orderDetail?.status)) return;
    document.getElementById('firstRunSaleSuccess').hidden = false;
}

// after veHoaDon(d) and showing hoaDonSection
showFirstRunSaleSuccess(d);
```

Do not infer success from the URL alone or from a `PENDING` transfer order.

- [ ] **Step 6: Add bilingual copy, shared style and cache busting**

Append `&amp;onboarding=20260828-r2` to existing POS locale/JS asset versions so old version-prefix tests remain valid. Load `onboarding-r2.css?v=20260828-r2`. Use focus-visible styles, 44px targets, `aria-live="polite"` and no mandatory animation.

- [ ] **Step 7: Verify POS, QR and offline regressions**

Run:

```powershell
node --check static/js/pos.js
python -m pytest tests/test_onboarding_r2.py tests/test_qr_pos_ui.py tests/test_qr_intent_issuance.py tests/test_orders.py tests/test_pos_offline_ui.py tests/test_pos_offline_sync_ui.py tests/test_offline_client_v1.py tests/test_offline_client_sync_v1.py -q
```

Expected: all pass; transfer remains unchanged for fully configured shops; offline cash behavior remains intact.

- [ ] **Step 8: Record progress and commit only Task 6 files**

```powershell
git diff -- static/pos.html static/js/pos.js static/js/locales/pos.js static/css/onboarding-r2.css tests/test_qr_pos_ui.py tests/test_onboarding_r2.py
git add static/pos.html static/js/pos.js static/js/locales/pos.js static/css/onboarding-r2.css tests/test_qr_pos_ui.py tests/test_onboarding_r2.py
git commit -m "Complete first-sale onboarding in POS"
```

---

## Task 7: End-to-End Verification and Handoff

**Files:**

- Modify outside repo: `C:\Users\nguye\OneDrive\Desktop\FSellingV2\PROGRESS.md`
- No production file may change unless a failing verification demonstrates a scoped defect; any fix must return to the relevant TDD task and receive its own focused commit.

- [ ] **Step 1: Run syntax and focused automated verification**

```powershell
node --check static/js/onboarding-r2.js
node --check static/js/seller.js
node --check static/js/pos.js
node tests/js/onboarding-r2-ui.test.js
python -m pytest tests/test_onboarding_r2.py tests/test_onboarding_r1.py tests/test_qr_pos_ui.py tests/test_qr_intent_issuance.py tests/test_orders.py tests/test_authorization.py tests/test_qr_account_change_fence.py tests/test_i18n.py tests/test_contract.py -q
```

Expected: zero failures.

- [ ] **Step 2: Run the established focused regression pack**

```powershell
python -m pytest tests/test_auth_landing.py tests/test_seller_sidebar_ui.py tests/test_assistant_experience_r2.py tests/test_assistant_feedback.py tests/test_assistant_navigation_r1.py tests/test_assistant_guided_tasks_r1.py tests/test_loyalty_ui.py tests/test_stocktake_preview_ui.py tests/test_subscription_ui.py tests/test_supplier_ui.py tests/test_pos_offline_ui.py tests/test_pos_offline_sync_ui.py -q
```

Expected: zero failures. Record the exact count and duration in `PROGRESS.md`.

- [ ] **Step 3: Verify runtime-provider boundaries from local configuration**

Run a read-only search that does not print `.env` values:

```powershell
rg -n "GEMINI_ENABLED=false|TTS_SERVER_ENABLED=false" .env.example scripts static fselling
```

Then inspect the process startup/config tests already present. Do not print `.env`, keys or secrets. Expected: no code path in this feature enables either provider.

- [ ] **Step 4: Perform browser acceptance on local port 8100**

Use a fresh disposable SELLER account and real, explicitly entered test values:

1. Login → dedicated step 1 appears; keyboard focus and mobile layout are usable.
2. Submit minimal shop with network failure simulated → values stay; retry creates exactly one shop.
3. Submit first product with actual quantity → one `Chưa phân loại` category exists.
4. Skip at each stage → management opens; reload does not reopen welcome; resume card shows one action.
5. Open POS through `/pos?tour=sale&onboarding=r2`; VietQR is disabled and cash selected.
6. Finish a cash sale → success appears only after order detail is `PAID`.
7. Return to Seller → resume card is gone because `sale_completed=true`.
8. Existing seller, STAFF, ADMIN and `/pos?tour=sale` without `onboarding=r2` remain unchanged.
9. Enter a complete bank group in Settings → VietQR becomes available; a partial group is rejected.

Capture screenshots only for visual QA; do not add them to Git unless the user separately approves them as artifacts.

- [ ] **Step 5: Audit the final diff and commit graph**

```powershell
git status --short
git log --oneline -8
git diff 37166d9..HEAD -- fselling static tests docs/superpowers
```

Expected: every R2 change is explainable by the approved spec; unrelated dirty files are still present but unstaged/unmodified by this implementation.

- [ ] **Step 6: Update the final `PROGRESS.md` checkpoint**

Record:

- completed task/commit list;
- exact automated test commands, counts and outcomes;
- browser scenarios and results;
- known limitations: browser-local dismissal, bank setup required for VietQR, no offline setup queue;
- explicit confirmation Gemini and server TTS remained OFF;
- next safe decision gate: user acceptance before enabling any provider or starting an unrelated feature.

No empty “done” commit is required. If all verification passes, hand the result to the user with file links and evidence.

---

## Final Acceptance Checklist

- [ ] New SELLER with zero shops sees one focused task, not the old dashboard checklist.
- [ ] “Để sau” is account-scoped in this browser and never counts as durable completion.
- [ ] Shop name + phone are sufficient; advanced fields remain editable later.
- [ ] Partial bank configuration fails; cash/debt remain available; transfer fails closed before mutation.
- [ ] First product requires real name, price and actual quantity, with no stock default.
- [ ] `Chưa phân loại` is lazy, shop-scoped, reused and rolled back with failed product creation.
- [ ] Resume card exposes exactly one next action and disappears after `sale_completed=true`.
- [ ] Assistant help explains/navigates only and makes no provider or business mutation call.
- [ ] R2 success appears only after a `PAID` or `DEBT` order in the explicit onboarding query path.
- [ ] Existing owners, STAFF, ADMIN, demo tour, QR v0/v1 and offline cash flows regress cleanly.
- [ ] No new dependency, route, table, migration, deployment, billing or provider enablement.
