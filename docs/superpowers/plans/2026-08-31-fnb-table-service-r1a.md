# F&B Table Service R1A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Thêm chế độ bán tại bàn local-first gồm bật F&B, khu vực/bàn, phiên phục vụ, món nháp, chuyển/gộp bàn và đồng bộ polling nhiều thiết bị mà không thay đổi POS bán lẻ.

**Architecture:** R1A là một vertical slice độc lập dưới `/api/fnb` và trang `/fnb`, dùng bảng F&B riêng thay vì biến `Order` thành bill đang mở. Mọi mutation được tuần tự hóa bằng shop write-lock hiện có, kiểm `expected_revision`, chống retry bằng `operation_id` + fingerprint, rồi tăng `Shop.fnb_revision`; frontend nằm trong controller riêng để không làm `static/js/pos.js` lớn thêm. R1A chưa gửi Bếp/Bar, chưa trừ tồn và chưa tạo `Order`.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic/SQLite forward-only migrations, Pydantic, vanilla HTML/CSS/JavaScript, pytest, Node `assert`.

**Spec:** `docs/superpowers/specs/2026-08-31-fnb-table-service-r1-design.md`

## Global Constraints

- Giữ `GEMINI_ENABLED=false` và `TTS_SERVER_ENABLED=false`; không gọi provider, bật billing hoặc deploy.
- `Shop.fnb_enabled` mặc định `false`; khi tắt, điều hướng và dữ liệu F&B không xuất hiện.
- R1A chỉ có khu vực/bàn, phiên phục vụ, món nháp, chuyển/gộp bàn, revision, idempotency và polling; không ticket Bếp/Bar, không mutation tồn kho, không check/bill/payment.
- Mọi mutation nhận `operation_id` và `expected_revision`: setup/open dùng `Shop.fnb_revision`, mutation phiên dùng `Session.revision`; table/line update còn mang state version của đúng row. Retry cùng operation/fingerprint trả kết quả cũ; cùng ID khác payload trả 409.
- Sai revision trả HTTP 409 với code `FNB_SESSION_CHANGED` và snapshot mới nhất; không mutation một phần.
- Tiền là integer VND và giá món nháp luôn chụp từ `Product.price` trong DB; không tin giá client.
- Không thêm dependency, WebSocket, offline multi-device, drag-and-drop floor editor hoặc abstraction dùng một lần.
- Chuỗi mới có tiếng Việt và tiếng Anh; trạng thái không chỉ dựa vào màu; touch target tối thiểu 44px, input mobile tối thiểu 16px.
- Không sửa hoặc stage các file user-owned đã exclude; sau mỗi task cập nhật `C:\Users\nguye\OneDrive\Desktop\FSellingV2\PROGRESS.md` (nằm ngoài Git repo).
- Mọi commit bắt buộc chạy `./test-commit.ps1 "message"`; không dùng `git commit` trực tiếp.

---

## File and Responsibility Map

### Create

- `fselling/models/fnb.py` — area, table, session, session-table history, draft line và immutable operation/audit ledger của R1A.
- `fselling/schemas/fnb.py` — request contract, giới hạn chuỗi/số lượng và literal state.
- `fselling/services/fnb_service.py` — tenant/feature gate, shop lock, idempotency, revision, floor read-model và lifecycle R1A.
- `fselling/routers/fnb.py` — route mỏng dưới `/api/fnb`.
- `migrations/versions/0009_fnb_table_service_r1a.py` — forward-only schema + `verify()`.
- `tests/test_migration_0009_fnb_r1a.py` — migration/verify/adoption regression.
- `tests/test_fnb_r1a_setup.py` — flag, area/table, tenant, permission và floor read-model.
- `tests/test_fnb_r1a_sessions.py` — open/move/merge/cancel, line draft, concurrency và idempotency.
- `static/fnb.html` — page shell cho khu vực, floor và session drawer.
- `static/css/fnb-r1a.css` — responsive floor grid, drawer và loading/error/empty states.
- `static/js/fnb-r1a.js` — race-safe controller, polling 2 giây, local unsent draft và rendering.
- `static/js/locales/fnb.js` — tiếng Việt/Anh riêng cho F&B.
- `tests/js/fnb-r1a.test.js` — Node harness cho controller/race/render/escaping.
- `tests/test_fnb_r1a_ui.py` — asset, route, locale và Node harness contract.

### Modify

- `fselling/models/shop.py` — `fnb_enabled`, `fnb_revision`.
- `fselling/models/__init__.py` — đăng ký model F&B.
- `fselling/main.py` — include F&B router trước static mount.
- `fselling/services/shop_service.py` — chặn hard-delete shop đã có cấu hình/lịch sử F&B.
- `fselling/services/catalog_service.py` — chặn hard-delete product đã có dòng món F&B; hướng dẫn Ẩn.
- `fselling/routers/pages.py` — `/fnb` và redirect `/fnb.html`.
- `fselling/dependencies.py` — `PERMISSION_FNB_SERVICE` và `PERMISSION_FNB_MANAGE`; CASHIER phục vụ bàn, MANAGER phục vụ + thiết lập, WAREHOUSE không được.
- `migrations/checksums.json` — append checksum revision 0009, không sửa checksum cũ.
- `tests/test_migration_i04.py`, `tests/test_migration_i05.py`, `tests/test_migration_0004_offline.py`, `tests/test_migration_0005_offline_issue_lifecycle.py`, `tests/test_migration_0006_offline_receipt_items.py`, `tests/test_migration_0007_qr_payment_domain.py`, `tests/test_offline_lease_identity.py` — cập nhật duy nhất các head-path/current-head expectations cho revision 0009; historical target 0004–0008 vẫn giữ nguyên.
- `static/pos.html` — một entry `Bán tại bàn`, ẩn mặc định.
- `static/js/pos.js` — chỉ cập nhật visibility/link theo shop đã load; không nhúng state F&B.
- `static/js/api.js` — giữ object `detail` có code/snapshot trên Error để F&B phục hồi 409; vẫn hiển thị message chuỗi.
- `static/js/locales/pos.js` — nhãn entry và trạng thái feature-disabled.
- `static/seller.html` — switch owner bật/tắt bán tại bàn trong form cửa hàng.
- `static/js/seller.js` — gọi settings API riêng, rollback switch khi lỗi.
- `static/js/locales/seller.js` — nhãn/mô tả switch F&B Việt/Anh.
- `tests/conftest.py` — helper tạo shop F&B/area/table dùng chung.
- `PROGRESS.md` ngoài repo — checkpoint sau từng task.

### Explicitly unchanged in R1A

- `fselling/services/order_service.py`, `inventory_service.py`, `payment_service.py`, model `Order*`, QR, voucher, loyalty, debt, receipt và ca bán hàng.
- Product station, Bếp/Bar, manager PIN, stock allocation, tạm tính, split check và checkout; các phần này thuộc plan R1B/R1C sau khi R1A đạt gate.
- POS retail offline state machine và service worker cache contract ngoài việc nạp entry `/fnb` online.

---

### Task 1: Forward-Only R1A Domain Schema

**Files:**

- Create: `fselling/models/fnb.py`
- Create: `migrations/versions/0009_fnb_table_service_r1a.py`
- Create: `tests/test_migration_0009_fnb_r1a.py`
- Modify: `fselling/models/shop.py:1-27`
- Modify: `fselling/models/__init__.py:1-110`
- Modify: `migrations/checksums.json:39-44`
- Modify: head-sensitive migration tests returned by `rg -n "0008_purchase_orders|HEAD_PATH" tests`

**Interfaces:**

- Consumes: `fselling.core.database.Base`, existing `Shop`, `User`, `Product` IDs and forward-only migration coordinator.
- Produces: `FnbArea`, `FnbTable`, `FnbServiceSession`, `FnbSessionTable`, `FnbSessionLine`, `FnbActionLog`; `Shop.fnb_enabled: bool`; `Shop.fnb_revision: int`.

- [ ] **Step 1: Write the failing migration shape test**

Create `tests/test_migration_0009_fnb_r1a.py` using the `MigrationCoordinator`/`StaticInventory` pattern from `tests/test_migration_0007_qr_payment_domain.py`. The core setup/assertions must be:

```python
import sqlite3
from pathlib import Path

import pytest

from fselling.migration.coordinator import MigrationCoordinator
from fselling.migration.topology import StaticInventory

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FNB_R1A = "0009_fnb_table_service_r1a"
EXPECTED_TABLES = {
    "fnb_areas", "fnb_tables", "fnb_service_sessions",
    "fnb_session_tables", "fnb_session_lines", "fnb_action_logs",
}

def coordinator(path):
    return MigrationCoordinator(
        path, project_root=PROJECT_ROOT, inventory_provider=StaticInventory()
    )


def test_0008_to_0009_adds_schema_and_defaults_existing_shop_off(tmp_path):
    database = tmp_path / "fnb-r1a.db"
    runner = coordinator(database)
    assert runner.init() == ["0001_legacy_9cf7106_baseline"]
    runner.upgrade("0008_purchase_orders")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO users (id, username, hashed_password, role, is_verified, is_active) "
            "VALUES (1, 'owner-fnb', 'hash', 'SELLER', 1, 1)"
        )
        connection.execute(
            "INSERT INTO shops (id, name, bank_account_no, bank_code, is_active, owner_id) "
            "VALUES (1, 'FNB Shop', '', '', 1, 1)"
        )
    assert runner.upgrade("head") == [FNB_R1A]
    runner.verify()
    with sqlite3.connect(database) as connection:
        objects = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert EXPECTED_TABLES <= objects
        shop_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(shops)").fetchall()
        }
        assert {"fnb_enabled", "fnb_revision"} <= shop_columns
        assert connection.execute(
            "SELECT fnb_enabled, fnb_revision FROM shops WHERE id=1"
        ).fetchone() == (0, 0)

```

In a second test, insert valid owner/shop/area/table/two-session rows through a local SQL seed helper using `sqlite3.connect` with `PRAGMA foreign_keys=ON`. Insert one unreleased `fnb_session_tables` link, assert a second unreleased link for the same table raises `sqlite3.IntegrityError`, set the first link's `released_at`, then assert a later session link succeeds. Do not bypass foreign keys. Also assert invalid session statuses, nonpositive line quantities, duplicate `(shop_id, operation_id)`, duplicate normalized area/table names and a mismatched historical link are rejected or caught by `verify()`.

- [ ] **Step 2: Run the new migration test to verify red**

Run: `python -m pytest tests/test_migration_0009_fnb_r1a.py -q`

Expected: FAIL because revision `0009_fnb_table_service_r1a` and F&B tables do not exist.

- [ ] **Step 3: Add ORM models with only R1A fields**

Create `fselling/models/fnb.py` with these exact classes/columns. Use `datetime.datetime.utcnow`, `Boolean`, `CheckConstraint`, `Column`, `DateTime`, `ForeignKey`, `Index`, `Integer`, `String`, `Text` and relationships only where later serialization needs them:

```python
class FnbArea(Base):
    __tablename__ = "fnb_areas"
    __table_args__ = (
        Index("ux_fnb_areas_shop_name_key", "shop_id", "name_key", unique=True),
    )
    id = Column(Integer, primary_key=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    name_key = Column(String(100), nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)

class FnbTable(Base):
    __tablename__ = "fnb_tables"
    __table_args__ = (
        Index("ux_fnb_tables_area_name_key", "area_id", "name_key", unique=True),
    )
    id = Column(Integer, primary_key=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False, index=True)
    area_id = Column(Integer, ForeignKey("fnb_areas.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    name_key = Column(String(100), nullable=False)
    sort_order = Column(Integer, nullable=False, default=0)
    active = Column(Boolean, nullable=False, default=True)
    state_version = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)

class FnbServiceSession(Base):
    __tablename__ = "fnb_service_sessions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('OPEN','PARTIALLY_SETTLED','PAYMENT_PENDING','CLOSED','CANCELLED')",
            name="ck_fnb_sessions_status",
        ),
    )
    id = Column(Integer, primary_key=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False, index=True)
    status = Column(String(24), nullable=False, default="OPEN", index=True)
    revision = Column(Integer, nullable=False, default=0)
    merged_into_session_id = Column(Integer, ForeignKey("fnb_service_sessions.id"), nullable=True)
    opened_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    opened_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    closed_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    closed_at = Column(DateTime, nullable=True)

class FnbSessionTable(Base):
    __tablename__ = "fnb_session_tables"
    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("fnb_service_sessions.id"), nullable=False, index=True)
    table_id = Column(Integer, ForeignKey("fnb_tables.id"), nullable=False, index=True)
    added_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    released_at = Column(DateTime, nullable=True)

class FnbSessionLine(Base):
    __tablename__ = "fnb_session_lines"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_fnb_session_lines_quantity"),
        CheckConstraint("cancelled_quantity >= 0 AND cancelled_quantity <= quantity", name="ck_fnb_session_lines_cancelled"),
    )
    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("fnb_service_sessions.id"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    product_name = Column(String(300), nullable=False)
    unit_price_vnd = Column(Integer, nullable=False)
    note = Column(String(500), nullable=True)
    quantity = Column(Integer, nullable=False)
    cancelled_quantity = Column(Integer, nullable=False, default=0)
    created_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    state_version = Column(Integer, nullable=False, default=0)

class FnbActionLog(Base):
    __tablename__ = "fnb_action_logs"
    __table_args__ = (
        Index("ux_fnb_action_shop_operation", "shop_id", "operation_id", unique=True),
    )
    id = Column(Integer, primary_key=True)
    shop_id = Column(Integer, ForeignKey("shops.id"), nullable=False, index=True)
    session_id = Column(Integer, ForeignKey("fnb_service_sessions.id"), nullable=True, index=True)
    actor_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    action = Column(String(64), nullable=False)
    operation_id = Column(String(128), nullable=False)
    operation_fingerprint = Column(String(64), nullable=False)
    result_json = Column(Text, nullable=False)
    before_json = Column(Text, nullable=True)
    after_json = Column(Text, nullable=True)
    reason = Column(String(500), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
```

Add `fnb_enabled = Column(Boolean, nullable=False, default=False)` and `fnb_revision = Column(Integer, nullable=False, default=0)` to `Shop`. Import/export all six F&B models in `fselling/models/__init__.py` so SQLAlchemy registers every FK target.

- [ ] **Step 4: Create the forward-only migration and verifier**

Create `migrations/versions/0009_fnb_table_service_r1a.py` with:

```python
revision = "0009_fnb_table_service_r1a"
down_revision = "0008_purchase_orders"
branch_labels = None
depends_on = None
```

The DDL must mirror the ORM fields and add:

```sql
ALTER TABLE shops ADD COLUMN fnb_enabled BOOLEAN NOT NULL DEFAULT 0;
ALTER TABLE shops ADD COLUMN fnb_revision INTEGER NOT NULL DEFAULT 0;
CREATE UNIQUE INDEX ux_fnb_active_session_table
ON fnb_session_tables (table_id) WHERE released_at IS NULL;
CREATE INDEX ix_fnb_floor_area ON fnb_tables (shop_id, area_id, active, sort_order);
CREATE INDEX ix_fnb_sessions_shop_status ON fnb_service_sessions (shop_id, status);
CREATE INDEX ix_fnb_lines_session_created ON fnb_session_lines (session_id, created_at);
```

Follow revision 0008's `_execute()`, `upgrade()`, `verify(connection)` and forward-only `downgrade()` convention. `verify()` must enumerate every required table/index/column and reject: unknown session status, cross-shop area/table/session/product references, two unreleased links for one table, invalid quantities and a closed/cancelled session with an unreleased table link. Product station and manager approver columns are deliberately absent until R1B has code that uses them.

- [ ] **Step 5: Update the immutable migration checksum registry**

Compute only the new file hash:

```powershell
(Get-FileHash migrations/versions/0009_fnb_table_service_r1a.py -Algorithm SHA256).Hash.ToLower()
```

Append one `0009_fnb_table_service_r1a` object to `migrations/checksums.json` with `down_revision`, relative `path` and that exact hash. Do not recalculate or edit revisions 0001–0008.

Update every test that means “current graph head” to append/expect `0009_fnb_table_service_r1a`. Do not mechanically replace every `0008_purchase_orders`: assertions explicitly upgrading to, verifying, truncating or fault-injecting at revision 0008 must continue to say 0008. In copied-graph tests that remove future revisions to simulate an older release, remove 0009 and its manifest entry before constructing `MigrationCoordinator`. Use `rg -n "0008_purchase_orders|HEAD_PATH" tests` to review each occurrence and require `tests/test_migration_i04.py` plus revisions 0004–0007 suites to pass in Step 6.

- [ ] **Step 6: Run migration, model and baseline schema tests**

Run:

```powershell
python -m pytest tests/test_migration_0009_fnb_r1a.py tests/test_migration_i04.py tests/test_migration_i05.py tests/test_migration_0004_offline.py tests/test_migration_0005_offline_issue_lifecycle.py tests/test_migration_0006_offline_receipt_items.py tests/test_migration_0007_qr_payment_domain.py tests/test_migration_product_id.py tests/test_offline_lease_identity.py -q
python -m pytest tests/test_staff_schema.py tests/test_customer_schema.py tests/test_orders.py -q
```

Expected: all pass; existing database adopts 0009 forward, new database builds to 0009, verifier detects tampering, and retail models still load.

- [ ] **Step 7: Update progress and commit Task 1 through the mandatory gate**

Record schema names, test counts and provider boundary in root `PROGRESS.md`, then inspect `git status --short` and run:

```powershell
.\test-commit.ps1 "Add F&B table service R1A schema"
```

Expected: JS syntax and full pytest pass; commit contains only Task 1 paths and `migrations/checksums.json`.

---

### Task 2: Feature Gate, Setup API and Floor Read Model

**Files:**

- Create: `fselling/schemas/fnb.py`
- Create: `fselling/services/fnb_service.py`
- Create: `fselling/routers/fnb.py`
- Create: `tests/test_fnb_r1a_setup.py`
- Modify: `fselling/dependencies.py:16-49`
- Modify: `fselling/main.py:1-30,237-265`
- Modify: `tests/conftest.py:215-293`

**Interfaces:**

- Consumes: Task 1 models, `require_shop_access`, `require_own_shop`, `inventory_service.lock_shop_for_inventory`, `PERMISSION_CATALOG_READ` and `Product.price`.
- Produces: `PATCH /api/fnb/shops/{shop_id}/settings`, area/table CRUD subset, `GET /api/fnb/floor`, stable F&B error bodies and test helpers `enable_fnb`, `create_fnb_area`, `create_fnb_table`.

- [ ] **Step 1: Write failing feature, tenant and floor tests**

Create `tests/test_fnb_r1a_setup.py`:

```python
from conftest import auth, new_staff, seller_with_shop

def test_fnb_is_off_by_default_and_only_owner_can_enable(client):
    ctx = seller_with_shop(client)
    off = client.get(
        "/api/fnb/floor", params={"shop_id": ctx["shop_id"]},
        headers=auth(ctx["token"]),
    )
    assert off.status_code == 409
    assert off.json()["detail"]["code"] == "FNB_DISABLED"

    _, cashier = new_staff(client, ctx, "CASHIER")
    denied = client.patch(
        f"/api/fnb/shops/{ctx['shop_id']}/settings",
        json={"enabled": True, "expected_revision": 0,
              "operation_id": "enable-fnb-staff-0001"},
        headers=auth(cashier),
    )
    assert denied.status_code in {403, 404}

    enabled = client.patch(
        f"/api/fnb/shops/{ctx['shop_id']}/settings",
        json={"enabled": True, "expected_revision": 0,
              "operation_id": "enable-fnb-owner-0001"},
        headers=auth(ctx["token"]),
    )
    assert enabled.status_code == 200
    assert enabled.json() == {"shop_id": ctx["shop_id"], "fnb_enabled": True, "fnb_revision": 1}

def test_area_table_floor_is_tenant_scoped_and_stably_sorted(client):
    first = seller_with_shop(client)
    second = seller_with_shop(client)
    enable_fnb(client, first)
    enable_fnb(client, second)
    patio = create_fnb_area(client, first, "Ngoài sân", sort_order=20)
    hall = create_fnb_area(client, first, "Trong nhà", sort_order=10)
    table_2 = create_fnb_table(client, first, hall["id"], "Bàn 2", sort_order=20)
    table_1 = create_fnb_table(client, first, hall["id"], "Bàn 1", sort_order=10)

    body = client.get(
        "/api/fnb/floor", params={"shop_id": first["shop_id"]},
        headers=auth(first["token"]),
    ).json()
    assert [area["id"] for area in body["areas"]] == [hall["id"], patio["id"]]
    assert [row["id"] for row in body["areas"][0]["tables"]] == [table_1["id"], table_2["id"]]
    assert body["areas"][0]["tables"][0]["state"] == "EMPTY"
    assert "cost_price" not in str(body)

    cross = client.get(
        "/api/fnb/floor", params={"shop_id": first["shop_id"]},
        headers=auth(second["token"]),
    )
    assert cross.status_code == 403
```

Add tests that assert: trimmed/casefolded duplicate area/table names fail; a table cannot reference another shop's area; inactive areas/tables stay in history but are omitted from the active floor; CASHIER can read/serve but cannot create/update areas or tables; MANAGER can configure; WAREHOUSE is 403; `after_revision` equal to current returns `{"changed": false, "fnb_revision": N}` without areas; unknown IDs never leak cross-tenant existence; disabling F&B while any session is OPEN/PARTIALLY_SETTLED/PAYMENT_PENDING is rejected with `FNB_ACTIVE_SESSION`, while disabling after all sessions close preserves history.

For settings, area and table mutations, assert a stale floor revision returns 409 `FNB_FLOOR_CHANGED` before any row changes; retrying the exact committed request returns its original response even after the shop revision advances; and reusing its operation ID with a different name/enabled value returns `FNB_OPERATION_REUSED`.

- [ ] **Step 2: Run setup tests to verify red**

Run: `python -m pytest tests/test_fnb_r1a_setup.py -q`

Expected: collection or route failures because schemas/router/service do not exist.

- [ ] **Step 3: Add exact request schemas**

Create `fselling/schemas/fnb.py`:

```python
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field
from ..core.numeric_limits import MAX_SAFE_QUANTITY

OperationId = str


class FnbRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

class FnbSettingsUpdate(FnbRequest):
    enabled: bool
    expected_revision: int = Field(ge=0, le=MAX_SAFE_QUANTITY)
    operation_id: OperationId = Field(min_length=8, max_length=128)

class FnbAreaCreate(FnbRequest):
    shop_id: int
    name: str = Field(min_length=1, max_length=100)
    sort_order: int = Field(default=0, ge=0, le=MAX_SAFE_QUANTITY)
    expected_revision: int = Field(ge=0, le=MAX_SAFE_QUANTITY)
    operation_id: OperationId = Field(min_length=8, max_length=128)

class FnbAreaUpdate(FnbRequest):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    sort_order: Optional[int] = Field(default=None, ge=0, le=MAX_SAFE_QUANTITY)
    active: Optional[bool] = None
    expected_revision: int = Field(ge=0, le=MAX_SAFE_QUANTITY)
    operation_id: OperationId = Field(min_length=8, max_length=128)

class FnbTableCreate(FnbRequest):
    shop_id: int
    area_id: int
    name: str = Field(min_length=1, max_length=100)
    sort_order: int = Field(default=0, ge=0, le=MAX_SAFE_QUANTITY)
    expected_revision: int = Field(ge=0, le=MAX_SAFE_QUANTITY)
    operation_id: OperationId = Field(min_length=8, max_length=128)

class FnbTableUpdate(FnbRequest):
    area_id: Optional[int] = None
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    sort_order: Optional[int] = Field(default=None, ge=0, le=MAX_SAFE_QUANTITY)
    active: Optional[bool] = None
    expected_revision: int = Field(ge=0, le=MAX_SAFE_QUANTITY)
    expected_state_version: int = Field(ge=0, le=MAX_SAFE_QUANTITY)
    operation_id: OperationId = Field(min_length=8, max_length=128)
```

Do not add a generic schema factory or repository layer. Session schemas are added in Task 3 when their service exists.

- [ ] **Step 4: Add F&B permission and shared service primitives**

In `fselling/dependencies.py`, add `PERMISSION_FNB_SERVICE = "FNB_SERVICE"` and `PERMISSION_FNB_MANAGE = "FNB_MANAGE"`. Grant SERVICE to CASHIER and MANAGER; grant MANAGE only to MANAGER. Do not change existing permissions. SELLER/ADMIN retain the dependency module's existing bypass, while the feature settings endpoint still uses `require_own_shop` and therefore remains owner-only.

Start `fselling/services/fnb_service.py` with stdlib `hashlib`, `json`, `unicodedata`, current UTC datetime, SQLAlchemy `Session`, the approved models/schemas and these public contracts/private helpers:

```python
def require_fnb_access(
    db: Session, shop_id: int, current_user: models.User, permission: str
) -> models.Shop:
    shop = require_shop_access(db, shop_id, current_user)
    require_staff_permission(current_user, permission)
    return shop


def require_fnb_shop(db: Session, shop_id: int, current_user: models.User) -> models.Shop:
    shop = require_fnb_access(
        db, shop_id, current_user, PERMISSION_FNB_SERVICE
    )
    if not bool(shop.fnb_enabled):
        raise fnb_error(409, "FNB_DISABLED", "Cửa hàng chưa bật bán tại bàn")
    return shop

def normalize_name(value: str) -> tuple[str, str]:
    display = unicodedata.normalize(
        "NFC", " ".join((value or "").strip().split())
    )
    if not display:
        raise fnb_error(400, "FNB_NAME_REQUIRED", "Tên không được để trống")
    return display, unicodedata.normalize("NFKC", display).casefold()

def operation_fingerprint(action: str, payload: dict) -> str:
    canonical = json.dumps(
        {"action": action, "payload": payload},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

def fnb_error(status_code: int, code: str, message: str, **extra) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": tr(message), **extra},
    )
```

Add `_existing_operation(db, shop_id, operation_id, fingerprint)` that returns parsed `result_json`, raises `FNB_OPERATION_REUSED` when fingerprint differs, and returns `None` when new. Add `_record_operation(db, *, shop_id, session_id, actor_user_id, action, operation_id, fingerprint, result, before=None, after=None, reason=None)` that writes compact sorted JSON to `FnbActionLog`. Every mutation follows this exact transaction order:

```python
def require_floor_revision(shop: models.Shop, expected_revision: int) -> None:
    current = int(shop.fnb_revision or 0)
    if current != int(expected_revision):
        raise fnb_error(
            409, "FNB_FLOOR_CHANGED", "Sơ đồ bàn vừa được cập nhật",
            revision=current,
        )
```

1. Authenticate tenant + exact permission with `require_fnb_access`; do not expose an operation across tenants.
2. `inventory_service.lock_shop_for_inventory(db, shop_id)` before any read that decides a write.
3. Refresh `Shop`, recheck idempotency under the lock and return the old result before checking current feature/state. This makes a response-lost retry stable even if the feature was disabled afterward.
4. For a new operation, call `require_floor_revision` for settings/setup/open mutations or `require_session_revision` for session mutations. Settings may enable an OFF shop; every other new F&B operation requires `fnb_enabled`. Validate tenant/row state, mutate and increment `shop.fnb_revision` once.
5. Flush, serialize authoritative result, append operation log, commit once.
6. On exception rollback; never call `log_system_action()` inside this transaction because it commits independently.

- [ ] **Step 5: Implement settings, area/table mutations and floor serialization**

Add service functions `update_fnb_settings(db, current_user, shop_id, request) -> dict`, `create_area(db, current_user, request) -> dict`, `update_area(db, current_user, area_id, request) -> dict`, `create_table(db, current_user, request) -> dict`, `update_table(db, current_user, table_id, request) -> dict` and `get_floor(db, current_user, shop_id, after_revision=None) -> dict`.

`update_fnb_settings` uses `require_own_shop`, shop lock, checks `expected_revision` and increments revision only when the value changes. Turning the feature off first checks that no nonterminal session remains; otherwise return 409 `FNB_ACTIVE_SESSION`. Area/table mutations require `PERMISSION_FNB_MANAGE`, check the floor revision and normalized keys; inactive records cannot accept new tables or sessions; an occupied table cannot be deactivated/moved. `get_floor` requires `PERMISSION_FNB_SERVICE` and returns:

```python
{
    "changed": True,
    "shop_id": shop.id,
    "fnb_revision": int(shop.fnb_revision),
    "areas": [{
        "id": area.id, "name": area.name, "sort_order": area.sort_order,
        "tables": [{
            "id": table.id, "name": table.name,
            "state_version": table.state_version, "state": "EMPTY",
            "session": None,
        }],
    }],
}
```

Sort areas/tables by `(sort_order, id)`. At R1A Task 2 all tables are empty; Task 3 replaces `state/session` from active links without changing the response shape.

- [ ] **Step 6: Add thin routes and register them**

Create `fselling/routers/fnb.py` with `router = APIRouter(prefix="/api/fnb", tags=["fnb"])` and these routes:

```python
@router.patch("/shops/{shop_id}/settings")
def patch_settings(shop_id: int, request: FnbSettingsUpdate, db=Depends(get_db), current_user=Depends(get_current_user)):
    return fnb_service.update_fnb_settings(db, current_user, shop_id, request)

@router.get("/floor")
def floor(shop_id: int, after_revision: int | None = Query(None, ge=0), db=Depends(get_db), current_user=Depends(get_current_user)):
    return fnb_service.get_floor(db, current_user, shop_id, after_revision)

@router.post("/areas")
def post_area(request: FnbAreaCreate, db=Depends(get_db), current_user=Depends(get_current_user)):
    return fnb_service.create_area(db, current_user, request)

@router.patch("/areas/{area_id}")
def patch_area(area_id: int, request: FnbAreaUpdate, db=Depends(get_db), current_user=Depends(get_current_user)):
    return fnb_service.update_area(db, current_user, area_id, request)

@router.post("/tables")
def post_table(request: FnbTableCreate, db=Depends(get_db), current_user=Depends(get_current_user)):
    return fnb_service.create_table(db, current_user, request)

@router.patch("/tables/{table_id}")
def patch_table(table_id: int, request: FnbTableUpdate, db=Depends(get_db), current_user=Depends(get_current_user)):
    return fnb_service.update_table(db, current_user, table_id, request)
```

Import/include the router in `fselling/main.py` before `pages.router` and the static mount.

- [ ] **Step 7: Add explicit reusable test helpers**

Append to `tests/conftest.py`:

```python
def enable_fnb(client, ctx: dict) -> dict:
    response = client.patch(
        f"/api/fnb/shops/{ctx['shop_id']}/settings",
        json={"enabled": True, "expected_revision": 0,
              "operation_id": f"enable-{uuid.uuid4().hex}"},
        headers=auth(ctx["token"]),
    )
    assert response.status_code == 200, response.text
    return response.json()

def create_fnb_area(client, ctx: dict, name="Khu A", sort_order=0) -> dict:
    floor = client.get("/api/fnb/floor", params={"shop_id": ctx["shop_id"]},
                       headers=auth(ctx["token"])).json()
    response = client.post("/api/fnb/areas", json={
        "shop_id": ctx["shop_id"], "name": name, "sort_order": sort_order,
        "expected_revision": floor["fnb_revision"],
        "operation_id": f"area-{uuid.uuid4().hex}",
    }, headers=auth(ctx["token"]))
    assert response.status_code == 200, response.text
    return response.json()

def create_fnb_table(client, ctx: dict, area_id: int, name="Bàn 1", sort_order=0) -> dict:
    floor = client.get("/api/fnb/floor", params={"shop_id": ctx["shop_id"]},
                       headers=auth(ctx["token"])).json()
    response = client.post("/api/fnb/tables", json={
        "shop_id": ctx["shop_id"], "area_id": area_id,
        "name": name, "sort_order": sort_order,
        "expected_revision": floor["fnb_revision"],
        "operation_id": f"table-{uuid.uuid4().hex}",
    }, headers=auth(ctx["token"]))
    assert response.status_code == 200, response.text
    return response.json()
```

- [ ] **Step 8: Run setup, authorization and retail regression tests**

Run:

```powershell
python -m pytest tests/test_fnb_r1a_setup.py tests/test_authorization.py tests/test_staff_roles.py tests/test_staff_access.py tests/test_shops.py tests/test_orders.py -q
```

Expected: all pass; disabled feature is fail-closed, tenant/permission boundaries hold, and retail role presets retain all existing permissions.

Before this gate, add `_has_fnb_data(db, shop_id)` to `shop_service.py` and reject hard-delete with HTTP 409 once any `FnbArea`, `FnbServiceSession` or `FnbActionLog` exists; tell the owner to khóa the shop to retain history. In `catalog_service.delete_product`, under the existing shop inventory lock, reject hard-delete when any `FnbSessionLine.product_id` references the product and tell the user to Ẩn it. Add one regression for each path to `tests/test_fnb_r1a_setup.py`; disabling the feature must not delete either history or these references.

- [ ] **Step 9: Update progress and commit Task 2 through the mandatory gate**

Record API contract and test evidence in root `PROGRESS.md`, inspect only Task 2 paths, then run:

```powershell
.\test-commit.ps1 "Add F&B floor setup API"
```

Expected: full gate passes and the commit does not contain UI, session lifecycle, inventory or payment changes.

---

### Task 3: Revision-Safe Session and Draft-Line Lifecycle

**Files:**

- Create: `tests/test_fnb_r1a_sessions.py`
- Modify: `fselling/schemas/fnb.py`
- Modify: `fselling/services/fnb_service.py`
- Modify: `fselling/routers/fnb.py`
- Modify: `tests/conftest.py`

**Interfaces:**

- Consumes: Task 2 operation ledger, floor serializer, shop lock and F&B permission/feature gates.
- Produces: `open_session`, `get_session`, `add_line`, `update_line`, `cancel_line`, `move_table`, `merge_table`, `cancel_session` plus their `/api/fnb/sessions` routes. Every success returns one authoritative session snapshot.

- [ ] **Step 1: Write failing open/retry/revision tests**

Create `tests/test_fnb_r1a_sessions.py` with a fixture that enables F&B and creates two areas, three tables and two products. Add:

```python
def open_session(client, ctx, table, operation_id="open-session-0001",
                 expected_revision=None, expected_table_version=None):
    if expected_revision is None or expected_table_version is None:
        floor = client.get(
            "/api/fnb/floor", params={"shop_id": ctx["shop_id"]},
            headers=auth(ctx["token"]),
        ).json()
        expected_revision = floor["fnb_revision"] if expected_revision is None else expected_revision
        if expected_table_version is None:
            current = next(
                row for area in floor["areas"] for row in area["tables"]
                if row["id"] == table["id"]
            )
            expected_table_version = current["state_version"]
    return client.post("/api/fnb/sessions", json={
        "shop_id": ctx["shop_id"],
        "table_id": table["id"],
        "expected_revision": expected_revision,
        "expected_table_version": expected_table_version,
        "operation_id": operation_id,
    }, headers=auth(ctx["token"]))


def test_open_session_is_idempotent_and_one_table_has_one_active_session(client, fnb_ctx):
    floor_revision = client.get(
        "/api/fnb/floor", params={"shop_id": fnb_ctx["shop_id"]},
        headers=auth(fnb_ctx["token"]),
    ).json()["fnb_revision"]
    first = open_session(
        client, fnb_ctx, fnb_ctx["table_1"], expected_revision=floor_revision,
        expected_table_version=fnb_ctx["table_1"]["state_version"],
    )
    assert first.status_code == 200, first.text
    session = first.json()
    assert session["status"] == "OPEN"
    assert session["revision"] == 0
    assert [row["id"] for row in session["tables"]] == [fnb_ctx["table_1"]["id"]]

    retry = open_session(
        client, fnb_ctx, fnb_ctx["table_1"], expected_revision=floor_revision,
        expected_table_version=fnb_ctx["table_1"]["state_version"],
    )
    assert retry.status_code == 200
    assert retry.json() == session

    reused = client.post("/api/fnb/sessions", json={
        "shop_id": fnb_ctx["shop_id"],
        "table_id": fnb_ctx["table_2"]["id"],
        "expected_revision": client.get(
            "/api/fnb/floor", params={"shop_id": fnb_ctx["shop_id"]},
            headers=auth(fnb_ctx["token"]),
        ).json()["fnb_revision"],
        "expected_table_version": fnb_ctx["table_2"]["state_version"],
        "operation_id": "open-session-0001",
    }, headers=auth(fnb_ctx["token"]))
    assert reused.status_code == 409
    assert reused.json()["detail"]["code"] == "FNB_OPERATION_REUSED"

    occupied = open_session(
        client, fnb_ctx, fnb_ctx["table_1"], "open-session-0002"
    )
    assert occupied.status_code == 409
    assert occupied.json()["detail"]["code"] == "FNB_TABLE_OCCUPIED"


def test_stale_session_revision_returns_current_snapshot_without_partial_write(client, fnb_ctx):
    session = open_session(client, fnb_ctx, fnb_ctx["table_1"]).json()
    added = client.post(f"/api/fnb/sessions/{session['id']}/lines", json={
        "product_id": fnb_ctx["product_1"]["id"], "quantity": 2,
        "note": "Ít đá", "expected_revision": 0,
        "operation_id": "add-line-00000001",
    }, headers=auth(fnb_ctx["token"]))
    assert added.status_code == 200
    assert added.json()["revision"] == 1

    stale = client.post(f"/api/fnb/sessions/{session['id']}/lines", json={
        "product_id": fnb_ctx["product_2"]["id"], "quantity": 1,
        "note": None, "expected_revision": 0,
        "operation_id": "add-line-00000002",
    }, headers=auth(fnb_ctx["token"]))
    assert stale.status_code == 409
    detail = stale.json()["detail"]
    assert detail["code"] == "FNB_SESSION_CHANGED"
    assert detail["snapshot"]["revision"] == 1
    assert len(detail["snapshot"]["lines"]) == 1
```

- [ ] **Step 2: Add failing move/merge/cancel and tenant tests**

Add tests that prove:

```python
def test_move_changes_only_table_links_and_preserves_session(client, fnb_ctx):
    session = open_session(client, fnb_ctx, fnb_ctx["table_1"]).json()
    moved = client.post(f"/api/fnb/sessions/{session['id']}/move-table", json={
        "from_table_id": fnb_ctx["table_1"]["id"],
        "to_table_id": fnb_ctx["table_2"]["id"],
        "expected_revision": session["revision"],
        "expected_from_state_version": fnb_ctx["table_1"]["state_version"] + 1,
        "expected_to_state_version": fnb_ctx["table_2"]["state_version"],
        "operation_id": "move-table-000001",
    }, headers=auth(fnb_ctx["token"]))
    assert moved.status_code == 200, moved.text
    body = moved.json()
    assert body["id"] == session["id"]
    assert [table["id"] for table in body["tables"]] == [fnb_ctx["table_2"]["id"]]


def test_merge_two_draft_sessions_moves_lines_and_preserves_line_ids(client, fnb_ctx):
    source = open_session(client, fnb_ctx, fnb_ctx["table_1"], "open-source-0001").json()
    target = open_session(client, fnb_ctx, fnb_ctx["table_2"], "open-target-0001").json()
    source = add_test_line(client, fnb_ctx, source, fnb_ctx["product_1"], "source-line-0001")
    target = add_test_line(client, fnb_ctx, target, fnb_ctx["product_2"], "target-line-0001")
    original_line_ids = {source["lines"][0]["id"], target["lines"][0]["id"]}

    merged = client.post(f"/api/fnb/sessions/{source['id']}/merge-table", json={
        "target_table_id": fnb_ctx["table_2"]["id"],
        "expected_revision": source["revision"],
        "expected_target_session_revision": target["revision"],
        "expected_target_table_version": fnb_ctx["table_2"]["state_version"] + 1,
        "operation_id": "merge-table-00001",
    }, headers=auth(fnb_ctx["token"]))
    assert merged.status_code == 200, merged.text
    assert {line["id"] for line in merged.json()["lines"]} == original_line_ids
    assert {table["id"] for table in merged.json()["tables"]} == {
        fnb_ctx["table_1"]["id"], fnb_ctx["table_2"]["id"],
    }
```

Also assert: moving into occupied table is rejected; merging a stale target revision changes nothing; an empty target table is simply attached; source and target cannot be cross-shop; cancelling a nonempty session is rejected until all draft quantities are cancelled; cancel releases all active table links; inactive product cannot be added; product from another shop is 404; server snapshot price equals DB price even if a client adds an unknown `price` field (Pydantic should reject extra input by configuring F&B request models with `ConfigDict(extra="forbid")`).

Add permission tests: CASHIER can open sessions and add/update/cancel draft quantities, but move/merge returns 403; MANAGER/owner can move and merge. Until R1B introduces one-use manager approval tokens, R1A must not simulate PIN or let a cashier bypass this boundary.

- [ ] **Step 3: Run session tests to verify red**

Run: `python -m pytest tests/test_fnb_r1a_sessions.py -q`

Expected: FAIL because session schemas/routes/service functions are absent.

- [ ] **Step 4: Add the session request contracts**

Append to `fselling/schemas/fnb.py`; every class inherits `FnbRequest`, so unknown client fields are rejected by the shared `ConfigDict(extra="forbid")` contract:

```python
class FnbSessionOpen(FnbRequest):
    shop_id: int
    table_id: int
    expected_revision: int = Field(ge=0, le=MAX_SAFE_QUANTITY)
    expected_table_version: int = Field(ge=0, le=MAX_SAFE_QUANTITY)
    operation_id: OperationId = Field(min_length=8, max_length=128)


class FnbLineCreate(FnbRequest):
    product_id: int
    quantity: int = Field(gt=0, le=MAX_SAFE_QUANTITY)
    note: Optional[str] = Field(default=None, max_length=500)
    expected_revision: int = Field(ge=0, le=MAX_SAFE_QUANTITY)
    operation_id: OperationId = Field(min_length=8, max_length=128)


class FnbLineUpdate(FnbRequest):
    quantity: int = Field(gt=0, le=MAX_SAFE_QUANTITY)
    note: Optional[str] = Field(default=None, max_length=500)
    expected_line_version: int = Field(ge=0, le=MAX_SAFE_QUANTITY)
    expected_revision: int = Field(ge=0, le=MAX_SAFE_QUANTITY)
    operation_id: OperationId = Field(min_length=8, max_length=128)


class FnbLineCancel(FnbRequest):
    line_id: int
    quantity: int = Field(gt=0, le=MAX_SAFE_QUANTITY)
    expected_line_version: int = Field(ge=0, le=MAX_SAFE_QUANTITY)
    expected_revision: int = Field(ge=0, le=MAX_SAFE_QUANTITY)
    operation_id: OperationId = Field(min_length=8, max_length=128)


class FnbMoveTable(FnbRequest):
    from_table_id: int
    to_table_id: int
    expected_revision: int = Field(ge=0, le=MAX_SAFE_QUANTITY)
    expected_from_state_version: int = Field(ge=0, le=MAX_SAFE_QUANTITY)
    expected_to_state_version: int = Field(ge=0, le=MAX_SAFE_QUANTITY)
    operation_id: OperationId = Field(min_length=8, max_length=128)


class FnbMergeTable(FnbRequest):
    target_table_id: int
    expected_revision: int = Field(ge=0, le=MAX_SAFE_QUANTITY)
    expected_target_session_revision: Optional[int] = Field(default=None, ge=0, le=MAX_SAFE_QUANTITY)
    expected_target_table_version: int = Field(ge=0, le=MAX_SAFE_QUANTITY)
    operation_id: OperationId = Field(min_length=8, max_length=128)


class FnbSessionCancel(FnbRequest):
    expected_revision: int = Field(ge=0, le=MAX_SAFE_QUANTITY)
    reason: Optional[str] = Field(default=None, max_length=500)
    operation_id: OperationId = Field(min_length=8, max_length=128)
```

- [ ] **Step 5: Implement one authoritative session serializer and revision guard**

In `fnb_service.py`, add:

```python
def serialize_session(db: Session, session: models.FnbServiceSession) -> dict:
    links = db.query(models.FnbSessionTable).filter(
        models.FnbSessionTable.session_id == session.id,
        models.FnbSessionTable.released_at.is_(None),
    ).order_by(models.FnbSessionTable.id).all()
    tables = []
    for link in links:
        table = db.query(models.FnbTable).filter(
            models.FnbTable.id == link.table_id,
            models.FnbTable.shop_id == session.shop_id,
        ).one()
        tables.append({
            "id": table.id, "area_id": table.area_id, "name": table.name,
            "state_version": int(table.state_version),
        })
    lines = db.query(models.FnbSessionLine).filter(
        models.FnbSessionLine.session_id == session.id,
    ).order_by(models.FnbSessionLine.id).all()
    serialized_lines = [{
        "id": line.id, "product_id": line.product_id,
        "product_name": line.product_name,
        "unit_price_vnd": int(line.unit_price_vnd),
        "note": line.note, "quantity": int(line.quantity),
        "cancelled_quantity": int(line.cancelled_quantity),
        "billable_quantity": int(line.quantity) - int(line.cancelled_quantity),
        "state_version": int(line.state_version),
    } for line in lines]
    subtotal = sum(
        line["unit_price_vnd"] * line["billable_quantity"]
        for line in serialized_lines
    )
    return {
        "id": session.id, "shop_id": session.shop_id,
        "status": session.status, "revision": int(session.revision),
        "opened_at": session.opened_at.isoformat() + "Z",
        "tables": tables, "lines": serialized_lines,
        "subtotal_vnd": subtotal,
        "unsent_quantity": sum(line["billable_quantity"] for line in serialized_lines),
    }


def require_session_revision(
    db: Session, session: models.FnbServiceSession, expected_revision: int
) -> None:
    if int(session.revision) != int(expected_revision):
        raise fnb_error(
            409, "FNB_SESSION_CHANGED", "Bàn vừa được cập nhật trên thiết bị khác",
            revision=int(session.revision), snapshot=serialize_session(db, session),
        )
```

Use checked integer multiplication/addition from `fselling.core.money` for subtotal; if the snippet's plain multiplication is copied literally, replace it before committing so overflow returns a stable 400 rather than producing an unbounded number.

- [ ] **Step 6: Implement open/get/add/update/cancel line operations**

Add concrete functions `open_session(db, current_user, request) -> dict`, `get_session(db, current_user, session_id) -> dict`, `add_line(db, current_user, session_id, request) -> dict`, `update_line(db, current_user, line_id, request) -> dict` and `cancel_line(db, current_user, session_id, request) -> dict`.

Implement each function following Task 2's transaction order. `open_session` validates table/area active and table `state_version`, inserts an unreleased link, increments the table version and shop floor revision, but leaves new session revision at 0. Draft line mutations require `session.status == "OPEN"`, verify product belongs to the same shop and is active, snapshot `name` and integer `price`, normalize blank note to `None`, then increment line/session/shop revisions once. Every add inserts a new line (never silently merges notes); update cannot reduce `quantity` below `cancelled_quantity`; cancellation cannot exceed billable quantity and only increments `cancelled_quantity`, never deletes a line. R1B adds/snapshots station when “Gửi Bếp/Bar” actually exists.

- [ ] **Step 7: Implement move, merge and cancel-session state transitions**

Add concrete functions `move_table(db, current_user, session_id, request) -> dict`, `merge_table(db, current_user, session_id, request) -> dict` and `cancel_session(db, current_user, session_id, request) -> dict`.

Implement the functions with these required transition rules:

1. `move_table`: source link must be active in the session; destination must be active, same shop and unoccupied. Release source link, create destination link, increment both table versions, session revision and shop revision.
2. `merge_table` to empty table: create one link and increment target table/session/shop revisions.
3. `merge_table` to another OPEN session: require exact target revision; release its active links and create new links for the source; move its draft line `session_id` values without changing line IDs; set target `status="CANCELLED"`, `merged_into_session_id=source.id`, close actor/time; increment both session revisions, all moved table versions and shop revision once.
4. Reject merging the same session/table twice, any non-OPEN session, missing target revision for occupied table, or a future non-draft artifact. The latter is expressed now as a helper `session_has_only_r1a_drafts()` returning true only because R1B/R1C tables do not exist yet; R1B must replace it with explicit ticket/check queries.
5. `cancel_session`: allowed only when every line has `billable_quantity == 0`; release all links, increment their table versions, mark session CANCELLED and increment session/shop revisions.

Require `PERMISSION_FNB_MANAGE` at the start of `move_table` and `merge_table`; all other R1A session mutations use `PERMISSION_FNB_SERVICE`. This preserves the approved security boundary without prematurely implementing R1B manager PIN tokens.

- [ ] **Step 8: Add routes and update the floor read-model**

Add routes matching the approved spec:

```python
@router.post("/sessions")
@router.get("/sessions/{session_id}")
@router.post("/sessions/{session_id}/lines")
@router.patch("/lines/{line_id}")
@router.post("/sessions/{session_id}/cancel-line")
@router.post("/sessions/{session_id}/move-table")
@router.post("/sessions/{session_id}/merge-table")
@router.post("/sessions/{session_id}/cancel")
```

Each route only delegates typed request + auth/db dependencies to the matching service function. Update `get_floor()` to join unreleased links and return table state `SERVING`, with session summary:

```python
{
    "id": session.id,
    "revision": session.revision,
    "opened_at": session.opened_at.isoformat() + "Z",
    "subtotal_vnd": subtotal,
    "unsent_quantity": unsent_quantity,
    "table_count": active_link_count,
}
```

Do not return notes, cost, customer information or complete lines in floor polling.

- [ ] **Step 9: Run focused lifecycle and invariant tests**

Run:

```powershell
python -m pytest tests/test_fnb_r1a_sessions.py tests/test_fnb_r1a_setup.py tests/test_authorization.py tests/test_orders.py tests/test_stock_adjust.py -q
```

Expected: all pass. Additionally query DB in tests to assert no `Order`, `OrderItem`, `OrderPayment`, `FnbKitchenTicket` or inventory mutation occurred; because R1B models do not yet exist, the test checks unchanged `Product.stock` and unchanged counts in existing order tables.

- [ ] **Step 10: Update progress and commit Task 3 through the mandatory gate**

Record lifecycle, stale-revision, retry and no-inventory evidence in `PROGRESS.md`; inspect the diff, then run:

```powershell
.\test-commit.ps1 "Add F&B table session lifecycle"
```

Expected: full gate passes; commit contains only schemas/service/router/tests/helper changes from Task 3.

---

### Task 4: Dedicated Floor UI, Polling and Local Acceptance Gate

**Files:**

- Create: `static/fnb.html`
- Create: `static/css/fnb-r1a.css`
- Create: `static/js/fnb-r1a.js`
- Create: `static/js/locales/fnb.js`
- Create: `tests/js/fnb-r1a.test.js`
- Create: `tests/test_fnb_r1a_ui.py`
- Modify: `fselling/routers/pages.py:22-76`
- Modify: `static/pos.html:63-96,540-582`
- Modify: `static/js/pos.js:461-570`
- Modify: `static/js/api.js:253-267`
- Modify: `static/js/locales/pos.js`
- Modify: `static/seller.html:2107-2132`
- Modify: `static/js/seller.js:1842-1937`
- Modify: `static/js/locales/seller.js`
- Modify only if browser QA proves a defect: Task 1–3 F&B paths.

**Interfaces:**

- Consumes: `GET /api/shops`, `GET /api/products/{shop_id}`, all R1A APIs, global `apiCall`, global i18n and `localStorage.currentShopId`.
- Produces: `/fnb`, owner feature switch, POS entry visible only for enabled shops, race-safe floor/session controller and verified local R1A release candidate.

- [ ] **Step 1: Write failing page/asset/locale contract tests**

Create `tests/test_fnb_r1a_ui.py`:

```python
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_fnb_page_and_assets_are_wired(client):
    page = client.get("/fnb")
    assert page.status_code == 200
    html = page.text
    assert 'id="fnbFloor"' in html
    assert 'id="fnbSessionPanel"' in html
    assert 'id="fnbLiveStatus"' in html
    assert 'id="fnbSetupOpen"' in html
    assert 'id="fnbSetupDialog"' in html
    assert '/css/fnb-r1a.css?' in html
    assert '/js/locales/fnb.js?' in html
    assert '/js/fnb-r1a.js?' in html
    api_source = (ROOT / "static/js/api.js").read_text(encoding="utf-8")
    assert "error.detail =" in api_source


def test_pos_entry_is_hidden_until_shop_capability_is_known():
    html = (ROOT / "static/pos.html").read_text(encoding="utf-8")
    assert 'id="btnTableService"' in html
    assert 'hidden' in html.split('id="btnTableService"', 1)[1].split('>', 1)[0]


def test_fnb_controller_node_harness():
    result = subprocess.run(
        ["node", "tests/js/fnb-r1a.test.js"], cwd=ROOT,
        text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
```

Also assert `/fnb.html` redirects to `/fnb`; seller switch exists only in owner shop-edit UI; every `fnb.*`, `pos.mode.table_service` and seller F&B key exists in both `vi` and `en`; no inline `onclick` is used inside dynamically rendered floor/session content.

- [ ] **Step 2: Write the failing controller harness first**

Create `tests/js/fnb-r1a.test.js` with `node:assert/strict`, a fake request function and a tiny fake storage/renderer. The minimum executable cases are:

```javascript
const assert = require('node:assert/strict');
const { createController, escapeHtml } = require('../../static/js/fnb-r1a.js');

async function testLateFloorResponseIsIgnoredAfterShopChange() {
    const pending = [];
    const controller = createController({
        request: endpoint => new Promise(resolve => pending.push({ endpoint, resolve })),
        render: () => {}, setTimeoutFn: () => 1, clearTimeoutFn: () => {},
        storage: new Map(), now: () => 1_000,
    });
    const first = controller.selectShop(1);
    const second = controller.selectShop(2);
    pending.find(row => row.endpoint.includes('shop_id=2')).resolve({
        changed: true, shop_id: 2, fnb_revision: 2, areas: [],
    });
    await second;
    pending.find(row => row.endpoint.includes('shop_id=1')).resolve({
        changed: true, shop_id: 1, fnb_revision: 9, areas: [{ id: 9, tables: [] }],
    });
    await first;
    assert.equal(controller.getState().shopId, 2);
    assert.deepEqual(controller.getState().floor.areas, []);
}


async function testConflictKeepsDraftAndUsesAuthoritativeSnapshot() {
    const draft = { product_id: 7, quantity: 2, note: 'Ít đá' };
    const latest = { id: 4, revision: 3, lines: [] };
    const controller = createController({
        request: async () => {
            const error = new Error('changed');
            error.status = 409;
            error.detail = { code: 'FNB_SESSION_CHANGED', snapshot: latest };
            throw error;
        },
        render: () => {}, setTimeoutFn: () => 1, clearTimeoutFn: () => {},
        storage: new Map(), now: () => 2_000,
    });
    controller.seedSession({ id: 4, revision: 2, lines: [] });
    await assert.rejects(controller.addLine(draft));
    assert.deepEqual(controller.getState().session, latest);
    assert.deepEqual(controller.getState().recoverableDraft, draft);
}

assert.equal(escapeHtml('<img src=x onerror=alert(1)>'), '&lt;img src=x onerror=alert(1)&gt;');
Promise.resolve()
    .then(testLateFloorResponseIsIgnoredAfterShopChange)
    .then(testConflictKeepsDraftAndUsesAuthoritativeSnapshot)
    .then(() => process.stdout.write('fnb-r1a controller ok\n'));
```

Add cases for: poll uses current floor revision; unchanged response preserves DOM data; background interval is 10 seconds and foreground interval is 2 seconds; dispose cancels timers; double-click shares one pending mutation; retry reuses the same operation ID; same ID is replaced only after definitive 4xx; session draft key includes username + shop + session; cancel/move/merge use the latest revision; all user strings are escaped.

Add controller cases for authorized setup mutations: create area/table uses one operation ID per click, update sends the latest `expected_state_version`, successful setup reloads the floor, duplicate-name 4xx keeps the dialog values, CASHIER/WAREHOUSE never receive a rendered setup control, and STAFF MANAGER does.

- [ ] **Step 3: Run UI tests to verify red**

Run:

```powershell
python -m pytest tests/test_fnb_r1a_ui.py -q
node tests/js/fnb-r1a.test.js
```

Expected: FAIL because page, assets and controller exports do not exist.

- [ ] **Step 4: Create the semantic `/fnb` page shell**

Add `/fnb` and `/fnb.html` handlers to `pages.py`, matching the existing `/pos` convention. Create `static/fnb.html` with this hierarchy and no business logic inline:

```html
<header class="fnb-header">
  <a class="fnb-back" href="/pos" data-i18n="fnb.back_to_counter">Bán tại quầy</a>
  <h1 data-i18n="fnb.title">Bán tại bàn</h1>
  <select id="fnbShopSelect" aria-label="Cửa hàng"></select>
</header>
<main class="fnb-shell">
  <section class="fnb-floor-column" aria-labelledby="fnbFloorTitle">
    <div class="fnb-floor-heading">
      <div><p class="eyebrow" data-i18n="fnb.floor.eyebrow">Sơ đồ phục vụ</p>
      <h2 id="fnbFloorTitle" data-i18n="fnb.floor.title">Chọn bàn để bắt đầu</h2></div>
      <button id="fnbSetupOpen" type="button" hidden data-i18n="fnb.setup.open">Thiết lập bàn</button>
      <button id="fnbRetry" type="button" hidden data-i18n="common.retry">Thử lại</button>
    </div>
    <nav id="fnbAreaTabs" aria-label="Khu vực"></nav>
    <div id="fnbFloor" class="fnb-floor-grid" aria-live="polite"></div>
    <p id="fnbLiveStatus" class="sr-only" role="status" aria-live="polite"></p>
  </section>
  <aside id="fnbSessionPanel" class="fnb-session-panel" aria-labelledby="fnbSessionTitle" hidden inert>
    <header><h2 id="fnbSessionTitle"></h2><button id="fnbSessionClose" type="button" aria-label="Đóng">×</button></header>
    <label for="fnbProductSearch" data-i18n="fnb.menu.search_label">Tìm món</label>
    <input id="fnbProductSearch" type="search" autocomplete="off" data-i18n-placeholder="fnb.menu.search_placeholder">
    <div id="fnbProductGrid"></div>
    <section aria-labelledby="fnbDraftTitle"><h3 id="fnbDraftTitle" data-i18n="fnb.draft.title">Món chưa gửi</h3><div id="fnbDraftLines"></div></section>
    <footer><strong id="fnbSubtotal"></strong><button id="fnbFutureSend" type="button" disabled data-i18n="fnb.send.r1b">Gửi Bếp/Bar — có ở R1B</button></footer>
  </aside>
</main>
<dialog id="fnbSetupDialog" aria-labelledby="fnbSetupTitle">
  <form method="dialog"><button value="cancel" aria-label="Đóng">×</button></form>
  <h2 id="fnbSetupTitle" data-i18n="fnb.setup.title">Khu vực và bàn</h2>
  <div id="fnbSetupAreas"></div>
  <form id="fnbAreaForm"><label for="fnbAreaName" data-i18n="fnb.setup.area_name">Tên khu vực</label><input id="fnbAreaName" maxlength="100" required><button type="submit" data-i18n="fnb.setup.add_area">Thêm khu vực</button></form>
  <form id="fnbTableForm"><label for="fnbTableArea" data-i18n="fnb.setup.area">Khu vực</label><select id="fnbTableArea" required></select><label for="fnbTableName" data-i18n="fnb.setup.table_name">Tên bàn</label><input id="fnbTableName" maxlength="100" required><button type="submit" data-i18n="fnb.setup.add_table">Thêm bàn</button></form>
  <p id="fnbSetupStatus" role="status" aria-live="polite"></p>
</dialog>
```

Load versioned common/i18n/api scripts, then `locales/fnb.js` and `fnb-r1a.js`. The disabled future-send button is explanatory, not a dead primary CTA; primary R1A actions are selecting a table and adding/editing drafts.

- [ ] **Step 5: Implement the controller as a browser/Node module**

Create `static/js/fnb-r1a.js` in an IIFE that exports through `module.exports` under Node and `window.FnbR1A` in browser. The controller state and floor loader must follow this concrete shape:

```javascript
function createController(deps) {
    const state = {
        shopId: null, floorRevision: null, floor: { areas: [] },
        session: null, requestEpoch: 0, pendingMutation: null,
        recoverableDraft: null, pollTimer: null, disposed: false,
    };
    const pollDelay = () => deps.isHidden?.() ? 10_000 : 2_000;

    async function loadFloor(force = false) {
        const shopId = Number(state.shopId);
        const epoch = ++state.requestEpoch;
        const suffix = !force && Number.isInteger(state.floorRevision)
            ? `&after_revision=${state.floorRevision}` : '';
        try {
            const result = await deps.request(`/fnb/floor?shop_id=${shopId}${suffix}`);
            if (state.disposed || epoch !== state.requestEpoch || shopId !== state.shopId) return;
            if (result.changed !== false) {
                state.floor = result;
                state.floorRevision = Number(result.fnb_revision);
                deps.render({ type: 'floor', value: result });
            }
        } catch (error) {
            if (!state.disposed && epoch === state.requestEpoch && shopId === state.shopId) {
                deps.render({ type: 'floor-error', error, hasData: state.floor.areas.length > 0 });
            }
        } finally {
            if (!state.disposed && epoch === state.requestEpoch && shopId === state.shopId) {
                state.pollTimer = deps.setTimeoutFn(() => loadFloor(false), pollDelay());
            }
        }
    }

    async function selectShop(shopId) {
        deps.clearTimeoutFn(state.pollTimer);
        state.requestEpoch += 1;
        state.shopId = Number(shopId);
        state.floorRevision = null;
        state.floor = { areas: [] };
        state.session = null;
        state.recoverableDraft = null;
        return loadFloor(true);
    }

    return {
        selectShop, loadFloor,
        getState: () => structuredClone(state),
        seedSession: session => { state.session = structuredClone(session); },
        dispose: () => { state.disposed = true; deps.clearTimeoutFn(state.pollTimer); },
        createArea, updateArea, createTable, updateTable,
        openTable, addLine, updateLine, cancelLine, moveTable, mergeTable, cancelSession,
    };
}
```

Implement every returned mutation method in the same file. It must set one `pendingMutation` object containing endpoint/method/body/operation ID before the request, ignore a second click while pending, clear only on success or definitive non-retryable 4xx, and preserve it for timeout/network retry. On `FNB_SESSION_CHANGED`, replace `state.session` with `error.detail.snapshot`, save the user's attempted body in `recoverableDraft`, render `conflict`, and reject so UI can announce it. Setup mutations and `openTable` send current `state.floorRevision`; `openTable` also sends current table `state_version`; line/session operations send current session/line/table revisions from state, never revisions captured when the page first loaded. On `FNB_FLOOR_CHANGED`, force-reload the floor while keeping setup form values so the user can submit again explicitly.

The existing `apiCall` keeps `Error.code` but drops the rest of the structured detail. In `static/js/api.js`, after constructing the error, add `error.detail = (data && typeof data.detail === 'object') ? data.detail : null;` before throwing. Do not change redirect, token clearing or displayed message behavior; the controller consumes only `code`, numeric revisions and server snapshots, never renders the raw object.

- [ ] **Step 6: Implement DOM mounting and complete state inventory**

The browser-only mount supplies `apiCall`, real timeout functions, `document.hidden`, `sessionStorage` adapter and renderer. Render these explicit states:

| State | Required UI and recovery |
| --- | --- |
| Loading with no data | six inert skeleton table cards; status `Đang tải sơ đồ bàn` |
| No enabled shops | explain setup and link owner to `/seller?setup=fnb`; STAFF sees contact-owner text |
| No areas/tables | `Chưa có bàn`; owner CTA opens the setup dialog; STAFF sees contact-owner text |
| Empty table | text + icon `Trống`; click opens once |
| Serving table | text `Đang phục vụ`, elapsed time, subtotal and unsent quantity |
| Poll error with data | keep cards; compact `Chưa cập nhật được` + retry |
| Poll error without data | error panel explaining saved/no-saved data and retry |
| Empty session | `Bàn chưa gọi món`; product menu remains usable |
| Mutation pending | disable only affected controls; visible progress text |
| Draft add/update not yet acknowledged | label `Chưa đồng bộ` on that exact row; keep quantity/note locally and retry the same operation ID |
| Revision conflict | show latest session, keep attempted draft, CTA `Áp dụng lại` |
| Auth/permission loss | dispose controller, clear visible snapshot, redirect via existing `api.js` authority |
| Feature disabled while open | clear F&B data and return to `/pos` with translated message |

Use event delegation on `data-action`/`data-id`; never interpolate product/table/note strings without `escapeHtml`. Persist only the currently edited quantity/note draft in `sessionStorage`; authoritative server lines are never cached as offline truth.

Owner/STAFF MANAGER setup uses the same dialog, not a second admin page: list active/inactive areas and tables, create, rename/reorder and hide through Task 2 APIs. Hide is unavailable while a table is occupied and the server remains authoritative. CASHIER sees the floor but never sees `#fnbSetupOpen`; WAREHOUSE cannot enter the floor. Returning from a successful setup mutation forces `loadFloor(true)` so the manager immediately sees the new layout.

- [ ] **Step 7: Add responsive CSS and bilingual copy**

`static/css/fnb-r1a.css` must use the existing orange brand sparingly for primary action/focus, neutral floor cards, readable state chips, grid `repeat(auto-fill, minmax(150px, 1fr))`, and a desktop 60/40 floor/session split. At `max-width: 760px`, session becomes a bottom sheet with backdrop, safe-area padding, max height 92dvh, internal scroll and visible close button. At 320px and 200% zoom there must be no horizontal page overflow. Add `prefers-reduced-motion` and `:focus-visible` rules.

Create `static/js/locales/fnb.js` with identical Vietnamese/English key sets for every state/action/error above. Product/table business names are data, never translation keys.

- [ ] **Step 8: Add owner switch and POS entry without coupling controllers**

In the shop edit form, add an owner-only checkbox `#shopFnbEnabled` with explanation “Bật sơ đồ bàn và phục vụ tại bàn; POS bán tại quầy vẫn giữ nguyên.” Hide/disable it in create mode; in edit mode set it from `shop.fnb_enabled` and reset its disabled state. Add `const fnbSettingOperations = new Map();` beside `editShopId` so a response-lost retry is keyed by shop instead of the reused DOM input. Its change handler:

```javascript
async function updateFnbSetting(input) {
    if (!editShopId || input.disabled) return;
    const shopId = Number(editShopId);
    const previous = !input.checked;
    input.disabled = true;
    const operationId = fnbSettingOperations.get(shopId)
        || `fnb-setting-${crypto.randomUUID()}`;
    fnbSettingOperations.set(shopId, operationId);
    try {
        const result = await apiCall(`/fnb/shops/${shopId}/settings`, 'PATCH', {
            enabled: input.checked,
            expected_revision: Number(
                allShops.find(row => row.id === shopId)?.fnb_revision || 0
            ),
            operation_id: operationId,
        });
        const shop = allShops.find(row => row.id === shopId);
        if (shop) {
            shop.fnb_enabled = result.fnb_enabled;
            shop.fnb_revision = result.fnb_revision;
        }
        fnbSettingOperations.delete(shopId);
        if (Number(editShopId) === shopId) {
            showToast(t(result.fnb_enabled ? 'seller.shops.fnb_enabled' : 'seller.shops.fnb_disabled'));
        }
    } catch (error) {
        if (Number(editShopId) === shopId) input.checked = previous;
        if (Number(error.status) >= 400 && Number(error.status) < 500) {
            fnbSettingOperations.delete(shopId);
        }
        if (Number(editShopId) === shopId) showToast(error.message);
    } finally {
        if (Number(editShopId) === shopId) input.disabled = false;
    }
}
```

In POS, add hidden `#btnTableService`. Implement only:

```javascript
function updateFnbCapability() {
    const shop = allShops.find(item => Number(item.id) === Number(currentShopId));
    const button = document.getElementById('btnTableService');
    if (button) button.hidden = !Boolean(shop?.fnb_enabled);
}
```

Call it after shop load and shop change beside `updateTransferCapability()`. Button navigation only sets the already authoritative `currentShopId` and opens `/fnb`; it does not instantiate the F&B controller in `pos.js`.

- [ ] **Step 9: Run syntax, UI, API and retail focused gates**

Run:

```powershell
node --check static/js/fnb-r1a.js
node --check static/js/api.js
node --check static/js/pos.js
node --check static/js/seller.js
node tests/js/fnb-r1a.test.js
python -m pytest tests/test_fnb_r1a_ui.py tests/test_fnb_r1a_setup.py tests/test_fnb_r1a_sessions.py tests/test_pos_stabilization_r1_ui.py tests/test_seller_sidebar_ui.py tests/test_i18n.py tests/test_authorization.py tests/test_orders.py -q
python -m pytest tests/test_ai_provider_readiness.py tests/test_config.py -q
```

Expected: every command exits 0; provider/config tests confirm Gemini/TTS remain fail-closed.

- [ ] **Step 10: Run local multi-device browser acceptance before commit**

Start/reuse local server at `http://127.0.0.1:8100` with disposable demo data only. Verify:

1. Owner switch OFF hides POS entry; direct `/fnb` cannot load floor data. Switch ON reveals entry without changing retail POS.
2. Through `Thiết lập bàn`, create at least two areas/ten tables, rename one table and hide one unused table; floor sorts and labels states correctly, while an occupied table cannot be hidden.
3. Open the same shop in three tabs/devices: A opens table, B sees it within 2–3 seconds, C cannot open it again.
4. A and B add draft lines from the same revision: one succeeds, stale one gets latest snapshot and keeps its draft for explicit reapply; no silent overwrite.
5. Move to an empty table; merge an empty table; merge two draft sessions; all devices converge and line IDs/quantities remain unchanged.
6. Timeout/retry with the same operation ID never duplicates session/line/link; double-click controls remain single-flight.
7. Cancel all draft quantities then cancel session; every linked table returns to `Trống`.
8. CASHIER can serve; WAREHOUSE cannot read floor; second shop cannot see IDs/data.
9. Retail checkout, receipt, shift and history still work after switching between `/pos` and `/fnb`.
10. Desktop 1280×720, tablet, 390×844, 320px and 200% zoom have no horizontal overflow; 44px targets, 16px inputs, keyboard focus return, Escape close and reduced motion work; browser console is clean.

If QA finds a defect, write one red pytest/Node regression for that exact defect before changing production code, rerun the smallest test, then rerun Step 9. Do not widen scope to R1B/R1C.

- [ ] **Step 11: Audit final diff, update progress and commit through mandatory gate**

Run:

```powershell
git diff --check
git status --short
git diff -- static/fnb.html static/css/fnb-r1a.css static/js/fnb-r1a.js static/js/locales/fnb.js fselling/routers/pages.py static/pos.html static/js/api.js static/js/pos.js static/js/locales/pos.js static/seller.html static/js/seller.js static/js/locales/seller.js tests/js/fnb-r1a.test.js tests/test_fnb_r1a_ui.py
```

Update root `PROGRESS.md` with task commits, focused/full test evidence, browser journeys, accessibility results, known R1A limitation “chưa gửi Bếp/Bar, chưa trừ tồn, chưa thanh toán”, and provider/deploy boundaries. Then run:

```powershell
.\test-commit.ps1 "Add F&B table service R1A experience"
```

Expected: JS syntax and full pytest pass; commit contains only verified R1A UI/integration files. Confirm `git status --short` is empty and no runtime provider setting changed.

---

## R1A Completion Gate and Next Plans

R1A is complete only when all four task commits pass their mandatory full gate and the three-device browser journey passes. Then write a separate R1B implementation plan against the actual R1A models/services for Product station, Bếp/Bar tickets, stock allocations, cancellation/restock/waste and manager PIN. Write R1C only after R1B proves stock is deducted exactly once; R1C must create final `Order`/payment by transferring allocation provenance without calling retail `create_order()`'s stock deduction at `fselling/services/order_service.py:744-748`.
