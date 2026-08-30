# Lịch sử bán hàng R1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cho người có quyền SALE xem, tìm, in và gửi lại các hóa đơn `PAID`/`DEBT` của cửa hàng hiện tại ngay trong POS, với danh sách 20 đơn, dữ liệu tối thiểu và phục hồi rõ khi lỗi.

**Architecture:** Thêm một read-model API riêng dưới router orders, kiểm tra shop và quyền SALE trước khi lọc/phân trang. Frontend thay modal tìm mã đơn hiện có bằng bảng lịch sử; state bất đồng bộ nằm trong một controller vanilla JavaScript nhỏ, còn bộ dựng/in/chia sẻ hóa đơn cố định R2 được tái sử dụng. Không dùng API dashboard, không thêm schema, dependency hoặc provider.

**Tech Stack:** FastAPI, SQLAlchemy, vanilla HTML/CSS/JavaScript, pytest, Node `assert`.

**Spec:** `docs/superpowers/specs/2026-08-30-lich-su-ban-hang-r1-design.md`

## Global Constraints

- Giữ `GEMINI_ENABLED=false` và `TTS_SERVER_ENABLED=false`; không gọi provider, bật billing hoặc deploy.
- Endpoint danh sách chỉ trả đơn `PAID`/`DEBT` của đúng shop và luôn yêu cầu `PERMISSION_SALE`.
- Không cấp `PERMISSION_REPORT`, không trả tổng doanh thu/lãi/giá vốn và không xuất Excel.
- Kích thước trang cố định là 20; mặc định `today`, lựa chọn `7d`, còn `q` có nội dung tìm toàn bộ lịch sử.
- Danh sách chỉ trả điện thoại đã che; chi tiết tiếp tục dùng `GET /api/orders/{order_id}/detail` và hóa đơn R2 hiện có.
- Không sửa, hủy, hoàn tiền, cache offline hoặc thêm mutation nghiệp vụ.
- Mọi chuỗi mới có tiếng Việt và tiếng Anh; input mobile tối thiểu 16px, vùng bấm tối thiểu 44px.
- Worktree có ba file không theo dõi của người dùng: `TONG_QUAN_CHUC_NANG_VA_VALUE_PROPOSITION.md`, `check_db_stats.py`, `inspect_details.py`. Không sửa hoặc stage chúng.
- Sau mỗi task, cập nhật `C:\Users\nguye\OneDrive\Desktop\FSellingV2\PROGRESS.md`; file này nằm ngoài Git repo ứng dụng và không được stage.

---

## File and Responsibility Map

### Create

- `tests/test_sales_history_r1.py` — hợp đồng API, phân quyền tenant, tìm kiếm, ngày, phân trang và che điện thoại.
- `static/js/pos-sales-history-r1.js` — state controller, chống response cũ và DOM renderer riêng của Lịch sử đơn.
- `static/css/pos-sales-history-r1.css` — layout modal desktop/mobile, thẻ, skeleton và trạng thái.
- `tests/js/pos-sales-history-r1.test.js` — Node harness cho state, race, phân trang, detail và escaping.
- `tests/test_sales_history_r1_ui.py` — chạy Node harness và khóa hợp đồng asset/markup/locale.

### Modify

- `fselling/services/order_service.py` — query read-model `list_sales_history` và helper che điện thoại/ngày UTC+7.
- `fselling/routers/orders.py` — route `GET /api/orders/{shop_id}/history` và validation query.
- `static/pos.html` — đổi nút/modal tìm hóa đơn thành Lịch sử đơn và nạp assets có version.
- `static/js/pos.js` — mount controller, reset khi đổi shop và bridge detail sang bộ in/chia sẻ R2.
- `static/js/locales/pos.js` — nội dung `pos.sales_history.*` Việt/Anh.
- `tests/js/receipt-actions-r1.test.js` — cập nhật hợp đồng nút cũ sau khi được thay bởi Lịch sử đơn; giữ test hóa đơn R2.
- `tests/test_receipt_actions_r1.py` — chỉ đổi số assertion harness nếu cần sau khi test cũ được cập nhật.

### Explicitly unchanged

- Database models/migrations và hợp đồng `GET /api/orders/{order_id}/detail`.
- API dashboard/report, subscription report range và quyền `PERMISSION_REPORT`.
- Receipt image generator, staff copy restriction, order mutation, inventory và payment state machine.

---

### Task 1: SALE-Scoped Sales History API

**Files:**

- Create: `tests/test_sales_history_r1.py`
- Modify: `fselling/services/order_service.py:1-25,1644`
- Modify: `fselling/routers/orders.py:1-25,93`

**Interfaces:**

- Consumes: `require_shop_access`, `require_staff_permission`, `PERMISSION_SALE`, `models.Order`, `models.Customer`.
- Produces: `order_service.list_sales_history(db, current_user, shop_id, scope="today", q=None, page=1) -> Dict[str, Any]` and `GET /api/orders/{shop_id}/history`.

- [ ] **Step 1: Write failing API fixtures and default-list test**

Create `tests/test_sales_history_r1.py` with a DB helper that fixes status, customer and time without invoking unrelated checkout behavior:

```python
from datetime import datetime, timedelta

from fselling import models
from fselling.core.database import SessionLocal
from fselling.services import order_service
from conftest import auth, new_staff, seller_with_shop


def add_order(ctx, *, status="PAID", created_at=None, customer=None, total=12_000):
    with SessionLocal() as db:
        customer_id = None
        if customer:
            row = models.Customer(
                shop_id=ctx["shop_id"], name=customer[0], phone=customer[1]
            )
            db.add(row)
            db.flush()
            customer_id = row.id
        order = models.Order(
            shop_id=ctx["shop_id"], status=status, payment_method="cash",
            total_amount=total, customer_id=customer_id,
            created_at=created_at or datetime.utcnow(),
        )
        db.add(order)
        db.flush()
        db.add(models.OrderItem(
            order_id=order.id, product_name="Nước suối", price=total,
            quantity=1, net_amount_vnd=total,
        ))
        db.commit()
        return order.id


def test_history_defaults_to_20_finalized_orders_today(client):
    ctx = seller_with_shop(client)
    now = datetime.utcnow()
    ids = [add_order(ctx, status="PAID" if i % 2 else "DEBT",
                     created_at=now - timedelta(minutes=i)) for i in range(21)]
    add_order(ctx, status="PENDING", created_at=now + timedelta(seconds=1))
    add_order(ctx, status="CANCELLED", created_at=now + timedelta(seconds=2))
    add_order(ctx, status="PAID", created_at=now + timedelta(days=2))

    response = client.get(
        f"/api/orders/{ctx['shop_id']}/history", headers=auth(ctx["token"])
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert [row["id"] for row in body["orders"]] == ids[:20]
    assert {row["status"] for row in body["orders"]} <= {"PAID", "DEBT"}
    assert body["page"] == 1
    assert body["per_page"] == 20
    assert body["has_more"] is True
    assert body["searching_all_history"] is False
    second = client.get(
        f"/api/orders/{ctx['shop_id']}/history",
        params={"page": 2}, headers=auth(ctx["token"]),
    ).json()
    assert [row["id"] for row in second["orders"]] == ids[20:]
    assert second["has_more"] is False
```

- [ ] **Step 2: Add failing search, privacy, range and permission tests**

```python
def test_search_ignores_scope_and_matches_id_name_or_phone(client):
    ctx = seller_with_shop(client)
    old = datetime.utcnow() - timedelta(days=45)
    order_id = add_order(
        ctx, created_at=old, customer=("Cô Lan", "0774867057"), total=45_000
    )
    for query in (str(order_id), "cô lan", "867057"):
        response = client.get(
            f"/api/orders/{ctx['shop_id']}/history",
            params={"scope": "today", "q": query},
            headers=auth(ctx["token"]),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert [row["id"] for row in body["orders"]] == [order_id]
        assert body["searching_all_history"] is True
        assert body["orders"][0]["customer_phone_masked"] == "077 *** 7057"
        assert "0774867057" not in response.text


def test_history_range_and_page_are_validated(client):
    ctx = seller_with_shop(client)
    assert client.get(
        f"/api/orders/{ctx['shop_id']}/history",
        params={"scope": "month"}, headers=auth(ctx["token"]),
    ).status_code == 422


def test_history_uses_calendar_days_in_utc_plus_seven():
    fixed_utc = datetime(2026, 8, 30, 18, 0, 0)  # 01:00 ngày 31/08 tại VN
    assert order_service._history_bounds_utc("today", fixed_utc) == (
        datetime(2026, 8, 30, 17, 0, 0),
        datetime(2026, 8, 31, 17, 0, 0),
    )
    assert order_service._history_bounds_utc("7d", fixed_utc) == (
        datetime(2026, 8, 24, 17, 0, 0),
        datetime(2026, 8, 31, 17, 0, 0),
    )
    assert client.get(
        f"/api/orders/{ctx['shop_id']}/history",
        params={"page": 0}, headers=auth(ctx["token"]),
    ).status_code == 422


def test_cashier_can_read_but_warehouse_and_other_shop_cannot(client):
    owner = seller_with_shop(client)
    other = seller_with_shop(client)
    add_order(owner)
    _, cashier = new_staff(client, owner, staff_role="CASHIER")
    _, warehouse = new_staff(client, owner, staff_role="WAREHOUSE")
    url = f"/api/orders/{owner['shop_id']}/history"
    assert client.get(url, headers=auth(cashier)).status_code == 200
    assert client.get(url, headers=auth(warehouse)).status_code == 403
    assert client.get(url, headers=auth(other["token"])).status_code == 403


def test_search_treats_sql_wildcards_as_plain_text(client):
    ctx = seller_with_shop(client)
    add_order(ctx, customer=("Khách thường", "0900000001"))
    response = client.get(
        f"/api/orders/{ctx['shop_id']}/history",
        params={"q": "%_"}, headers=auth(ctx["token"]),
    )
    assert response.status_code == 200
    assert response.json()["orders"] == []
```

- [ ] **Step 3: Run the focused tests and confirm the route is absent**

Run: `python -m pytest tests/test_sales_history_r1.py -q`

Expected: FAIL with `404`/`405` or route-contract failures because the GET history endpoint does not exist.

- [ ] **Step 4: Implement the bounded read model in the order service**

Add required imports `time`, `timedelta`, `func`, `or_` and `joinedload`, then implement constants and helpers without changing the order state machine:

```python
HISTORY_PAGE_SIZE = 20
HISTORY_SCOPES = frozenset({"today", "7d"})
LOCAL_UTC_OFFSET = timedelta(hours=7)


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _mask_customer_phone(value: Optional[str]) -> Optional[str]:
    digits = "".join(ch for ch in (value or "") if ch.isdigit())
    if not digits:
        return None
    if len(digits) < 7:
        return "***"
    return f"{digits[:3]} *** {digits[-4:]}"


def _history_bounds_utc(scope: str, now_utc: datetime) -> Tuple[datetime, datetime]:
    local_now = now_utc + LOCAL_UTC_OFFSET
    days_back = 0 if scope == "today" else 6
    local_start = datetime.combine(
        local_now.date() - timedelta(days=days_back), time.min
    )
    local_end = datetime.combine(local_now.date() + timedelta(days=1), time.min)
    return (
        local_start - LOCAL_UTC_OFFSET,
        local_end - LOCAL_UTC_OFFSET,
    )


def list_sales_history(
    db: Session,
    current_user: models.User,
    shop_id: int,
    scope: str = "today",
    q: Optional[str] = None,
    page: int = 1,
) -> Dict[str, Any]:
    require_shop_access(db, shop_id, current_user)
    require_staff_permission(current_user, PERMISSION_SALE)
    if scope not in HISTORY_SCOPES or page < 1:
        raise HTTPException(status_code=400, detail=tr("Bộ lọc lịch sử không hợp lệ"))

    query_text = (q or "").strip()
    base = (
        db.query(models.Order)
        .options(joinedload(models.Order.customer))
        .filter(
            models.Order.shop_id == shop_id,
            models.Order.status.in_((STATUS_PAID, STATUS_DEBT)),
        )
    )
    if query_text:
        escaped = _escape_like(query_text)
        matches = [models.Customer.name.ilike(f"%{escaped}%", escape="\\")]
        phone_digits = "".join(ch for ch in query_text if ch.isdigit())
        if phone_digits:
            normalized_phone = models.Customer.phone
            for separator in (" ", "-", ".", "(", ")", "+"):
                normalized_phone = func.replace(normalized_phone, separator, "")
            matches.append(normalized_phone.like(f"%{phone_digits}%", escape="\\"))
        if query_text.isdecimal():
            matches.append(models.Order.id == int(query_text))
        base = base.outerjoin(models.Customer).filter(or_(*matches))
    else:
        start_utc, end_utc = _history_bounds_utc(scope, datetime.utcnow())
        base = base.filter(
            models.Order.created_at >= start_utc,
            models.Order.created_at < end_utc,
        )

    rows = (
        base.order_by(models.Order.created_at.desc(), models.Order.id.desc())
        .offset((page - 1) * HISTORY_PAGE_SIZE)
        .limit(HISTORY_PAGE_SIZE + 1)
        .all()
    )
    has_more = len(rows) > HISTORY_PAGE_SIZE
    rows = rows[:HISTORY_PAGE_SIZE]
    return {
        "orders": [{
            "id": row.id,
            "created_at": row.created_at,
            "status": row.status,
            "payment_method": row.payment_method,
            "total_amount": row.total_amount,
            "customer_name": row.customer.name if row.customer else None,
            "customer_phone_masked": _mask_customer_phone(
                row.customer.phone if row.customer else None
            ),
        } for row in rows],
        "page": page,
        "per_page": HISTORY_PAGE_SIZE,
        "has_more": has_more,
        "searching_all_history": bool(query_text),
    }
```

Do not call `subscription_service.require_pro` and do not reuse `_dashboard_order` because both would couple an operational receipt lookup to report data/contracts.

- [ ] **Step 5: Expose the validated GET route**

Add `Literal` and `Query` imports, then place this route before `@router.post("/{shop_id}/offline")`:

```python
@router.get("/{shop_id}/history")
def get_sales_history(
    shop_id: int,
    scope: Literal["today", "7d"] = Query("today"),
    q: str | None = Query(None, max_length=100),
    page: int = Query(1, ge=1),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return order_service.list_sales_history(
        db, current_user, shop_id, scope=scope, q=q, page=page
    )
```

- [ ] **Step 6: Run focused and authorization regressions**

Run: `python -m pytest tests/test_sales_history_r1.py tests/test_authorization.py tests/test_orders.py -q`

Expected: all pass; no order mutation, inventory or existing tenant boundary changes.

- [ ] **Step 7: Record progress and commit only Task 1 paths**

```powershell
git diff -- fselling/services/order_service.py fselling/routers/orders.py tests/test_sales_history_r1.py
git add fselling/services/order_service.py fselling/routers/orders.py tests/test_sales_history_r1.py
git commit -m "Add SALE-scoped order history"
```

---

### Task 2: Race-Safe Sales History Controller

**Files:**

- Create: `static/js/pos-sales-history-r1.js`
- Create: `tests/js/pos-sales-history-r1.test.js`
- Create: `tests/test_sales_history_r1_ui.py`

**Interfaces:**

- Consumes: injected `request(path)`, `getShopId()`, and `onReceipt(detail)` functions.
- Produces: `FSellingSalesHistoryR1.createController(dependencies)` with `subscribe`, `open`, `close`, `setScope`, `search`, `clearSearch`, `loadMore`, `retry`, `selectOrder`, `closeDetail`, `resetForShopChange`, `getState`.

- [ ] **Step 1: Write a failing Node harness for default load and pagination**

Create `tests/js/pos-sales-history-r1.test.js`:

```javascript
'use strict';

const assert = require('assert/strict');
const { createController } = require('../../static/js/pos-sales-history-r1.js');

function row(id) {
    return { id, status: 'PAID', customer_name: null, total_amount: 12000 };
}

(async () => {
    const paths = [];
    const pages = {
        1: { orders: [row(3), row(2)], page: 1, per_page: 20, has_more: true, searching_all_history: false },
        2: { orders: [row(1)], page: 2, per_page: 20, has_more: false, searching_all_history: false }
    };
    const controller = createController({
        getShopId: () => 7,
        request: async path => {
            paths.push(path);
            const page = Number(new URL(`http://local${path}`).searchParams.get('page'));
            return pages[page];
        },
        onReceipt() {}
    });
    await controller.open();
    assert.deepEqual(controller.getState().orders.map(item => item.id), [3, 2]);
    assert.match(paths[0], /\/orders\/7\/history\?scope=today&page=1$/);
    await controller.loadMore();
    assert.deepEqual(controller.getState().orders.map(item => item.id), [3, 2, 1]);
    assert.equal(controller.getState().hasMore, false);
```

Close the async IIFE at the end of the file with error reporting and a stable success line:

```javascript
    console.log('pos-sales-history-r1 harness: passed');
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
```

- [ ] **Step 2: Extend the harness for search, stale responses and detail validation**

Add cases using deferred promises:

```javascript
function deferred() {
    let resolve;
    const promise = new Promise(done => { resolve = done; });
    return { promise, resolve };
}

// Search must encode text and invalidate a slower previous response.
const oldRequest = deferred();
const newRequest = deferred();
let call = 0;
const race = createController({
    getShopId: () => 7,
    request: () => (++call === 1 ? oldRequest.promise : newRequest.promise),
    onReceipt() {}
});
const oldRun = race.search('Cô Lan');
const newRun = race.search('Mai & Bé');
newRequest.resolve({ orders: [row(9)], page: 1, per_page: 20, has_more: false, searching_all_history: true });
await newRun;
oldRequest.resolve({ orders: [row(8)], page: 1, per_page: 20, has_more: false, searching_all_history: true });
await oldRun;
assert.deepEqual(race.getState().orders.map(item => item.id), [9]);

// Detail must be finalized and still belong to the selected shop.
let receipt = null;
const detail = createController({
    getShopId: () => 7,
    request: async path => path.endsWith('/detail')
        ? { id: 9, shop_id: 7, status: 'DEBT', items: [] }
        : { orders: [], page: 1, per_page: 20, has_more: false, searching_all_history: false },
    onReceipt: value => { receipt = value; }
});
await detail.selectOrder(9);
assert.equal(receipt.receipt_copy, true);
assert.equal(detail.getState().detail.id, 9);
```

Also assert `resetForShopChange()` and `close()` invalidate pending work, `loadMore()` cannot run twice concurrently, and a wrong-shop/non-finalized detail produces a recoverable `detailError` without calling `onReceipt`.

- [ ] **Step 3: Add the pytest wrapper and verify the module is missing**

```python
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_sales_history_node_harness():
    completed = subprocess.run(
        ["node", "tests/js/pos-sales-history-r1.test.js"],
        cwd=ROOT, capture_output=True, text=True, timeout=30, check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "pos-sales-history-r1 harness: passed" in completed.stdout
```

Run: `python -m pytest tests/test_sales_history_r1_ui.py -q`

Expected: FAIL because `static/js/pos-sales-history-r1.js` does not exist.

- [ ] **Step 4: Implement the UMD controller with immutable snapshots**

Create `static/js/pos-sales-history-r1.js`:

```javascript
(function (root, factory) {
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    if (root) root.FSellingSalesHistoryR1 = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
    'use strict';

    function createController({ request, getShopId, onReceipt }) {
        let requestId = 0;
        let listener = () => {};
        const state = {
            open: false, scope: 'today', query: '', page: 0, orders: [],
            hasMore: false, loading: false, loadingMore: false, error: '',
            searchingAllHistory: false, detail: null,
            detailLoading: false, detailError: ''
        };
        const snapshot = () => ({ ...state, orders: state.orders.slice() });
        const publish = () => listener(snapshot());

        async function load(page, append) {
            const shopId = Number(getShopId());
            if (!Number.isSafeInteger(shopId) || shopId <= 0) {
                state.error = 'select_shop'; publish(); return;
            }
            const token = ++requestId;
            if (!append) {
                state.orders = [];
                state.page = 0;
                state.hasMore = false;
            }
            state.loading = !append;
            state.loadingMore = append;
            state.error = '';
            publish();
            const params = new URLSearchParams({ scope: state.scope, page: String(page) });
            if (state.query) params.set('q', state.query);
            try {
                const data = await request(`/orders/${shopId}/history?${params}`);
                if (token !== requestId || shopId !== Number(getShopId())) return;
                state.orders = append ? state.orders.concat(data.orders) : data.orders.slice();
                state.page = data.page;
                state.hasMore = Boolean(data.has_more);
                state.searchingAllHistory = Boolean(data.searching_all_history);
            } catch (error) {
                if (token !== requestId) return;
                state.error = Number(error?.status) === 401 ? 'session'
                    : Number(error?.status) === 403 ? 'forbidden' : 'network';
            } finally {
                if (token === requestId) {
                    state.loading = false; state.loadingMore = false; publish();
                }
            }
        }

        return {
            subscribe(fn) { listener = fn; publish(); return () => { listener = () => {}; }; },
            getState: snapshot,
            async open() {
                Object.assign(state, {
                    open: true, scope: 'today', query: '', page: 0, orders: [],
                    hasMore: false, error: '', detail: null, detailError: ''
                });
                publish();
                await load(1, false);
            },
            close() {
                requestId += 1;
                Object.assign(state, {
                    open: false, loading: false, loadingMore: false,
                    detailLoading: false
                });
                publish();
            },
            async setScope(scope) { state.scope = scope === '7d' ? '7d' : 'today'; state.query = ''; await load(1, false); },
            async search(value) { state.query = String(value || '').trim(); await load(1, false); },
            async clearSearch() { state.query = ''; await load(1, false); },
            async loadMore() { if (!state.hasMore || state.loading || state.loadingMore) return; await load(state.page + 1, true); },
            async retry() {
                const append = state.orders.length > 0 && state.page > 0;
                await load(append ? state.page + 1 : 1, append);
            },
            async selectOrder(orderId) {
                const shopId = Number(getShopId());
                const token = ++requestId;
                state.detail = null;
                state.detailError = '';
                state.detailLoading = true;
                publish();
                try {
                    const detail = await request(`/orders/${Number(orderId)}/detail`);
                    if (token !== requestId || shopId !== Number(getShopId())) return;
                    if (Number(detail.shop_id) !== shopId) {
                        throw Object.assign(new Error(), { code: 'other_shop' });
                    }
                    if (!['PAID', 'DEBT'].includes(detail.status)) {
                        throw Object.assign(new Error(), { code: 'not_finalized' });
                    }
                    detail.receipt_copy = true;
                    state.detail = detail;
                    onReceipt(detail);
                } catch (error) {
                    if (token !== requestId) return;
                    state.detailError = error?.code || (Number(error?.status) === 401 ? 'session'
                        : Number(error?.status) === 403 ? 'forbidden'
                        : Number(error?.status) === 404 ? 'not_found' : 'network');
                } finally {
                    if (token === requestId) { state.detailLoading = false; publish(); }
                }
            },
            closeDetail() {
                requestId += 1;
                Object.assign(state, {
                    detail: null, detailLoading: false, detailError: ''
                });
                publish();
            },
            resetForShopChange() {
                requestId += 1;
                Object.assign(state, {
                    open: false, scope: 'today', query: '', page: 0, orders: [],
                    hasMore: false, loading: false, loadingMore: false,
                    error: '', searchingAllHistory: false, detail: null,
                    detailLoading: false, detailError: ''
                });
                publish();
            }
        };
    }

    return { createController };
});
```

- [ ] **Step 5: Run the controller harness and syntax check**

Run: `node --check static/js/pos-sales-history-r1.js`

Run: `python -m pytest tests/test_sales_history_r1_ui.py -q`

Expected: syntax exits 0 and the Node harness passes all state/race/detail cases.

- [ ] **Step 6: Record progress and commit only Task 2 paths**

```powershell
git diff -- static/js/pos-sales-history-r1.js tests/js/pos-sales-history-r1.test.js tests/test_sales_history_r1_ui.py
git add static/js/pos-sales-history-r1.js tests/js/pos-sales-history-r1.test.js tests/test_sales_history_r1_ui.py
git commit -m "Add sales history state controller"
```

---

### Task 3: POS History Surface and Immutable Receipt Actions

**Files:**

- Create: `static/css/pos-sales-history-r1.css`
- Modify: `static/js/pos-sales-history-r1.js`
- Modify: `static/pos.html:15,80-86,437-453,510-551`
- Modify: `static/js/pos.js:540-565,3749-3825,4650`
- Modify: `static/js/locales/pos.js:402-416,828-842`
- Modify: `tests/js/pos-sales-history-r1.test.js`
- Modify: `tests/test_sales_history_r1_ui.py`
- Modify: `tests/js/receipt-actions-r1.test.js`
- Modify: `tests/test_receipt_actions_r1.py`

**Interfaces:**

- Consumes: Task 2 `createController`, global `apiCall`, `dich`, `escapeHtml`, `dinhDangTienHoaDon`, `dinhDangNgayGioHoaDon`, `veHoaDon`, `inHoaDon`, `chiaSeHoaDon`.
- Produces: `FSellingSalesHistoryR1.mount(options) -> { open, close, resetForShopChange }` and the accessible `#salesHistoryModal` UI.

- [ ] **Step 1: Add failing static contracts for the approved surface**

Extend `tests/test_sales_history_r1_ui.py`:

```python
def test_pos_hosts_sales_history_assets_and_accessible_dialog():
    html = (ROOT / "static/pos.html").read_text(encoding="utf-8")
    assert 'id="btnSalesHistory"' in html
    assert 'onclick="moLichSuDon()"' in html
    assert 'id="salesHistoryModal"' in html
    assert 'role="dialog"' in html
    assert 'aria-labelledby="salesHistoryTitle"' in html
    for element_id in (
        "salesHistorySearch", "salesHistorySubmit", "salesHistoryToday", "salesHistory7d",
        "salesHistoryList", "salesHistoryLoadMore", "salesHistoryDetail",
    ):
        assert f'id="{element_id}"' in html
    assert "/css/pos-sales-history-r1.css?v=20260830-r1" in html
    assert "/js/pos-sales-history-r1.js?v=20260830-r1" in html


def test_sales_history_copy_exists_in_both_locales():
    locale = (ROOT / "static/js/locales/pos.js").read_text(encoding="utf-8")
    for key in (
        "pos.sales_history.open", "pos.sales_history.search_placeholder",
        "pos.sales_history.today", "pos.sales_history.seven_days",
        "pos.sales_history.searching_all", "pos.sales_history.empty_today",
        "pos.sales_history.empty_seven_days", "pos.sales_history.no_results",
        "pos.sales_history.retry", "pos.sales_history.login_again",
        "pos.sales_history.load_more", "pos.sales_history.print",
        "pos.sales_history.share", "pos.sales_history.close",
    ):
        assert locale.count(f"'{key}'") == 2
```

Run: `python -m pytest tests/test_sales_history_r1_ui.py -q`

Expected: FAIL because the POS still contains the old ID-only modal and does not host the new assets.

- [ ] **Step 2: Replace the old modal with semantic history markup**

Change the action button to:

```html
<button id="btnSalesHistory" type="button" class="btn-outline" onclick="moLichSuDon()" aria-haspopup="dialog" aria-controls="salesHistoryModal">
    <i class="ph ph-clock-counter-clockwise" aria-hidden="true"></i>
    <span data-i18n="pos.sales_history.open">Lịch sử đơn</span>
</button>
```

Replace `#oldReceiptModal` with one `#salesHistoryModal.pos-modal.sales-history-modal`, containing:

```html
<div class="sales-history-card">
    <header class="sales-history-header">
        <div><small data-i18n="pos.sales_history.eyebrow">TÌM VÀ GỬI LẠI</small><h3 id="salesHistoryTitle" data-i18n="pos.sales_history.title">Lịch sử đơn</h3></div>
        <button id="salesHistoryClose" type="button" class="icon-button" data-i18n-aria-label="pos.sales_history.close" aria-label="Đóng">×</button>
    </header>
    <form id="salesHistoryForm" class="sales-history-search" novalidate>
        <label for="salesHistorySearch" data-i18n="pos.sales_history.search_label">Tìm đơn</label>
        <div><input id="salesHistorySearch" type="search" maxlength="100" autocomplete="off" data-i18n-placeholder="pos.sales_history.search_placeholder"><button id="salesHistorySubmit" type="submit" data-i18n="pos.sales_history.search">Tìm</button></div>
    </form>
    <div class="sales-history-scopes" role="group" data-i18n-aria-label="pos.sales_history.range_label">
        <button id="salesHistoryToday" type="button" aria-pressed="true" data-i18n="pos.sales_history.today">Hôm nay</button>
        <button id="salesHistory7d" type="button" aria-pressed="false" data-i18n="pos.sales_history.seven_days">7 ngày</button>
    </div>
    <p id="salesHistoryAllHint" class="sales-history-hint" hidden data-i18n="pos.sales_history.searching_all">Đang tìm trong toàn bộ lịch sử</p>
    <div id="salesHistoryStatus" role="status" aria-live="polite"></div>
    <div id="salesHistoryList" class="sales-history-list"></div>
    <button id="salesHistoryLoadMore" type="button" hidden data-i18n="pos.sales_history.load_more">Xem thêm 20 đơn</button>
    <section id="salesHistoryDetail" class="sales-history-detail" hidden aria-live="polite"></section>
</div>
```

Load the feature CSS in `<head>` and feature JS immediately before `pos.js`, both with the exact `20260830-r1` suffix.

- [ ] **Step 3: Add complete Vietnamese and English copy**

Replace dead `pos.receipt_lookup.*` keys with `pos.sales_history.*`. Include exact recovery text from the spec:

```javascript
'pos.sales_history.empty_today': 'Hôm nay chưa có đơn nào',
'pos.sales_history.empty_seven_days': 'Chưa có đơn nào trong 7 ngày gần đây',
'pos.sales_history.show_seven_days': 'Xem 7 ngày gần đây',
'pos.sales_history.no_results': 'Không tìm thấy đơn phù hợp',
'pos.sales_history.clear_search': 'Xóa tìm kiếm',
'pos.sales_history.network_error': 'Không tải được lịch sử. Kiểm tra mạng rồi thử lại.',
'pos.sales_history.session_error': 'Phiên làm việc đã hết hạn',
'pos.sales_history.permission_error': 'Bạn không có quyền xem lịch sử đơn. Hãy liên hệ chủ cửa hàng.',
'pos.sales_history.loading': 'Đang tải lịch sử đơn…',
'pos.sales_history.loading_more': 'Đang tải…',
'pos.sales_history.guest': 'Khách lẻ',
'pos.sales_history.paid': 'Đã thanh toán',
'pos.sales_history.debt': 'Ghi nợ',
'pos.sales_history.cash': 'Tiền mặt',
'pos.sales_history.transfer': 'Chuyển khoản',
'pos.sales_history.detail_not_found': 'Không còn tìm thấy đơn này.',
'pos.sales_history.detail_forbidden': 'Bạn không có quyền xem đơn này.',
'pos.sales_history.detail_other_shop': 'Đơn này thuộc cửa hàng khác.',
'pos.sales_history.detail_not_finalized': 'Đơn này chưa hoàn tất nên chưa thể gửi hóa đơn.',
'pos.sales_history.detail_network': 'Chưa tải được chi tiết đơn. Kiểm tra mạng rồi thử lại.',
'pos.sales_history.detail_session': 'Phiên làm việc đã hết hạn.',
```

Add equivalent natural English strings in the English object; do not concatenate sentences from fragments.

- [ ] **Step 4: Add safe pure renderers and the DOM mount adapter**

Extend the module export with `renderOrderCard` and `mount`. User data must pass through injected `escapeHtml` before reaching `innerHTML`:

```javascript
function renderOrderCard(order, { escapeHtml, t, money, dateTime }) {
    const name = order.customer_name || t('pos.sales_history.guest');
    return `<button type="button" class="sales-history-order" data-order-id="${Number(order.id)}">
        <span><strong>#${Number(order.id)}</strong><small>${escapeHtml(dateTime(order.created_at))}</small><em>${escapeHtml(t(`pos.sales_history.${String(order.status).toLowerCase()}`))}</em></span>
        <span><strong>${escapeHtml(name)}</strong><small>${escapeHtml(order.customer_phone_masked || '')}</small></span>
        <span><strong>${escapeHtml(money(order.total_amount))}</strong><small>${escapeHtml(t(`pos.sales_history.${order.payment_method}`))}</small></span>
    </button>`;
}
```

Add a concrete detail renderer. Every product/customer value is escaped before insertion:

```javascript
function renderDetail(detail, ui) {
    const lines = (detail.items || []).map(item => `<li>
        <span>${ui.escapeHtml(item.product_name || '')} × ${Number(item.quantity) || 0}</span>
        <span>${ui.escapeHtml(ui.money(item.line_total))}</span>
    </li>`).join('');
    return `<div class="sales-history-detail-head">
        <strong>#${Number(detail.id)}</strong>
        <span>${ui.escapeHtml(ui.dateTime(detail.created_at))}</span>
    </div>
    <ul>${lines}</ul>
    <p class="sales-history-detail-total"><span>${ui.escapeHtml(ui.t('pos.sales_history.total'))}</span><strong>${ui.escapeHtml(ui.money(detail.total_amount))}</strong></p>
    <div class="sales-history-detail-actions">
        <button type="button" data-history-action="print">${ui.escapeHtml(ui.t('pos.sales_history.print'))}</button>
        <button type="button" data-history-action="share">${ui.escapeHtml(ui.t('pos.sales_history.share'))}</button>
        <button type="button" data-history-action="close-detail">${ui.escapeHtml(ui.t('pos.sales_history.close'))}</button>
    </div>`;
}
```

Implement `mount(options)` as the only DOM adapter. It creates one controller, registers each listener once and re-renders from controller snapshots:

```javascript
function mount(options) {
    const doc = options.document || document;
    const ui = {
        t: options.t, escapeHtml: options.escapeHtml,
        money: options.money, dateTime: options.dateTime
    };
    const elements = {
        form: doc.getElementById('salesHistoryForm'),
        search: doc.getElementById('salesHistorySearch'),
        submit: doc.getElementById('salesHistorySubmit'),
        today: doc.getElementById('salesHistoryToday'),
        seven: doc.getElementById('salesHistory7d'),
        hint: doc.getElementById('salesHistoryAllHint'),
        status: doc.getElementById('salesHistoryStatus'),
        list: doc.getElementById('salesHistoryList'),
        more: doc.getElementById('salesHistoryLoadMore'),
        detail: doc.getElementById('salesHistoryDetail'),
        close: doc.getElementById('salesHistoryClose'),
        modal: doc.getElementById('salesHistoryModal')
    };
    const controller = createController({
        request: options.request,
        getShopId: options.getShopId,
        onReceipt: options.prepareReceipt
    });
    let current = controller.getState();

    function actionButton(action, key) {
        return `<button type="button" data-history-action="${action}">${ui.escapeHtml(ui.t(key))}</button>`;
    }

    function render(state) {
        current = state;
        elements.today.setAttribute('aria-pressed', String(state.scope === 'today'));
        elements.seven.setAttribute('aria-pressed', String(state.scope === '7d'));
        elements.hint.hidden = !state.searchingAllHistory;
        elements.submit.disabled = state.loading;

        if (state.loading && state.orders.length === 0) {
            elements.list.innerHTML = '<div class="sales-history-skeleton"></div>'.repeat(3);
            elements.status.textContent = ui.t('pos.sales_history.loading');
        } else {
            elements.list.innerHTML = state.orders.map(order => renderOrderCard(order, ui)).join('');
            if (state.error) {
                const key = state.error === 'forbidden' ? 'pos.sales_history.permission_error'
                    : state.error === 'session' ? 'pos.sales_history.session_error'
                    : 'pos.sales_history.network_error';
                const action = state.error === 'session'
                    ? actionButton('login', 'pos.sales_history.login_again')
                    : actionButton('retry', 'pos.sales_history.retry');
                elements.status.innerHTML = `${ui.escapeHtml(ui.t(key))} ${action}`;
            } else if (state.orders.length === 0 && state.query) {
                elements.status.innerHTML = `${ui.escapeHtml(ui.t('pos.sales_history.no_results'))} ${actionButton('clear', 'pos.sales_history.clear_search')}`;
            } else if (state.orders.length === 0) {
                const emptyKey = state.scope === '7d'
                    ? 'pos.sales_history.empty_seven_days'
                    : 'pos.sales_history.empty_today';
                const next = state.scope === 'today'
                    ? actionButton('seven-days', 'pos.sales_history.show_seven_days')
                    : '';
                elements.status.innerHTML = `${ui.escapeHtml(ui.t(emptyKey))} ${next}`;
            } else {
                elements.status.textContent = '';
            }
        }
        elements.more.hidden = !state.hasMore;
        elements.more.disabled = state.loadingMore;
        elements.more.textContent = ui.t(state.loadingMore
            ? 'pos.sales_history.loading_more' : 'pos.sales_history.load_more');

        elements.detail.hidden = !(state.detailLoading || state.detailError || state.detail);
        if (state.detailLoading) {
            elements.detail.textContent = ui.t('pos.sales_history.loading_detail');
        } else if (state.detailError) {
            elements.detail.innerHTML = `${ui.escapeHtml(ui.t(`pos.sales_history.detail_${state.detailError}`))} ${actionButton('close-detail', 'pos.sales_history.close')}`;
        } else if (state.detail) {
            elements.detail.innerHTML = renderDetail(state.detail, ui);
        } else {
            elements.detail.textContent = '';
        }
    }

    controller.subscribe(render);
    elements.form.addEventListener('submit', event => {
        event.preventDefault();
        controller.search(elements.search.value);
    });
    elements.today.addEventListener('click', () => {
        elements.search.value = ''; controller.setScope('today');
    });
    elements.seven.addEventListener('click', () => {
        elements.search.value = ''; controller.setScope('7d');
    });
    elements.more.addEventListener('click', () => controller.loadMore());
    elements.close.addEventListener('click', () => api.close());
    elements.list.addEventListener('click', event => {
        const card = event.target.closest('[data-order-id]');
        if (card) controller.selectOrder(Number(card.dataset.orderId));
    });
    elements.status.addEventListener('click', event => {
        const action = event.target.dataset.historyAction;
        if (action === 'retry') controller.retry();
        if (action === 'clear') { elements.search.value = ''; controller.clearSearch(); }
        if (action === 'seven-days') { elements.search.value = ''; controller.setScope('7d'); }
        if (action === 'login') options.goToLogin();
    });
    elements.modal.addEventListener('keydown', event => {
        if (event.key !== 'Tab') return;
        const focusable = [...elements.modal.querySelectorAll(
            'button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])'
        )].filter(node => !node.hidden);
        if (!focusable.length) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && doc.activeElement === first) {
            event.preventDefault(); last.focus();
        } else if (!event.shiftKey && doc.activeElement === last) {
            event.preventDefault(); first.focus();
        }
    });
    doc.addEventListener('fselling:localechange', () => render(current));
    elements.detail.addEventListener('click', async event => {
        const action = event.target.dataset.historyAction;
        if (action === 'close-detail') controller.closeDetail();
        if (!current.detail || !['print', 'share'].includes(action)) return;
        event.target.disabled = true;
        try {
            if (action === 'print') options.printReceipt(current.detail);
            else await options.shareReceipt(current.detail);
        } finally {
            event.target.disabled = false;
        }
    });

    const api = {
        open: () => { elements.search.value = ''; return controller.open(); },
        close: () => { controller.close(); options.closeModal('salesHistoryModal'); },
        resetForShopChange: () => controller.resetForShopChange(),
        getState: controller.getState
    };
    return api;
}
```

Export all three units so the Node harness can test them without a browser framework:

```javascript
return { createController, renderOrderCard, renderDetail, mount };
```

- [ ] **Step 5: Mount from POS and reuse the immutable receipt bridge**

Delete the obsolete `RECEIPT_LOOKUP_R2` ID-only controller from `static/js/pos.js`. Add a single bridge after receipt actions are defined:

```javascript
let salesHistoryR1 = null;

function chuanBiBanSaoHoaDon(detail) {
    detail.receipt_copy = true;
    duLieuHoaDonHienTai = detail;
    veHoaDon(detail);
}

function moLichSuDon() {
    if (!currentShopId) return showToast(dich('pos.sales_history.select_shop'));
    hienModalCa('salesHistoryModal', 'salesHistorySearch');
    salesHistoryR1.open();
}

salesHistoryR1 = window.FSellingSalesHistoryR1.mount({
    request: endpoint => apiCall(endpoint),
    getShopId: () => currentShopId,
    t: dich,
    escapeHtml,
    money: dinhDangTienHoaDon,
    dateTime: dinhDangNgayGioHoaDon,
    openModal: hienModalCa,
    closeModal: dongModalCa,
    goToLogin: () => window.location.assign('/#login'),
    prepareReceipt: chuanBiBanSaoHoaDon,
    printReceipt: detail => { chuanBiBanSaoHoaDon(detail); inHoaDon(); },
    shareReceipt: async detail => { chuanBiBanSaoHoaDon(detail); await chiaSeHoaDon(); }
});
```

At the start of a successful `changeShopPOS`, before assigning the new shop, call:

```javascript
salesHistoryR1?.resetForShopChange();
```

Update the existing overlay-click and Escape handlers so `salesHistoryModal`
calls `salesHistoryR1.close()`; every other business modal continues through
`dongModalCa(modal.id)`. This invalidates pending history/detail requests before
the DOM closes and preserves the existing focus-return behavior.

Do not show `#hoaDonSection` merely by selecting a history card; it is a backing renderer for immutable print/share. Detail remains inside the history modal.

- [ ] **Step 6: Add scoped responsive and state CSS**

Create `static/css/pos-sales-history-r1.css` with only `.sales-history-*` selectors. Lock the approved constraints:

```css
.sales-history-card { width:min(980px,96vw); max-height:92vh; overflow:auto; }
.sales-history-order { min-height:72px; width:100%; display:grid; grid-template-columns:1fr 1.4fr 1fr; gap:1rem; text-align:left; }
.sales-history-search input { min-height:44px; font-size:1rem; }
.sales-history-card button { min-height:44px; }
.sales-history-skeleton { min-height:72px; animation:sales-history-pulse 1.2s ease-in-out infinite; }
@media (prefers-reduced-motion:reduce) { .sales-history-skeleton { animation:none; } }
@media (max-width:640px) {
  .sales-history-modal { align-items:stretch; }
  .sales-history-card { width:100%; max-height:none; min-height:100dvh; border-radius:0; }
  .sales-history-order { grid-template-columns:1fr auto; }
}
```

Use existing POS color variables; do not introduce a second design token system.

- [ ] **Step 7: Extend Node/UI tests for escaping, states and immutable actions**

Add to `tests/js/pos-sales-history-r1.test.js`:

```javascript
const { renderOrderCard } = require('../../static/js/pos-sales-history-r1.js');
const escaped = renderOrderCard({
    id: 1, created_at: '2026-08-30T03:00:00Z', status: 'PAID',
    payment_method: 'cash', total_amount: 12000,
    customer_name: '<img src=x onerror=alert(1)>', customer_phone_masked: '090 *** 0001'
}, {
    escapeHtml: value => String(value).replaceAll('<', '&lt;').replaceAll('>', '&gt;'),
    t: key => key, money: value => `${value} ₫`, dateTime: value => value
});
assert.doesNotMatch(escaped, /<img/);
assert.match(escaped, /&lt;img/);
```

Use a minimal fake DOM to assert: initial skeleton, empty-today CTA, no-results CTA, retained rows on load-more failure, `aria-pressed` scope updates, detail buttons call injected print/share once, and action buttons stay disabled while sharing.

Update `tests/js/receipt-actions-r1.test.js` to expect `#btnSalesHistory`/`moLichSuDon()` instead of the deleted old modal while keeping every receipt-image and staff-copy assertion green.

- [ ] **Step 8: Run syntax, feature and receipt regression tests**

Run: `node --check static/js/pos-sales-history-r1.js`

Run: `node --check static/js/pos.js`

Run: `python -m pytest tests/test_sales_history_r1_ui.py tests/test_receipt_actions_r1.py tests/test_i18n.py tests/test_qr_pos_ui.py -q`

Expected: all pass; no duplicate receipt-history UI and no regression to receipt image/share/copy policy.

- [ ] **Step 9: Record progress and commit only Task 3 paths**

```powershell
git diff -- static/css/pos-sales-history-r1.css static/js/pos-sales-history-r1.js static/pos.html static/js/pos.js static/js/locales/pos.js tests/js/pos-sales-history-r1.test.js tests/test_sales_history_r1_ui.py tests/js/receipt-actions-r1.test.js tests/test_receipt_actions_r1.py
git add static/css/pos-sales-history-r1.css static/js/pos-sales-history-r1.js static/pos.html static/js/pos.js static/js/locales/pos.js tests/js/pos-sales-history-r1.test.js tests/test_sales_history_r1_ui.py tests/js/receipt-actions-r1.test.js tests/test_receipt_actions_r1.py
git commit -m "Add POS sales history experience"
```

---

### Task 4: Fortification, Regression Gate and Local Browser Acceptance

**Files:**

- Modify if a verified defect requires it: only Task 1–3 paths listed above.
- Modify: `C:\Users\nguye\OneDrive\Desktop\FSellingV2\PROGRESS.md` after each accepted fix and at final completion; never stage it.

**Interfaces:**

- Consumes: completed API, controller, UI and existing receipt actions.
- Produces: verified local R1 release candidate with provider boundaries unchanged.

- [ ] **Step 1: Run the complete focused gate**

```powershell
python -m pytest tests/test_sales_history_r1.py tests/test_sales_history_r1_ui.py tests/test_receipt_actions_r1.py tests/test_authorization.py tests/test_orders.py tests/test_i18n.py tests/test_qr_pos_ui.py tests/test_auth.py -q
node --check static/js/pos-sales-history-r1.js
node --check static/js/pos.js
```

Expected: every command exits 0. Fix only a demonstrated failure, add a red regression first, rerun the smallest failing command and then this gate.

- [ ] **Step 2: Verify provider and configuration boundaries**

Run: `python -m pytest tests/test_ai_provider_readiness.py tests/test_config.py -q`

Expected: all pass and local runtime remains fail-closed with `GEMINI_ENABLED=false` and `TTS_SERVER_ENABLED=false`.

- [ ] **Step 3: Run full automated regression**

Run: `python -m pytest -q`

Expected: exit 0 with the repository's configured coverage threshold satisfied; record pass/skip/warning counts in `PROGRESS.md`.

- [ ] **Step 4: Start or reuse the local server and execute owner/cashier browser journeys**

Use the existing local runtime on `http://127.0.0.1:8100`. With disposable demo data, verify:

1. Owner opens POS → Lịch sử đơn → sees at most 20 orders today.
2. `7 ngày`, search by ID/name/phone and clear search produce the expected data and label.
3. `Xem thêm 20 đơn` appends without scroll jump or duplicates.
4. PAID and DEBT cards open correct immutable line items; print/share use the R2 receipt copy.
5. STAFF CASHIER succeeds; STAFF WAREHOUSE sees the permission recovery state.
6. Switching shop while a delayed request is pending never renders old-shop data.
7. Offline/timeout keeps loaded rows, offers retry and never invents cached history.

Do not use or mutate the user's non-demo business data. Remove disposable QA identities if they are not part of the established demo seed.

- [ ] **Step 5: Run accessibility and responsive smoke**

At desktop and 390×844 mobile viewport, verify no horizontal overflow, visible close action, 44px targets, 16px search input, keyboard focus return, Escape close, 200% zoom, reduced motion and readable loading/error states. Check browser console for errors.

- [ ] **Step 6: Audit the final diff and commit only verified fixes**

```powershell
git diff --check
git status --short
git diff -- fselling/services/order_service.py fselling/routers/orders.py tests/test_sales_history_r1.py static/css/pos-sales-history-r1.css static/js/pos-sales-history-r1.js static/pos.html static/js/pos.js static/js/locales/pos.js tests/js/pos-sales-history-r1.test.js tests/test_sales_history_r1_ui.py tests/js/receipt-actions-r1.test.js tests/test_receipt_actions_r1.py
```

If browser QA required fixes, commit only those listed paths with:

```powershell
git add fselling/services/order_service.py fselling/routers/orders.py tests/test_sales_history_r1.py static/css/pos-sales-history-r1.css static/js/pos-sales-history-r1.js static/pos.html static/js/pos.js static/js/locales/pos.js tests/js/pos-sales-history-r1.test.js tests/test_sales_history_r1_ui.py tests/js/receipt-actions-r1.test.js tests/test_receipt_actions_r1.py
git commit -m "Harden sales history R1"
```

If there is no diff, do not create an empty commit. Confirm the index is empty and the three user-owned untracked files remain untouched.

- [ ] **Step 7: Write the final progress checkpoint**

Record in `PROGRESS.md`: task commits, focused/full test evidence, browser journeys, accessibility results, remaining limitations, and explicit confirmation that Gemini/TTS remain OFF and no deploy/billing change occurred.
