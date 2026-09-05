# F&B Safety Hotfix R1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make F&B cash settlement fail closed until the cashier explicitly records cash received, and make in-progress item cancellation recover through the existing stock-decision and manager-approval dialog without leaving the session stuck or retrying a destructive action incorrectly.

**Architecture:** Keep the existing FastAPI endpoints, Pydantic request models, controller, operation IDs, revisions, allocation logic, and approval tokens. Enforce the financial invariant in `pay_check`, then add narrowly scoped vanilla-JavaScript helpers and controller events that reuse the current checkout and approval forms; do not introduce a state-machine framework or database migration.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy, Pydantic, vanilla HTML/CSS/JavaScript, i18next catalogs, pytest, Node `assert`.

**Spec:** `docs/superpowers/specs/2026-09-05-fnb-safety-hotfix-r1-design.md`

## Global Constraints

- Start execution in an isolated worktree created with `superpowers:using-git-worktrees`; the worktree base must contain spec commit `5cd3701` and this plan document.
- Preserve the user's existing uncommitted Seller changes; never stage `static/css/seller.css`, `static/js/locales/seller.js`, `static/js/seller.js`, `static/seller.html`, or `tests/test_seller_sidebar_ui.py` as part of R1.
- Do not add a database migration, endpoint, dependency, feature flag, generic mutation framework, new F&B status, role, or permission.
- Do not change Retail POS behavior, KDS `NEW`/`IN_PROGRESS`/`DONE`, table-close rules, or authentication/session behavior.
- Keep `FnbCheckPay.cash_tendered_vnd` optional at schema level; enforce its conditional cash requirement in `pay_check` after the final payable total is calculated.
- A blank/null cash tender is invalid even when the final total is zero; numeric `0` remains distinct and valid when it covers the total.
- `transfer` and `debt` behavior must remain unchanged; a cash-tender field on either method remains invalid.
- Preserve exact operation ID, revision, manager-token, allocation, audit, voucher, loyalty, and rollback semantics.
- A definitive 4xx result must clear pending state before rendering; an unknown network result must retain the exact payload and operation ID for retry.
- A cancellation conflict must never be converted into `updateLine` or automatically reissued.
- New user-facing copy must exist in both Vietnamese and English catalogs; PINs must never enter logs, local storage, or recoverable drafts.
- Use existing classes and files first. Add CSS only if the existing layout cannot keep the new control usable at 390×844 and 1024×768.
- Work test-first. Each task gets a red test, minimum implementation, focused green test, relevant regression test, and its own commit.
- Keep runtime providers disabled and use only an isolated local demo database for browser UAT; do not use real QR, banking, customer data, ngrok, secrets, or external services.

## File Structure

| File | Responsibility in R1 |
|---|---|
| `fselling/services/fnb_service.py` | Reject null cash tender after final-total calculation and before any financial mutation |
| `static/fnb.html` | Add the exact-cash control, helper/status semantics, and cache-busted F&B asset URLs |
| `static/js/fnb-r1a.js` | Parse explicit cash input; manage cash form state; classify actionable cancellation responses and safe conflicts |
| `static/js/locales/fnb.js` | Vietnamese and English cash/cancellation copy with identical key sets |
| `static/css/fnb-r1a.css` | Only the local cash-entry row and small-screen layout if existing CSS is insufficient |
| `tests/test_fnb_r1c_checkout.py` | API financial invariant, rollback, zero-total, promotion, method, and idempotency regressions |
| `tests/test_fnb_r1b_cancel.py` | Server cancellation decision, approval binding, conflict, allocation, and rollback regressions |
| `tests/js/fnb-r1a.test.js` | Pure cash parsing and controller pending/conflict/retry behavior |
| `tests/test_fnb_r1a_ui.py` | HTML wiring, bilingual keys, safe delegated events, asset versions, and Node-harness execution |
| `FNB_R1_UAT_REPORT.md` | Append the verified R1 safety exit evidence after automated and browser gates pass |

---

### Task 1: Enforce the Cash-Tender Invariant in the Service

**Files:**
- Modify: `tests/test_fnb_r1c_checkout.py:10-365`
- Modify: `fselling/services/fnb_service.py:1482-1603`

**Interfaces:**
- Consumes: `FnbCheckPay.cash_tendered_vnd: Optional[ExactVND]`, `fnb_error(status_code, code, message, **extra)`, and the existing `pay_check` transaction/rollback boundary.
- Produces: `400 FNB_CASH_TENDERED_REQUIRED` with integer `detail.required`; every successful cash order has a numeric `cash_tendered_amount` explicitly supplied by the client.

- [ ] **Step 1: Add a failing test for missing tender with no side effects**

Add this test near the first cash-checkout test in `tests/test_fnb_r1c_checkout.py`:

```python
def test_cash_checkout_requires_explicit_tender_without_side_effects(client, db):
    ctx, headers, session = sent_session(client, 1)
    primary = client.get(
        f"/api/fnb/sessions/{session['id']}/checks", headers=headers
    ).json()["checks"][0]
    product = db.get(models.Product, ctx["product"]["id"])
    before_stock = product.stock
    before_orders = db.query(models.Order).count()
    before_logs = db.query(models.FnbActionLog).count()
    before_check_revision = primary["revision"]
    before_session_revision = session["revision"]

    response = client.post(
        f"/api/fnb/checks/{primary['id']}/pay",
        json={
            "payment_method": "cash",
            "expected_revision": before_check_revision,
            "expected_session_revision": before_session_revision,
            "operation_id": op("cash-missing-tender"),
        },
        headers=headers,
    )

    assert response.status_code == 400, response.text
    assert response.json()["detail"] == {
        "code": "FNB_CASH_TENDERED_REQUIRED",
        "message": "Cần nhập số tiền khách đã đưa",
        "required": 100_000,
    }
    db.expire_all()
    assert db.query(models.Order).count() == before_orders
    assert db.query(models.FnbActionLog).count() == before_logs
    assert db.get(models.Product, product.id).stock == before_stock
    check = db.get(models.FnbServiceCheck, primary["id"])
    assert check.status == "OPEN"
    assert check.revision == before_check_revision
    assert db.get(models.FnbServiceSession, session["id"]).revision == before_session_revision
```

- [ ] **Step 2: Run the focused test and verify the unsafe baseline**

Run:

```powershell
.\.venv\Scripts\python.exe -B -m pytest -o addopts='' -q -p no:cacheprovider tests/test_fnb_r1c_checkout.py::test_cash_checkout_requires_explicit_tender_without_side_effects
```

Expected: FAIL because the response is currently `200` and a paid order is created.

- [ ] **Step 3: Add the fail-closed service guard**

In `pay_check`, preserve the non-cash validation and replace the implicit `tendered = total` fallback with this ordering immediately after `total` and payment-method prerequisites are calculated:

```python
        if (
            request.payment_method == order_service.PAYMENT_METHOD_CASH
            and request.cash_tendered_vnd is None
        ):
            raise fnb_error(
                400,
                "FNB_CASH_TENDERED_REQUIRED",
                "Cần nhập số tiền khách đã đưa",
                required=total,
            )
        if (
            request.payment_method != order_service.PAYMENT_METHOD_CASH
            and request.cash_tendered_vnd is not None
        ):
            raise fnb_error(
                400,
                "FNB_CASH_TENDERED_INVALID",
                "Chỉ nhập tiền khách đưa khi thu tiền mặt",
            )
        tendered = (
            int(request.cash_tendered_vnd)
            if request.payment_method == order_service.PAYMENT_METHOD_CASH
            else total
        )
```

Keep the existing `FNB_CASH_SHORT` check immediately after this block. Do not move the guard below cash-shift acquisition, order creation, loyalty entry creation, voucher consumption, allocation transfer, receipt creation, or `_finish`.

- [ ] **Step 4: Update every successful cash fixture to declare the tender explicitly**

In `tests/test_fnb_r1c_checkout.py`, update successful cash requests that currently omit the field:

```python
"cash_tendered_vnd": primary["total_vnd"],
```

For the split-check loop, use the current loop item:

```python
"cash_tendered_vnd": check["total_vnd"],
```

Do not add the field to transfer or debt payloads. Use this inventory command and inspect each hit before continuing:

```powershell
rg -n '"payment_method": "cash"|payment_method.*cash' tests -g 'test_fnb*.py'
```

- [ ] **Step 5: Add zero-total and promotion rollback coverage**

Add a zero-total case that first adjusts a one-item check to a 100,000 VND flat discount, then exercises null and numeric zero:

```python
def test_zero_total_cash_still_requires_explicit_numeric_zero(client, db):
    _, headers, session = sent_session(client, 1)
    primary = client.get(
        f"/api/fnb/sessions/{session['id']}/checks", headers=headers
    ).json()["checks"][0]
    adjusted = client.patch(
        f"/api/fnb/checks/{primary['id']}/adjustments",
        json={
            "discount_kind": "FLAT",
            "discount_value": primary["total_vnd"],
            "service_charge_kind": "NONE",
            "service_charge_value": 0,
            "expected_revision": primary["revision"],
            "expected_session_revision": session["revision"],
            "operation_id": op("zero-total-adjust"),
        },
        headers=headers,
    ).json()
    primary = adjusted["checks"][0]
    base = {
        "payment_method": "cash",
        "expected_revision": primary["revision"],
        "expected_session_revision": adjusted["session_revision"],
        "operation_id": op("zero-total-pay"),
    }

    missing = client.post(
        f"/api/fnb/checks/{primary['id']}/pay", json=base, headers=headers
    )
    assert missing.status_code == 400
    assert missing.json()["detail"]["required"] == 0

    paid = client.post(
        f"/api/fnb/checks/{primary['id']}/pay",
        json={**base, "cash_tendered_vnd": 0},
        headers=headers,
    )
    assert paid.status_code == 200, paid.text
    assert paid.json()["order"]["cash_tendered_vnd"] == 0
    assert paid.json()["order"]["cash_change_vnd"] == 0
```

In `test_fnb_checkout_reuses_voucher_and_loyalty_contract_once`, post a copy of the final payload without `cash_tendered_vnd` before the successful request:

```python
    missing_tender = {key: value for key, value in payload.items()
                      if key != "cash_tendered_vnd"}
    before_balance = loyalty_service.balance_for_customer(
        db, customer["id"], shop_id=ctx["shop_id"]
    )
    rejected = client.post(
        f"/api/fnb/checks/{primary['id']}/pay",
        json=missing_tender,
        headers=headers,
    )
    assert rejected.status_code == 400, rejected.text
    assert rejected.json()["detail"]["code"] == "FNB_CASH_TENDERED_REQUIRED"
    db.expire_all()
    assert db.get(models.Voucher, voucher.json()["id"]).usage_count == 0
    assert loyalty_service.balance_for_customer(
        db, customer["id"], shop_id=ctx["shop_id"]
    ) == before_balance
    assert db.query(models.Order).count() == 0
```

Retain the existing successful request with `cash_tendered_vnd: 200_000` immediately after these assertions. It proves the rejected attempt did not consume the voucher, points, or check.

- [ ] **Step 6: Run all checkout contract tests**

Run:

```powershell
.\.venv\Scripts\python.exe -B -m pytest -o addopts='' -q -p no:cacheprovider tests/test_fnb_r1c_checkout.py
```

Expected: all tests pass, including cash exact/overpayment, zero-total cash, voucher/loyalty rollback, transfer pending, debt, split checks, idempotency, allocations, and shift ledger.

- [ ] **Step 7: Verify no unintended schema or migration change and commit**

Run:

```powershell
git diff --check -- fselling/services/fnb_service.py tests/test_fnb_r1c_checkout.py
git diff --name-only
```

Expected: the task diff names only the service and checkout test, in addition to any pre-existing user-owned paths that remain untouched and unstaged.

Commit only Task 1 files:

```powershell
git add -- fselling/services/fnb_service.py tests/test_fnb_r1c_checkout.py
git commit -m "fix: require explicit F&B cash tender"
```

---

### Task 2: Make Cash Intent Explicit in the Checkout UI

**Files:**
- Modify: `static/fnb.html:150-165,235-240`
- Modify: `static/js/fnb-r1a.js:1-53,562-565,590-607,830-872,1023-1030,1092-1100,1188-1203,1230-1249`
- Modify: `static/js/locales/fnb.js:117-139,300-322`
- Modify: `static/css/fnb-r1a.css:188-225` only if required by the layout check
- Modify: `tests/js/fnb-r1a.test.js:1-5,363-402`
- Modify: `tests/test_fnb_r1a_ui.py:24-80,150-205`

**Interfaces:**
- Consumes: Task 1's `FNB_CASH_TENDERED_REQUIRED` contract and `activeCheck().total_vnd`.
- Produces: `cashTenderedForPayment(method: string, rawValue: unknown): object`, `cashExactAllowed(voucherCode: string, loyaltyPoints: unknown): boolean`, and cash payment payloads that always contain an explicit numeric tender.

- [ ] **Step 1: Add failing pure-JavaScript tests for cash parsing**

Extend the import in `tests/js/fnb-r1a.test.js`:

```javascript
const {
    createController, escapeHtml, partitionLines,
    adjustmentValueForApi, adjustmentValueForForm, groupMenuProducts,
    cashTenderedForPayment, cashExactAllowed,
} = require('../../static/js/fnb-r1a.js');
```

Add these assertions before the promise chain:

```javascript
assert.deepEqual(cashTenderedForPayment('transfer', ''), {});
assert.deepEqual(cashTenderedForPayment('debt', '50000'), {});
assert.deepEqual(cashTenderedForPayment('cash', ''), { error: 'required' });
assert.deepEqual(cashTenderedForPayment('cash', '   '), { error: 'required' });
assert.deepEqual(cashTenderedForPayment('cash', '0'), { cash_tendered_vnd: 0 });
assert.deepEqual(cashTenderedForPayment('cash', '120000'), {
    cash_tendered_vnd: 120000,
});
assert.equal(cashExactAllowed('', 0), true);
assert.equal(cashExactAllowed('GIAM10', 0), false);
assert.equal(cashExactAllowed('', 1), false);
```

- [ ] **Step 2: Run the Node harness and verify the helpers are missing**

Run:

```powershell
node tests/js/fnb-r1a.test.js
```

Expected: FAIL because `cashTenderedForPayment` and `cashExactAllowed` are not exported functions.

- [ ] **Step 3: Implement and export the two pure helpers**

Place these helpers alongside the existing pure formatting/grouping helpers near the top of `static/js/fnb-r1a.js`:

```javascript
function cashTenderedForPayment(method, rawValue) {
    if (method !== 'cash') return {};
    const normalized = String(rawValue ?? '').trim();
    if (normalized === '') return { error: 'required' };
    return { cash_tendered_vnd: Number(normalized) };
}

function cashExactAllowed(voucherCode, loyaltyPoints) {
    return String(voucherCode || '').trim() === ''
        && Number(loyaltyPoints || 0) === 0;
}
```

Add both names to the existing CommonJS `api` export. Do not move DOM behavior into the controller and do not add a new utility module.

- [ ] **Step 4: Add the exact-cash control and accessible helper markup**

Replace the single cash-tender label in `static/fnb.html` with:

```html
<div id="fnbCashTenderedField" class="fnb-cash-field">
    <label for="fnbCashTendered">
        <span data-i18n="fnb.checkout.cash_tendered">Tiền khách đưa</span>
    </label>
    <div class="fnb-cash-entry">
        <input id="fnbCashTendered" type="number" min="0" inputmode="numeric"
               aria-describedby="fnbCashTenderedHelp fnbCashTenderedError">
        <button id="fnbCashExact" type="button" class="fnb-secondary"
                data-i18n="fnb.checkout.cash_exact">Khách đưa đúng tổng bill</button>
    </div>
    <small id="fnbCashTenderedHelp" data-i18n="fnb.checkout.cash_help">Nhập số tiền thực nhận trước khi xác nhận.</small>
    <p id="fnbCashTenderedError" role="status" aria-live="polite"></p>
</div>
```

Update F&B asset query versions in the same HTML so deployed browsers fetch the changed locale and JavaScript. Use one R1 identifier consistently:

```html
<script src="/js/locales/fnb.js?v=20260905-safety-r1"></script>
<script src="/js/fnb-r1a.js?v=20260905-safety-r1"></script>
```

Only bump `/css/fnb-r1a.css` to `v=20260905-safety-r1` if this task changes that file.

- [ ] **Step 5: Add bilingual copy and preserve catalog parity**

Add these exact keys to both `resources.vi.translation` and `resources.en.translation` in `static/js/locales/fnb.js`:

```javascript
// Vietnamese
'fnb.checkout.cash_exact': 'Khách đưa đúng tổng bill',
'fnb.checkout.cash_help': 'Nhập số tiền thực nhận trước khi xác nhận.',
'fnb.checkout.cash_promotion_help': 'Đang dùng voucher hoặc điểm. Hãy nhập số tiền thực nhận sau ưu đãi.',
'fnb.checkout.cash_required': 'Cần nhập số tiền khách đã đưa.',
'fnb.checkout.confirm_cash': 'Xác nhận đã thu {{amount}}',

// English
'fnb.checkout.cash_exact': 'Guest gave the displayed total',
'fnb.checkout.cash_help': 'Enter the cash actually received before confirming.',
'fnb.checkout.cash_promotion_help': 'A voucher or points are being used. Enter the cash received after the promotion.',
'fnb.checkout.cash_required': 'Enter the cash received.',
'fnb.checkout.confirm_cash': 'Confirm {{amount}} received',
```

Keep the Vietnamese and English key sets identical; do not hard-code either language in `fnb-r1a.js`.

- [ ] **Step 6: Wire cash-state behavior into the existing mount function**

Add `fnbCashExact`, `fnbCashTenderedHelp`, and `fnbCashTenderedError` to the element registry. Add one local updater:

```javascript
function updateCashControls({ clearTender = false } = {}) {
    const method = paymentMethod();
    const cash = method === 'cash';
    const check = activeCheck();
    const editable = check?.status === 'OPEN'
        && !controller.getState().pendingMutation
        && navigator.onLine;
    const exactAllowed = cashExactAllowed(
        elements.fnbVoucherCode.value,
        elements.fnbLoyaltyPoints.value,
    );
    if (clearTender) elements.fnbCashTendered.value = '';
    elements.fnbCashTenderedField.hidden = !cash;
    elements.fnbCashExact.disabled = !editable || !cash || !exactAllowed;
    elements.fnbCashTenderedHelp.textContent = t(
        exactAllowed ? 'fnb.checkout.cash_help' : 'fnb.checkout.cash_promotion_help'
    );
    elements.fnbCashTenderedError.textContent = '';
    elements.fnbPayButton.textContent = cash && elements.fnbCashTendered.value !== ''
        ? t('fnb.checkout.confirm_cash', {
            amount: money(Number(elements.fnbCashTendered.value)),
        })
        : t('fnb.checkout.pay');
}
```

Wire it as follows:

- payment-method change: `updateCashControls({ clearTender: true })`;
- selected-check change: clear tender before `renderChecks` and then update controls;
- checkout open: clear tender after loading fresh checks;
- voucher/points input: call `updateCashControls()` so the exact button and helper update;
- cash input: clear the error and refresh the CTA;
- exact button: set `fnbCashTendered.value = String(activeCheck().total_vnd)` and refresh controls;
- checkout close: clear tender/error before returning focus.

Do not persist tender in local storage and do not carry it across selected bills.

- [ ] **Step 7: Make the submit handler fail locally on blank cash**

Replace the optional cash assignment in the submit handler with:

```javascript
const cashInput = cashTenderedForPayment(method, elements.fnbCashTendered.value);
if (cashInput.error === 'required') {
    elements.fnbCashTenderedError.textContent = t('fnb.checkout.cash_required');
    elements.fnbCashTendered.focus();
    return;
}
Object.assign(values, cashInput);
```

Keep customer/voucher/loyalty validation and `controller.payCheck` after this block. Never translate a server/network error into a PAID result.

- [ ] **Step 8: Add static UI contract assertions**

In `test_fnb_page_and_assets_are_wired`, add the new IDs to the existing tuple and assert accessibility/cache wiring:

```python
    for element_id in (
        "fnbCashTendered",
        "fnbCashExact",
        "fnbCashTenderedHelp",
        "fnbCashTenderedError",
    ):
        assert f'id="{element_id}"' in html
    assert 'aria-describedby="fnbCashTenderedHelp fnbCashTenderedError"' in html
    assert "/js/locales/fnb.js?v=20260905-safety-r1" in html
    assert "/js/fnb-r1a.js?v=20260905-safety-r1" in html
```

Extend the bilingual key subset in `test_owner_edit_switch_and_bilingual_contracts`:

```python
        "fnb.checkout.cash_exact",
        "fnb.checkout.cash_help",
        "fnb.checkout.cash_promotion_help",
        "fnb.checkout.cash_required",
        "fnb.checkout.confirm_cash",
```

- [ ] **Step 9: Run focused UI and syntax checks**

Run:

```powershell
node --check static/js/fnb-r1a.js
node --check static/js/locales/fnb.js
node tests/js/fnb-r1a.test.js
.\.venv\Scripts\python.exe -B -m pytest -o addopts='' -q -p no:cacheprovider tests/test_fnb_r1a_ui.py
```

Expected: JavaScript syntax passes, Node prints `fnb-r1a controller ok`, and the UI pytest file passes.

- [ ] **Step 10: Check the two required viewport widths**

Run the local app with an isolated demo database and providers disabled. Inspect the checkout at 390×844 and 1024×768. If the input/button wrap or overflow, add only these local rules:

```css
.fnb-cash-field { display: grid; gap: 5px; }
.fnb-cash-field[hidden] { display: none; }
.fnb-cash-entry { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 8px; }
#fnbCashTenderedError { min-height: 20px; margin: 0; color: #9a3412; }
@media (max-width: 560px) {
    .fnb-cash-entry { grid-template-columns: 1fr; }
}
```

If CSS changes, bump its query version and update the static assertion. Do not change global PWA positioning in R1.

- [ ] **Step 11: Commit the cash UI slice**

Run `git diff --check` on the task paths, then commit only files that actually changed:

```powershell
git add -- static/fnb.html static/js/fnb-r1a.js static/js/locales/fnb.js tests/js/fnb-r1a.test.js tests/test_fnb_r1a_ui.py
if ((git status --short -- static/css/fnb-r1a.css)) { git add -- static/css/fnb-r1a.css }
git commit -m "fix: require explicit cash intent in F&B checkout"
```

---

### Task 3: Make Cancellation Action Requirements First-Class Controller Results

**Files:**
- Modify: `tests/js/fnb-r1a.test.js:134-216,392-402`
- Modify: `static/js/fnb-r1a.js:218-335,429-436,562-565`

**Interfaces:**
- Consumes: existing `startMutation`, `clearPending`, `FNB_CANCELLATION_DECISION_REQUIRED`, `FNB_APPROVAL_REQUIRED`, `FNB_SESSION_CHANGED`, and `FNB_LINE_CHANGED`.
- Produces: controller render events `{type: 'cancel-action-required', value, error, attempt}` and `{type: 'cancel-conflict', value, error}`; cancellation errors never create a recoverable add/update draft.

- [ ] **Step 1: Add a failing controller test for action-required cleanup**

Add this function to `tests/js/fnb-r1a.test.js`:

```javascript
async function testCancelDecisionRequiredClearsPendingWithoutDraft() {
    const deps = makeDeps({
        request: async endpoint => {
            if (endpoint.startsWith('/fnb/floor')) return floor();
            const error = new Error('Cần chọn cách xử lý tồn');
            error.status = 400;
            error.code = 'FNB_CANCELLATION_DECISION_REQUIRED';
            error.detail = { code: error.code };
            throw error;
        },
    });
    const controller = createController(deps);
    await controller.selectShop(1);
    controller.seedSession(session());

    await assert.rejects(controller.cancelLine(40, 1));

    assert.equal(controller.getState().pendingMutation, null);
    assert.equal(controller.getState().recoverableDraft, null);
    assert.equal(deps.renders.at(-1).type, 'cancel-action-required');
    assert.equal(deps.renders.at(-1).attempt.line_id, 40);
}
```

Register it in the promise chain immediately after the existing definitive-failure test.

- [ ] **Step 2: Add a failing test that prevents cancel conflict from becoming an update draft**

```javascript
async function testCancelConflictRequiresFreshUserDecision() {
    const latest = { ...session(8), lines: [{
        ...session(8).lines[0], state_version: 10,
    }] };
    const deps = makeDeps({
        request: async endpoint => {
            if (endpoint.startsWith('/fnb/floor')) return floor();
            const error = new Error('Món vừa thay đổi');
            error.status = 409;
            error.code = 'FNB_LINE_CHANGED';
            error.detail = { code: error.code, snapshot: latest };
            throw error;
        },
    });
    const controller = createController(deps);
    await controller.selectShop(1);
    controller.seedSession(session(7));

    await assert.rejects(controller.cancelLine(40, 1, {
        resolution: 'WASTE', reason: 'Món đã chế biến',
    }));

    assert.deepEqual(controller.getState().session, latest);
    assert.equal(controller.getState().pendingMutation, null);
    assert.equal(controller.getState().recoverableDraft, null);
    assert.equal(deps.renders.at(-1).type, 'cancel-conflict');
    assert.equal(deps.renders.some(event => event.type === 'conflict'), false);
}
```

Register it after the action-required test.

- [ ] **Step 3: Run the two new tests through the Node harness**

Run:

```powershell
node tests/js/fnb-r1a.test.js
```

Expected: FAIL because cancellation currently emits generic `mutation-error`/`conflict` and preserves a `recoverableDraft`.

- [ ] **Step 4: Add narrow cancellation classifiers**

Inside `createController`, next to `isDefinitive4xx`, add:

```javascript
function errorCode(error) {
    return error?.code || error?.detail?.code || '';
}

function isCancelActionRequired(mutation, error) {
    return mutation.action === 'cancel-line' && [
        'FNB_CANCELLATION_DECISION_REQUIRED',
        'FNB_APPROVAL_REQUIRED',
    ].includes(errorCode(error));
}
```

Do not classify `FNB_APPROVAL_INVALID`, permission loss, rate limiting, or arbitrary 400 responses as action-required.

- [ ] **Step 5: Handle safe cancel conflict before the generic conflict branch**

At the top of the mutation catch, replace its current inline `const code = error?.code || error?.detail?.code` declaration with `const code = errorCode(error)`, then place this branch before the generic session/line conflict block. Reuse the same `code` variable in every later branch; do not redeclare it:

```javascript
const code = errorCode(error);
if (
    mutation.action === 'cancel-line'
    && (code === 'FNB_SESSION_CHANGED' || code === 'FNB_LINE_CHANGED')
    && error?.detail?.snapshot
) {
    state.session = error.detail.snapshot;
    state.recoverableDraft = null;
    clearPending();
    deps.render({ type: 'cancel-conflict', value: state.session, error });
    throw error;
}
```

The generic conflict behavior for `add-line` and `update-line` must remain unchanged and continue preserving their drafts.

- [ ] **Step 6: Handle actionable cancellation before generic mutation-error rendering**

Immediately after the cancel-conflict branch, add:

```javascript
if (isCancelActionRequired(mutation, error)) {
    const attempt = clone(mutation.attempt);
    state.recoverableDraft = null;
    clearPending();
    deps.render({
        type: 'cancel-action-required',
        value: state.session,
        error,
        attempt,
    });
    throw error;
}
```

Then let all remaining branches follow existing behavior. Keep network ambiguity pending and preserve exact retry payload/operation ID.

- [ ] **Step 7: Run the full controller harness and existing UI wrapper**

Run:

```powershell
node --check static/js/fnb-r1a.js
node tests/js/fnb-r1a.test.js
.\.venv\Scripts\python.exe -B -m pytest -o addopts='' -q -p no:cacheprovider tests/test_fnb_r1a_ui.py::test_fnb_controller_node_harness
```

Expected: all three commands pass; existing add/update conflict and single-flight retry tests remain green.

- [ ] **Step 8: Commit the controller slice**

```powershell
git diff --check -- static/js/fnb-r1a.js tests/js/fnb-r1a.test.js
git add -- static/js/fnb-r1a.js tests/js/fnb-r1a.test.js
git commit -m "fix: classify F&B cancellation recovery states"
```

---

### Task 4: Connect Cancellation Events to the Existing Approval Dialog

**Files:**
- Modify: `static/js/fnb-r1a.js:590-607,900-960,1117-1133,1276-1301,1319-1329`
- Modify: `static/js/locales/fnb.js:151-159,334-342`
- Modify: `tests/js/fnb-r1a.test.js:392-402`
- Modify: `tests/test_fnb_r1a_ui.py:24-80,180-245`
- Test: `tests/test_fnb_r1b_cancel.py:43-180`

**Interfaces:**
- Consumes: Task 3's `cancel-action-required` and `cancel-conflict` render events; existing `/fnb/manager-approvals` and `controller.cancelLine(lineId, quantity, details)`.
- Produces: one recoverable dialog flow for `resolution`, trimmed `reason`, manager credentials, and approval token; close/success/conflict always clear sensitive dialog state.

- [ ] **Step 1: Strengthen backend decision and conflict regression tests**

In `test_in_progress_cancel_requires_bound_one_use_manager_approval`, first issue a payload without decision fields and assert the exact first-stage response before the existing approval assertions:

```python
    decision_required = client.post(
        f"/api/fnb/sessions/{session['id']}/cancel-line",
        json={
            "line_id": line["id"],
            "quantity": 1,
            "expected_line_version": line["state_version"],
            "expected_revision": session["revision"],
            "operation_id": op("cancel-needs-decision"),
        },
        headers=auth(cashier_token),
    )
    assert decision_required.status_code == 400
    assert decision_required.json()["detail"]["code"] == (
        "FNB_CANCELLATION_DECISION_REQUIRED"
    )
    db.expire_all()
    unchanged = db.get(models.FnbSessionLine, line["id"])
    assert unchanged.sent_cancelled_quantity == 0
    assert db.get(models.Product, ctx["product"]["id"]).stock == 8
```

Add a stale-revision assertion after approval creation but before successful cancellation. Submit the approved payload with `expected_revision` decremented by one and verify `FNB_SESSION_CHANGED`, approval remains unused, line/ticket/allocation remain unchanged. Then submit the original valid approved payload and preserve the existing successful/idempotent assertions.

- [ ] **Step 2: Run the focused cancellation test**

Run:

```powershell
.\.venv\Scripts\python.exe -B -m pytest -o addopts='' -q -p no:cacheprovider tests/test_fnb_r1b_cancel.py::test_in_progress_cancel_requires_bound_one_use_manager_approval
```

Expected before frontend work: PASS if the server contract already satisfies these assertions. If the approval is consumed on stale conflict or inventory changes, stop and fix that server invariant with a red regression before proceeding; do not mask it in JavaScript.

- [ ] **Step 3: Add dialog-state reset helpers in the existing mount function**

Add these local functions near the other DOM helpers:

```javascript
function resetApprovalDialog() {
    elements.fnbApprovalPin.value = '';
    elements.fnbApprovalStatus.textContent = '';
    elements.fnbCancelReason.value = '';
    elements.fnbCancelResolution.value = 'WASTE';
    pendingCancelLineId = null;
}

function closeApprovalAfterConflict() {
    resetApprovalDialog();
    if (elements.fnbApprovalDialog.open) elements.fnbApprovalDialog.close();
}
```

PIN must always clear. Resolution/reason may survive a wrong credential attempt, but not success, close, session conflict, shop change, logout, or page disposal.

- [ ] **Step 4: Render actionable and conflict events without unsynced state**

Add two branches before generic `mutation-error` rendering:

```javascript
} else if (event.type === 'cancel-action-required') {
    renderSession(event.value, null);
    sessionStatus(t('fnb.cancel.action_required'));
} else if (event.type === 'cancel-conflict') {
    renderSession(event.value, null);
    closeApprovalAfterConflict();
    sessionStatus(t('fnb.cancel.changed'));
```

Neither branch calls `saveDraft`, shows the unsynced badge, or leaves session controls disabled.

- [ ] **Step 5: Open the existing dialog for both actionable codes**

Replace the current single-code catch on the cancel button with:

```javascript
controller.cancelLine(id, 1).catch(error => {
    const code = error?.code || error?.detail?.code;
    if (![
        'FNB_CANCELLATION_DECISION_REQUIRED',
        'FNB_APPROVAL_REQUIRED',
    ].includes(code)) return;
    resetApprovalDialog();
    pendingCancelLineId = id;
    elements.fnbApprovalDialog.showModal();
    elements.fnbCancelResolution.focus();
});
```

The dialog must open only after the controller has cleared pending and rendered the current session.

- [ ] **Step 6: Validate the dialog and clear sensitive state correctly**

At approval submit, trim the reason before creating an approval. If missing, do not call either endpoint:

```javascript
const reason = elements.fnbCancelReason.value.trim();
if (!reason) {
    elements.fnbApprovalStatus.textContent = t('fnb.cancel.reason_required');
    elements.fnbCancelReason.focus();
    return;
}
```

Use `reason` in `controller.cancelLine`. On success call `resetApprovalDialog()` before closing. In the catch:

```javascript
const code = error?.code || error?.detail?.code;
elements.fnbApprovalPin.value = '';
if (code === 'FNB_SESSION_CHANGED' || code === 'FNB_LINE_CHANGED') return;
elements.fnbApprovalStatus.textContent = error.message;
```

For `close-approval`, call `resetApprovalDialog()` before closing. Also reset on checkout/shop/session teardown paths that already clear controller state.

- [ ] **Step 7: Add exact bilingual recovery copy**

Add matching keys:

```javascript
// Vietnamese
'fnb.cancel.action_required': 'Chưa hủy — món vẫn đang làm. Chọn cách xử lý tồn kho và cần quản lý duyệt.',
'fnb.cancel.changed': 'Món vừa thay đổi; kiểm tra lại trước khi hủy.',
'fnb.cancel.reason_required': 'Nhập lý do hủy món.',

// English
'fnb.cancel.action_required': 'Not cancelled — the item is still in preparation. Choose the inventory outcome and get manager approval.',
'fnb.cancel.changed': 'The item just changed. Review it before cancelling again.',
'fnb.cancel.reason_required': 'Enter the cancellation reason.',
```

- [ ] **Step 8: Add static and Node assertions for the safe flow**

In `tests/test_fnb_r1a_ui.py`, add these source-contract assertions and extend the bilingual key subset with all three `fnb.cancel.*` keys:

```python
    assert "type: 'cancel-action-required'" in source
    assert "type: 'cancel-conflict'" in source
    assert "FNB_CANCELLATION_DECISION_REQUIRED" in source
    assert "FNB_APPROVAL_REQUIRED" in source
    assert "function resetApprovalDialog()" in source
```

In the Node harness, retain Task 3's controller assertions and add:

```javascript
assert.equal(
    deps.renders.some(event => event.type === 'mutation-error'),
    false,
);
```

to the action-required test.

- [ ] **Step 9: Run cancellation, controller, UI, and syntax gates**

Run:

```powershell
.\.venv\Scripts\python.exe -B -m pytest -o addopts='' -q -p no:cacheprovider tests/test_fnb_r1b_cancel.py tests/test_fnb_r1a_ui.py
node --check static/js/fnb-r1a.js
node --check static/js/locales/fnb.js
node tests/js/fnb-r1a.test.js
```

Expected: cancellation inventory/approval tests pass, UI catalog parity passes, JavaScript syntax passes, and Node prints its success marker.

- [ ] **Step 10: Commit the dialog/recovery slice**

```powershell
git diff --check -- static/js/fnb-r1a.js static/js/locales/fnb.js tests/js/fnb-r1a.test.js tests/test_fnb_r1a_ui.py tests/test_fnb_r1b_cancel.py
git add -- static/js/fnb-r1a.js static/js/locales/fnb.js tests/js/fnb-r1a.test.js tests/test_fnb_r1a_ui.py tests/test_fnb_r1b_cancel.py
git commit -m "fix: recover in-progress F&B cancellation"
```

---

### Task 5: Run the R1 Exit Gate and Record Verified UAT Evidence

**Files:**
- Modify: `FNB_R1_UAT_REPORT.md`
- Verify only: all R1 implementation and test files

**Interfaces:**
- Consumes: Tasks 1-4 commits and the complete approved spec.
- Produces: a reproducible automated/browser exit result and a UAT report that supersedes the earlier “no known P0/P1” statement for this scope.

- [ ] **Step 1: Run focused automated gates from a clean R1 worktree**

Run:

```powershell
node --check static/js/fnb-r1a.js
node --check static/js/locales/fnb.js
node tests/js/fnb-r1a.test.js
.\.venv\Scripts\python.exe -B -m pytest -o addopts='' -q -p no:cacheprovider tests/test_fnb_r1c_checkout.py tests/test_fnb_r1b_cancel.py tests/test_fnb_r1a_ui.py
```

Expected: every command exits `0`; no skipped failure is accepted.

- [ ] **Step 2: Run the broader F&B and shared-money regression set**

Run:

```powershell
.\.venv\Scripts\python.exe -B -m pytest -o addopts='' -q -p no:cacheprovider tests/test_fnb_r1a_sessions.py tests/test_fnb_r1b_send.py tests/test_fnb_r1c_checks.py tests/test_fnb_r1c_checkout.py tests/test_fnb_r1b_cancel.py tests/test_cashier_checkout.py tests/test_shifts.py tests/test_vouchers.py tests/test_loyalty_shop_policy.py tests/test_reconciliation.py tests/test_staff_roles.py tests/test_fnb_r1a_ui.py
```

Expected: all selected tests pass. Any failure blocks UAT and must receive a new focused red regression before a fix.

- [ ] **Step 3: Run the full repository test suite before the release claim**

Run:

```powershell
.\.venv\Scripts\python.exe -B -m pytest -o addopts='' -q -p no:cacheprovider
```

Expected: exit `0`. Record the exact passed/skipped/warning counts in the execution report; do not infer them from earlier runs.

- [ ] **Step 4: Start an isolated local UAT runtime**

Use a temporary database copied only from the approved demo fixture, migrate the copy to the current revision, bind Uvicorn to `127.0.0.1`, and set provider/payment runtime controls to safe local values:

```text
GEMINI_ENABLED=false
TTS_SERVER_ENABLED=false
QR_SALES_MODE=OFF
QR_WEBHOOK_MODE=OFF
OFFLINE_LEASE_ISSUANCE_ENABLED=false
```

Use a temporary log/upload directory and an ephemeral local secret. Do not use the repository/default database if its provenance is uncertain. Record the temporary paths and server PID so cleanup targets are exact.

- [ ] **Step 5: Execute the cash UAT matrix**

At 390×844, 1024×768, and at least 1366×768:

1. Open a table, add/send one demo item, open checkout, choose cash, leave tender blank, submit.
2. Confirm focus moves to the input, inline error appears, no success toast appears, and database order/check/shift counts remain unchanged.
3. Enter `0` for a positive bill; confirm `FNB_CASH_SHORT` and no side effects.
4. Use the exact-cash button on a bill without promotions; confirm the field receives the displayed total and CTA states the amount received.
5. Pay with exact cash; confirm PAID, tender and change `0` on the receipt/order.
6. Pay a second bill with overpayment; confirm server-returned change is correct.
7. Enter a voucher or points; confirm the exact-cash button disables and helper text changes.
8. Trigger missing/short tender with a promotion; confirm voucher usage and loyalty balance do not change.
9. Confirm transfer remains PENDING until bank confirmation and debt still requires a customer.

Inspect the database copy after each rejected case; UI messages alone are not financial evidence.

- [ ] **Step 6: Execute the cancellation UAT matrix**

At mobile server and fixed Bar/Kitchen views:

1. Cancel a sent but not-started item; confirm direct success and exact stock restoration.
2. Start another item at Bar/Kitchen, then cancel from the server view.
3. Confirm the session first shows “Chưa hủy”, all valid controls are usable, and the existing dialog opens.
4. Submit an empty reason; confirm neither approval nor cancel endpoint is called.
5. Submit a wrong PIN; confirm resolution/reason remain, PIN clears, item remains IN_PROGRESS.
6. Submit a valid manager credential with WASTE; confirm one approval, one cancellation, one waste allocation, no restock.
7. Repeat with RESTOCK; confirm exact stock restoration once.
8. Create a revision conflict from a second device before approving; confirm the first device loads the new snapshot, closes/clears the dialog, does not show unsynced, and does not call `updateLine` or auto-cancel.
9. Stop the local backend after sending a cancel request; confirm no success is shown and retry reuses the same operation ID.

Use only fake local orders, sessions, tickets, and credentials.

- [ ] **Step 7: Update the UAT report only from fresh evidence**

Change the report date/baseline and replace the stale blanket claim with a scoped R1 addendum. If Steps 1-6 all pass, append:

```markdown
## Safety Hotfix R1

- Cash checkout now rejects a blank tender before creating an order or changing the check, shift, voucher, loyalty balance, allocation, or receipt.
- Numeric zero remains explicit and succeeds only when it covers the final payable total.
- In-progress cancellation opens the existing stock-decision and manager-approval dialog without leaving the service session pending.
- Cancellation conflicts load the authoritative snapshot and require a fresh user decision; they are never replayed as line updates.
- Unknown network outcomes retain the original operation ID for exact retry and never display a false success state.
```

Under that section, record the exact command outputs, browser viewports, demo order/session IDs, database assertions, commit SHA, and any remaining P2/P3 observations. If any gate fails, set the report conclusion to `FAIL` and record the exact failed step; do not write the PASS text.

- [ ] **Step 8: Verify scope, secret hygiene, and working-tree ownership**

Run:

```powershell
git diff --check
git status --short
$r1Base = git rev-list --reverse 5cd3701..HEAD | Select-Object -First 1
git diff --name-only "$r1Base..HEAD"
git diff --name-only
git diff $r1Base -- . | rg -n "API_KEY|SECRET_KEY|PASSWORD=|TOKEN="
if ($LASTEXITCODE -eq 1) { Write-Output 'SECRET_SCAN_CLEAR'; exit 0 }
```

Expected:

- no diff-check errors;
- no secret values;
- no migration, role, auth, Retail, KDS-state, table-close, Seller-sidebar, or dependency files;
- implementation paths are limited to the File Structure table;
- temporary database/log/upload files are outside git and outside the repository.

- [ ] **Step 9: Stop only the recorded UAT server process and commit the evidence**

Resolve the recorded server PID and command line before stopping it. Stop only that exact local Uvicorn process; retain or remove temporary evidence according to the user's instruction, never with a broad recursive target.

Commit only the report:

```powershell
git add -- FNB_R1_UAT_REPORT.md
git commit -m "docs: record F&B safety hotfix R1 UAT"
```

- [ ] **Step 10: Prepare the review handoff**

The handoff must state:

- exact commits and changed files;
- focused, regression, full-suite, syntax, Node, and browser results;
- cash/tender/order/shift/voucher/loyalty evidence;
- cancellation/ticket/allocation/approval/revision evidence;
- unverified production-only conditions;
- confirmation that the user's pre-existing Seller changes were neither modified nor committed;
- recommendation to merge R1 before starting the detailed Plan 2 design.

Do not claim Plan 2 is ready until R1 has been merged and its UAT evidence reviewed.

## Plan Self-Review Map

| Spec requirement | Implemented by |
|---|---|
| Blank/null cash tender rejected after final-total calculation | Task 1 Steps 1-3 |
| Zero-total explicit numeric zero | Task 1 Step 5 |
| No financial, stock, voucher, loyalty, revision, or receipt side effects | Task 1 Steps 1 and 5; Task 5 Steps 1-5 |
| Transfer/debt compatibility and non-cash tender rejection | Task 1 Steps 4-6; Task 5 Step 5 |
| Exact-cash UI, CTA, focus, accessibility, bilingual copy | Task 2 Steps 1-10 |
| Tender cleared across bill/method/dialog changes | Task 2 Step 6 |
| Cancellation action-required is not unsynced | Task 3 Steps 1 and 4-6; Task 4 Steps 4-5 |
| Pending clears before render on definitive cancellation 4xx | Task 3 Steps 1 and 6 |
| Wrong PIN, close, success, and conflict clear the correct dialog state | Task 4 Steps 3-6 |
| Cancel conflict never replays as updateLine or auto-cancel | Task 3 Steps 2 and 5; Task 5 Step 6 |
| Unknown network outcome preserves exact operation ID | Existing controller invariant plus Task 3 Step 6 and Task 5 Step 6 |
| No migration, endpoint, dependency, status, role, or permission expansion | Global Constraints and Task 5 Step 8 |
| Three viewports and local-only UAT | Task 5 Steps 4-7 |
| Release, rollback, external-client and next-plan gates | Spec sections 6, 10, and 11; Task 5 Steps 7-10 |
