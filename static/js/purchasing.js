// Nhập hàng + công nợ nhà cung cấp.
// File này được nạp SAU seller.js nên dùng đúng các helper thật của trang:
// apiCall, escapeHtml, dinhDangNgayGio, dinhDangTienDoiSoat, showToast và t.
(function (global) {
    'use strict';

    const PURCHASING_UI_ROLES = Object.freeze(new Set(['SELLER', 'ADMIN']));
    const PURCHASING_PENDING_STORAGE_PREFIX = 'fselling.purchasing.pending.v1';
    const MAX_PURCHASE_QUANTITY = 1_000_000_000;
    const MAX_PURCHASE_VND = 9_000_000_000_000_000;
    const ALL_PURCHASE_PAYMENT_METHODS = Object.freeze([
        'CASH_SHIFT', 'TRANSFER', 'OUTSIDE'
    ]);
    const ADMIN_PURCHASE_PAYMENT_METHODS = Object.freeze([
        'TRANSFER', 'OUTSIDE'
    ]);
    const PENDING_OPERATION_CONFIG = Object.freeze({
        supplier_create: 'pendingSupplierCreate',
        receipt_create: 'pendingReceiptCreate',
        receipt_confirm: 'pendingReceiptConfirm',
        supplier_payment: 'pendingSupplierPayment'
    });

    function canUsePurchasing() {
        return PURCHASING_UI_ROLES.has(MY_ROLE);
    }

    function availablePaymentMethods() {
        return MY_ROLE === 'ADMIN'
            ? ADMIN_PURCHASE_PAYMENT_METHODS
            : ALL_PURCHASE_PAYMENT_METHODS;
    }

    const state = {
        subTab: 'receipts',
        suppliers: [],
        supplierShopId: null,
        supplierRequestId: 0,
        receipts: [],
        receiptShopId: null,
        receiptRequestId: 0,
        editingSupplierId: null,
        editingReceiptId: null,
        receiptLines: [],
        nextLineKey: 1,
        currentReceiptDetail: null,
        currentSupplierDetail: null,
        paymentSupplier: null,
        confirmReceipt: null,
        supplierBusy: false,
        receiptBusy: false,
        confirmBusy: false,
        paymentBusy: false,
        pendingSupplierCreate: null,
        pendingReceiptCreate: null,
        pendingReceiptConfirm: null,
        pendingSupplierPayment: null
    };

    const $ = id => document.getElementById(id);

    function applyPaymentMethodRoleVisibility() {
        const hideCash = MY_ROLE === 'ADMIN';
        document.querySelectorAll('[data-owner-cash]').forEach(option => {
            option.hidden = hideCash;
            option.disabled = hideCash;
            option.setAttribute('aria-hidden', hideCash ? 'true' : 'false');
        });
    }

    function selectedShopId() {
        const value = Number(typeof currentShopId === 'undefined' ? null : currentShopId);
        return Number.isInteger(value) && value > 0 ? value : null;
    }

    function selectedGeneration() {
        return Number(typeof currentShopGeneration === 'undefined' ? 0 : currentShopGeneration);
    }

    function stillCurrent(shopId, generation) {
        return selectedShopId() === Number(shopId)
            && selectedGeneration() === Number(generation);
    }

    function todayLocal() {
        const now = new Date();
        const month = String(now.getMonth() + 1).padStart(2, '0');
        const day = String(now.getDate()).padStart(2, '0');
        return `${now.getFullYear()}-${month}-${day}`;
    }

    function dateOnly(value) {
        const raw = String(value || '');
        const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(raw);
        if (!match) return raw || '—';
        const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
        return new Intl.DateTimeFormat(
            global.FSellingI18n?.getIntlLocale?.() || 'vi-VN',
            { day: '2-digit', month: '2-digit', year: 'numeric' }
        ).format(date);
    }

    function integerFromInput(raw) {
        const parsed = _soTienTuChuoi(raw);
        return Number.isFinite(parsed) && Number.isInteger(parsed)
            && Number.isSafeInteger(parsed) ? parsed : NaN;
    }

    function safePurchaseLineTotal(quantity, unitCost) {
        if (
            !Number.isSafeInteger(quantity)
            || !Number.isSafeInteger(unitCost)
            || quantity <= 0
            || quantity > MAX_PURCHASE_QUANTITY
            || unitCost < 0
            || unitCost > MAX_PURCHASE_VND
            || (unitCost > 0 && quantity > Math.floor(MAX_PURCHASE_VND / unitCost))
        ) return NaN;
        return quantity * unitCost;
    }

    function operationId(prefix) {
        if (global.crypto && typeof global.crypto.randomUUID === 'function') {
            return global.crypto.randomUUID();
        }
        return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 12)}`;
    }

    function exactCopy(value) {
        return JSON.parse(JSON.stringify(value));
    }

    function currentActorUsername() {
        // Giữ nguyên chính xác chuỗi auth.js đã lưu; trim ở đây có thể nhập
        // nhằng hai username khác nhau nếu dữ liệu cũ từng cho phép khoảng trắng.
        return localStorage.getItem('username') || '';
    }

    function pendingStorageKey(kind, username = currentActorUsername()) {
        return `${PURCHASING_PENDING_STORAGE_PREFIX}:${username}:${kind}`;
    }

    function validPendingOperation(kind, pending) {
        if (!pending || typeof pending !== 'object') return false;
        if (!Number.isInteger(Number(pending.shopId)) || Number(pending.shopId) <= 0) {
            return false;
        }
        if (!pending.payload || typeof pending.payload !== 'object') return false;
        if (!String(pending.payload.operation_id || '').trim()) return false;
        if (kind === 'receipt_confirm') {
            return Number.isInteger(Number(pending.receiptId))
                && Number(pending.receiptId) > 0
                && pending.receipt && typeof pending.receipt === 'object';
        }
        if (kind === 'supplier_payment') {
            return Number.isInteger(Number(pending.supplierId))
                && Number(pending.supplierId) > 0
                && pending.supplier && typeof pending.supplier === 'object';
        }
        return true;
    }

    function readPendingOperation(kind) {
        const username = currentActorUsername();
        const stateField = PENDING_OPERATION_CONFIG[kind];
        if (!username || !stateField) return null;
        try {
            const raw = sessionStorage.getItem(pendingStorageKey(kind, username));
            if (!raw) return null;
            const saved = JSON.parse(raw);
            if (
                saved?.version !== 1
                || saved.username !== username
                || saved.kind !== kind
                || Number(saved.shop_id) !== Number(saved.pending?.shopId)
                || saved.pending?.actor_username !== username
                || !validPendingOperation(kind, saved.pending)
            ) {
                sessionStorage.removeItem(pendingStorageKey(kind, username));
                return null;
            }
            return exactCopy(saved.pending);
        } catch (error) {
            console.warn('Không đọc được thao tác nhập hàng đang chờ:', error);
            return null;
        }
    }

    function persistPendingOperation(kind, pending) {
        const username = currentActorUsername();
        const stateField = PENDING_OPERATION_CONFIG[kind];
        if (!username || !stateField || !validPendingOperation(kind, pending)) {
            showToast(t('seller.purchasing.storage_unavailable'));
            return null;
        }
        if (pending.actor_username && pending.actor_username !== username) {
            // BFCache/script đăng nhập chen ngang có thể thay localStorage trong
            // khi document cũ còn sống. Không chuyển op của actor cũ sang key
            // actor mới và cũng không gửi nó bằng token của actor mới.
            showToast(t('seller.purchasing.pending_actor_changed'));
            return null;
        }
        const exactPending = {
            ...exactCopy(pending),
            actor_username: username
        };
        const saved = {
            version: 1,
            username,
            role: MY_ROLE,
            kind,
            shop_id: Number(exactPending.shopId),
            pending: exactPending,
            saved_at: new Date().toISOString()
        };
        try {
            // Phải ghi xong trước khi request rời browser. Nếu response mất rồi
            // người dùng F5, bản này giữ nguyên entity id, payload và operation_id.
            sessionStorage.setItem(
                pendingStorageKey(kind, username),
                JSON.stringify(saved)
            );
            state[stateField] = exactPending;
            return exactPending;
        } catch (error) {
            // Không gửi một thao tác tiền/kho nếu chưa tạo được lưới an toàn F5.
            console.warn('Không lưu được thao tác nhập hàng đang chờ:', error);
            showToast(t('seller.purchasing.storage_unavailable'));
            return null;
        }
    }

    function clearPendingOperation(kind, pending = null) {
        // Request có thể đang bay đúng lúc một script đăng nhập tài khoản khác.
        // Kết quả rõ phải xóa key của actor đã BẮT ĐẦU request, không phải key
        // suy ra từ localStorage vừa bị thay giữa chừng.
        const username = String(pending?.actor_username || currentActorUsername());
        const stateField = PENDING_OPERATION_CONFIG[kind];
        if (stateField) state[stateField] = null;
        if (!username || !stateField) return;
        try {
            sessionStorage.removeItem(pendingStorageKey(kind, username));
        } catch (error) {
            console.warn('Không xóa được thao tác nhập hàng đã xử lý:', error);
        }
    }

    function restorePendingOperationsFromSession() {
        let pendingShopId = null;
        Object.entries(PENDING_OPERATION_CONFIG).forEach(([kind, stateField]) => {
            const pending = readPendingOperation(kind);
            if (!pending) return;
            // Từ phiên bản này UI chỉ cho một thao tác chưa rõ kết quả tại một
            // thời điểm. Nếu gặp dữ liệu cũ, chỉ khôi phục các thao tác cùng shop.
            if (pendingShopId !== null && Number(pending.shopId) !== pendingShopId) {
                return;
            }
            pendingShopId = Number(pending.shopId);
            state[stateField] = pending;
        });
        return pendingShopId;
    }

    function unknownOutcome(error) {
        // Không có HTTP status nghĩa là request có thể đã tới server nhưng phản
        // hồi thất lạc. Lỗi parse ở HTTP 2xx cũng là kết quả chưa chắc chắn.
        // 5xx/proxy timeout cũng có thể tới SAU lúc transaction đã commit. Chỉ
        // 4xx là kết quả chắc chắn để bỏ mã cũ và cho người dùng sửa payload.
        return !Number.isInteger(error?.status)
            || error.status < 400
            || error.status >= 500;
    }

    function setGlobalShopLocked(locked) {
        const selector = $('shopChungSelect');
        if (selector) selector.disabled = Boolean(locked);
    }

    function hasUnknownOperation() {
        return Boolean(
            state.pendingSupplierCreate
            || state.pendingReceiptCreate
            || state.pendingReceiptConfirm
            || state.pendingSupplierPayment
        );
    }

    function syncGlobalShopLock() {
        setGlobalShopLocked(
            hasUnknownOperation()
            || state.supplierBusy
            || state.receiptBusy
            || state.confirmBusy
            || state.paymentBusy
        );
    }

    // seller.js đã gọi init() nhưng đang chờ `/shops`; script này chạy trọn
    // trước khi promise đó tiếp tục. Đặt shop đã lưu ngay lúc này để init chọn
    // đúng cửa hàng của thao tác cũ, không lấy currentShopId của lần xem gần nhất.
    const restoredPendingShopId = restorePendingOperationsFromSession();
    if (restoredPendingShopId && canUsePurchasing()) {
        currentShopId = restoredPendingShopId;
        localStorage.setItem('currentShopId', String(restoredPendingShopId));
        syncGlobalShopLock();
        // F5 từ trang Seller thường quay về tab Thống kê. Kéo người dùng thẳng
        // về Nhập hàng để hộp cảnh báo/Thử lại không bị giấu ở tab khác.
        switchTab('purchasing', $('tabPurchasing'));
        restorePendingUi(false);
    }

    function supplierBalance(supplier) {
        return Number(supplier?.payable_balance || 0);
    }

    function supplierOverdue(supplier) {
        return Number(supplier?.overdue_amount || 0);
    }

    function receiptItems(receipt) {
        return Array.isArray(receipt?.items) ? receipt.items : [];
    }

    function receiptStatus(receipt) {
        return String(receipt?.status || 'DRAFT').toUpperCase();
    }

    function receiptCode(receipt) {
        return receipt?.code || receipt?.receipt_number || `PN-${receipt?.id || '?'}`;
    }

    function statusBadge(status) {
        const normalized = String(status || '').toUpperCase();
        const config = {
            DRAFT: ['seller.purchasing.status_draft', 'is-draft'],
            POSTED: ['seller.purchasing.status_confirmed', 'is-confirmed'],
            CONFIRMED: ['seller.purchasing.status_confirmed', 'is-confirmed'],
            CANCELLED: ['seller.purchasing.status_cancelled', 'is-cancelled']
        }[normalized] || ['seller.purchasing.status_draft', 'is-draft'];
        return `<span class="purchase-status ${config[1]}">${escapeHtml(t(config[0]))}</span>`;
    }

    function supplierStatusBadge(active) {
        const key = active === false ? 'seller.status.inactive' : 'seller.status.active';
        const css = active === false ? 'is-inactive' : 'is-active';
        return `<span class="purchase-status ${css}">${escapeHtml(t(key))}</span>`;
    }

    function setActionLabel(selector, key) {
        const node = document.querySelector(selector);
        if (node) {
            // i18n chạy bất đồng bộ sau khi trang vừa F5. Chỉ đổi textContent
            // thì lượt dịch kế tiếp sẽ đọc data-i18n cũ và đổi "Thử lại" về
            // "Xác nhận", dù payload vẫn đang bị khóa chờ retry. Cập nhật cả
            // khóa dịch để nhãn và hành vi luôn nói cùng một việc.
            node.setAttribute('data-i18n', key);
            node.textContent = t(key);
        }
    }

    function restoreSupplierCreateUi(pending) {
        const payload = pending.payload;
        clearSupplierForm();
        state.editingSupplierId = null;
        $('supplierName').value = payload.name || '';
        $('supplierPhone').value = payload.phone || '';
        $('supplierTaxCode').value = payload.tax_code || '';
        $('supplierAddress').value = payload.address || '';
        $('supplierNote').value = payload.note || '';
        $('supplierOpeningDebt').value = String(payload.opening_balance ?? 0);
        $('supplierOpeningDate').value = payload.opening_date || '';
        $('supplierOpeningDueDate').value = payload.opening_due_date || '';
        $('supplierOpeningNote').value = payload.opening_note || '';
        $('supplierOpeningSection').style.display = 'block';
        $('supplierFormTitle').textContent = t('seller.purchasing.new_supplier');
        setActionLabel('[data-supplier-action-label="save"]', 'common.retry');
        $('supplierFormModal').style.display = 'flex';
        lockSupplierForm(true, true);
    }

    function restoreReceiptCreateUi(pending) {
        const payload = pending.payload;
        const savedLines = Array.isArray(pending.lines) ? pending.lines : [];
        state.editingReceiptId = null;
        state.receiptLines = (Array.isArray(payload.items) ? payload.items : [])
            .map((item, index) => {
                const saved = savedLines[index] || {};
                return {
                    line_key: index + 1,
                    product_id: Number(item.product_id),
                    product_name: saved.product_name || '',
                    product_code: saved.product_code || '',
                    track_batches: saved.track_batches ?? Boolean(item.expiry_date),
                    quantity: Number(item.quantity),
                    unit_cost: Number(item.unit_cost),
                    expiry_date: item.expiry_date || ''
                };
            });
        state.nextLineKey = state.receiptLines.length + 1;
        $('purchaseSupplierSelect').value = String(payload.supplier_id || '');
        $('purchaseInvoiceNumber').value = payload.supplier_invoice_number || '';
        $('purchaseReceivedDate').value = payload.received_date || '';
        $('purchaseDueDate').value = payload.due_date || '';
        $('purchaseReceiptNote').value = payload.note || '';
        $('purchaseReceiptFormTitle').textContent = t('seller.purchasing.new_receipt');
        setActionLabel('[data-purchase-action-label="save-draft"]', 'common.retry');
        $('purchaseReceiptEditor').style.display = 'block';
        renderReceiptLines();
        lockReceiptEditor(true, true);
        $('purchaseReceiptEditor').scrollIntoView({ behavior: 'auto', block: 'start' });
    }

    function restoreReceiptConfirmUi(pending) {
        const payload = pending.payload;
        state.confirmReceipt = exactCopy(pending.receipt);
        renderConfirmSummary(state.confirmReceipt);
        $('purchaseConfirmPaid').value = String(payload.paid_amount ?? 0);
        $('purchaseConfirmMethod').value = payload.method || '';
        $('purchaseConfirmReference').value = payload.reference || '';
        $('purchaseConfirmNote').value = payload.note || '';
        updatePurchaseConfirmPreview();
        updatePurchaseConfirmPaymentRules();
        setActionLabel('[data-purchase-action-label="confirm"]', 'common.retry');
        $('purchaseConfirmModal').style.display = 'flex';
        lockConfirmModal(true, true);
    }

    function restoreSupplierPaymentUi(pending) {
        const payload = pending.payload;
        state.paymentSupplier = exactCopy(pending.supplier);
        $('supplierPaymentTitle').textContent = t('seller.purchasing.pay_supplier_name', {
            name: state.paymentSupplier.name || ''
        });
        $('supplierPaymentDescription').textContent = t('seller.purchasing.payment_desc', {
            balance: dinhDangTienDoiSoat(supplierBalance(state.paymentSupplier))
        });
        $('supplierPaymentAmount').value = String(payload.amount);
        $('supplierPaymentMethod').value = payload.method || '';
        $('supplierPaymentReference').value = payload.reference || '';
        $('supplierPaymentNote').value = payload.note || '';
        updateSupplierPaymentPreview();
        updateSupplierPaymentRules();
        setActionLabel('[data-purchase-action-label="pay"]', 'common.retry');
        $('supplierPaymentModal').style.display = 'flex';
        lockPaymentModal(true, true);
    }

    function restorePendingUi(notify = false) {
        const shopId = selectedShopId();
        const pendingEntries = [
            ['supplier_create', state.pendingSupplierCreate, restoreSupplierCreateUi],
            ['receipt_create', state.pendingReceiptCreate, restoreReceiptCreateUi],
            ['receipt_confirm', state.pendingReceiptConfirm, restoreReceiptConfirmUi],
            ['supplier_payment', state.pendingSupplierPayment, restoreSupplierPaymentUi]
        ];
        const matchingShopEntry = pendingEntries.find(([, pending]) => (
            pending && Number(pending.shopId) === Number(shopId)
        ));
        // Nếu quyền với shop vừa bị thu hồi, seller.js sẽ rơi về shop đầu tiên.
        // Vẫn phải hiện thao tác cũ để người dùng retry và nhận 403 rõ ràng;
        // giấu nó đi sẽ khiến họ tưởng không còn gì đang chờ.
        const entry = matchingShopEntry || pendingEntries.find(([, pending]) => pending);
        syncGlobalShopLock();
        if (!entry) return false;
        entry[2](entry[1]);
        if (notify) showToast(t('seller.purchasing.retry_before_close'));
        return true;
    }

    function hasOtherPendingOperation(kind) {
        return Object.entries(PENDING_OPERATION_CONFIG).some(([otherKind, stateField]) => (
            otherKind !== kind && Boolean(state[stateField])
        ));
    }

    function blockForOtherPendingOperation(kind) {
        if (!hasOtherPendingOperation(kind)) return false;
        restorePendingUi(true);
        return true;
    }

    function resetForShopChange() {
        state.supplierRequestId += 1;
        state.receiptRequestId += 1;
        state.suppliers = [];
        state.receipts = [];
        state.supplierShopId = null;
        state.receiptShopId = null;
        if (!hasUnknownOperation()) {
            closePurchaseReceiptForm(true);
            closeSupplierForm(true);
            closePurchaseConfirmModal(true);
            closeSupplierPaymentModal(true);
            closeSupplierHistory();
            closePurchaseReceiptDetail();
        }
        renderSuppliers();
        renderReceipts();
        updateSummaryCards();
    }

    async function loadSuppliers() {
        const shopId = selectedShopId();
        if (!shopId || !canUsePurchasing()) return;
        const generation = selectedGeneration();
        const requestId = ++state.supplierRequestId;
        try {
            // Màn quản lý phải thấy cả NCC đã ngừng để có thể xem lịch sử hoặc
            // kích hoạt lại. Ô chọn trên phiếu phía dưới vẫn chỉ lấy NCC active.
            const response = await apiCall(`/suppliers/${shopId}?include_inactive=true`);
            if (
                requestId !== state.supplierRequestId
                || !stillCurrent(shopId, generation)
            ) return;
            state.suppliers = Array.isArray(response?.suppliers)
                ? response.suppliers
                : (Array.isArray(response) ? response : []);
            state.supplierShopId = shopId;
            renderSuppliers();
            fillSupplierSelect();
            updateSummaryCards();
        } catch (error) {
            if (requestId === state.supplierRequestId && stillCurrent(shopId, generation)) {
                showToast(error.message);
            }
        }
    }

    async function loadPurchaseReceipts() {
        const shopId = selectedShopId();
        if (!shopId || !canUsePurchasing()) return;
        const generation = selectedGeneration();
        const requestId = ++state.receiptRequestId;
        try {
            const response = await apiCall(`/purchase-receipts/${shopId}`);
            if (
                requestId !== state.receiptRequestId
                || !stillCurrent(shopId, generation)
            ) return;
            state.receipts = Array.isArray(response?.receipts)
                ? response.receipts
                : (Array.isArray(response) ? response : []);
            state.receiptShopId = shopId;
            renderReceipts();
            updateSummaryCards();
        } catch (error) {
            if (requestId === state.receiptRequestId && stillCurrent(shopId, generation)) {
                showToast(error.message);
            }
        }
    }

    function load() {
        if (!canUsePurchasing() || !selectedShopId()) return;
        restorePendingUi(false);
        loadSuppliers();
        loadPurchaseReceipts();
        if (!cacheThuocShop(currentProductsShopId, selectedShopId())) loadProducts();
    }

    function switchPurchasingSubTab(tab) {
        if (hasUnknownOperation()) {
            restorePendingUi(true);
            return;
        }
        state.subTab = tab === 'suppliers' ? 'suppliers' : 'receipts';
        $('purchaseSubTabReceipts')?.classList.toggle('active', state.subTab === 'receipts');
        $('purchaseSubTabSuppliers')?.classList.toggle('active', state.subTab === 'suppliers');
        if ($('purchaseReceiptsSection')) {
            $('purchaseReceiptsSection').style.display = state.subTab === 'receipts' ? 'block' : 'none';
        }
        if ($('purchaseSuppliersSection')) {
            $('purchaseSuppliersSection').style.display = state.subTab === 'suppliers' ? 'block' : 'none';
        }
        if (state.subTab === 'suppliers') loadSuppliers();
        else loadPurchaseReceipts();
    }

    function updateSummaryCards() {
        const total = state.suppliers.reduce((sum, supplier) => sum + supplierBalance(supplier), 0);
        const overdue = state.suppliers.reduce((sum, supplier) => sum + supplierOverdue(supplier), 0);
        const drafts = state.receipts.filter(receipt => receiptStatus(receipt) === 'DRAFT').length;
        if ($('purchaseTotalPayable')) $('purchaseTotalPayable').textContent = dinhDangTienDoiSoat(total);
        if ($('purchaseOverduePayable')) $('purchaseOverduePayable').textContent = dinhDangTienDoiSoat(overdue);
        if ($('purchaseDraftCount')) $('purchaseDraftCount').textContent = dinhDangSoSeller(drafts);
    }

    function renderSuppliers() {
        const body = $('purchaseSuppliersList');
        const empty = $('purchaseSuppliersEmpty');
        if (!body || !empty) return;
        body.innerHTML = '';
        const current = state.supplierShopId === selectedShopId() ? state.suppliers : [];
        empty.style.display = current.length ? 'none' : 'block';
        current.forEach(supplier => {
            const id = Number(supplier.id);
            if (!Number.isInteger(id)) return;
            const balance = supplierBalance(supplier);
            const overdue = supplierOverdue(supplier);
            const contact = [supplier.phone, supplier.tax_code]
                .filter(Boolean)
                .map(value => escapeHtml(value))
                .join('<br>') || '—';
            const payButton = balance > 0
                ? `<button class="btn-outline" type="button" onclick="openSupplierPaymentModal(${id})" title="${escapeHtml(t('seller.purchasing.pay_supplier'))}" aria-label="${escapeHtml(t('seller.purchasing.pay_supplier'))}"><i class="ph ph-money"></i></button>`
                : '';
            const toggleKey = supplier.is_active === false
                ? 'seller.purchasing.activate_supplier'
                : 'seller.purchasing.deactivate_supplier';
            body.insertAdjacentHTML('beforeend', `<tr>
                <td><strong>${escapeHtml(supplier.name || '')}</strong>${supplier.address ? `<br><small>${escapeHtml(supplier.address)}</small>` : ''}</td>
                <td>${contact}</td>
                <td class="${balance > 0 ? 'purchase-debt-positive' : ''}">${escapeHtml(dinhDangTienDoiSoat(balance))}</td>
                <td class="${overdue > 0 ? 'purchase-debt-overdue' : ''}">${escapeHtml(dinhDangTienDoiSoat(overdue))}</td>
                <td>${supplierStatusBadge(supplier.is_active)}</td>
                <td><div class="purchase-table-actions">
                    <button class="btn-outline" type="button" onclick="openSupplierHistory(${id})" title="${escapeHtml(t('seller.purchasing.history'))}" aria-label="${escapeHtml(t('seller.purchasing.history'))}"><i class="ph ph-clock-counter-clockwise"></i></button>
                    ${payButton}
                    <button class="btn-outline" type="button" onclick="openSupplierForm(${id})" title="${escapeHtml(t('common.edit'))}" aria-label="${escapeHtml(t('common.edit'))}"><i class="ph ph-pencil"></i></button>
                    <button class="btn-outline" type="button" onclick="toggleSupplierStatus(${id})" title="${escapeHtml(t(toggleKey))}" aria-label="${escapeHtml(t(toggleKey))}"><i class="ph ph-power"></i></button>
                    <button class="btn-outline" type="button" onclick="deleteSupplier(${id})" title="${escapeHtml(t('common.delete'))}" aria-label="${escapeHtml(t('common.delete'))}" style="color:#B91C1C;"><i class="ph ph-trash"></i></button>
                </div></td>
            </tr>`);
        });
    }

    function renderReceipts() {
        const body = $('purchaseReceiptsList');
        const empty = $('purchaseReceiptsEmpty');
        if (!body || !empty) return;
        body.innerHTML = '';
        const current = state.receiptShopId === selectedShopId() ? state.receipts : [];
        empty.style.display = current.length ? 'none' : 'block';
        current.forEach(receipt => {
            const id = Number(receipt.id);
            if (!Number.isInteger(id)) return;
            const status = receiptStatus(receipt);
            const total = Number(receipt.total_amount || 0);
            const paid = Number(receipt.paid_amount || 0);
            const remaining = Number(receipt.remaining_amount ?? Math.max(0, total - paid));
            const draftActions = status === 'DRAFT'
                ? `<button class="btn-outline" type="button" onclick="editPurchaseReceipt(${id})" title="${escapeHtml(t('common.edit'))}" aria-label="${escapeHtml(t('common.edit'))}"><i class="ph ph-pencil"></i></button>
                   <button type="button" onclick="openPurchaseConfirmModal(${id})" title="${escapeHtml(t('seller.purchasing.confirm_submit'))}" aria-label="${escapeHtml(t('seller.purchasing.confirm_submit'))}"><i class="ph ph-check-circle"></i></button>
                   <button class="btn-outline" type="button" onclick="deletePurchaseReceipt(${id})" title="${escapeHtml(t('common.delete'))}" aria-label="${escapeHtml(t('common.delete'))}" style="color:#B91C1C;"><i class="ph ph-trash"></i></button>`
                : '';
            body.insertAdjacentHTML('beforeend', `<tr>
                <td><strong>${escapeHtml(receiptCode(receipt))}</strong>${receipt.supplier_invoice_number ? `<br><small>${escapeHtml(t('seller.purchasing.invoice_short', { number: receipt.supplier_invoice_number }))}</small>` : ''}</td>
                <td>${escapeHtml(receipt.supplier_name || '')}</td>
                <td>${escapeHtml(dateOnly(receipt.received_date || receipt.created_at))}</td>
                <td>${escapeHtml(dinhDangTienDoiSoat(total))}</td>
                <td>${escapeHtml(dinhDangTienDoiSoat(paid))}</td>
                <td class="${remaining > 0 ? 'purchase-debt-positive' : ''}">${escapeHtml(dinhDangTienDoiSoat(remaining))}</td>
                <td>${statusBadge(status)}</td>
                <td><div class="purchase-table-actions">
                    <button class="btn-outline" type="button" onclick="openPurchaseReceiptDetail(${id})" title="${escapeHtml(t('seller.actions.view_detail'))}" aria-label="${escapeHtml(t('seller.actions.view_detail'))}"><i class="ph ph-eye"></i></button>
                    ${draftActions}
                </div></td>
            </tr>`);
        });
    }

    function fillSupplierSelect() {
        const select = $('purchaseSupplierSelect');
        if (!select) return;
        const previous = select.value;
        const options = state.suppliers
            .filter(supplier => supplier.is_active !== false || String(supplier.id) === previous)
            .map(supplier => `<option value="${Number(supplier.id)}">${escapeHtml(supplier.name || '')}</option>`)
            .join('');
        select.innerHTML = `<option value="">${escapeHtml(t('seller.purchasing.choose_supplier'))}</option>${options}`;
        const pendingSupplierId = state.pendingReceiptCreate?.payload?.supplier_id;
        const valueToRestore = pendingSupplierId && Number(state.pendingReceiptCreate?.shopId) === selectedShopId()
            ? String(pendingSupplierId)
            : previous;
        if ([...select.options].some(option => option.value === valueToRestore)) {
            select.value = valueToRestore;
        }
    }

    function clearSupplierForm() {
        ['supplierName', 'supplierPhone', 'supplierTaxCode', 'supplierAddress',
            'supplierNote', 'supplierOpeningNote'].forEach(id => {
            if ($(id)) $(id).value = '';
        });
        if ($('supplierOpeningDebt')) $('supplierOpeningDebt').value = '0';
        if ($('supplierOpeningDate')) $('supplierOpeningDate').value = todayLocal();
        if ($('supplierOpeningDueDate')) $('supplierOpeningDueDate').value = '';
    }

    function lockSupplierForm(locked, retry = false) {
        ['supplierName', 'supplierPhone', 'supplierTaxCode', 'supplierAddress',
            'supplierNote', 'supplierOpeningDebt', 'supplierOpeningDate',
            'supplierOpeningDueDate', 'supplierOpeningNote'].forEach(id => {
            if ($(id)) $(id).disabled = Boolean(locked);
        });
        const save = $('supplierSaveButton');
        if (save) save.disabled = Boolean(locked && !retry);
        document.querySelectorAll('#supplierFormModal .purchase-modal-actions .btn-outline')
            .forEach(button => { button.disabled = Boolean(retry); });
        if ($('supplierCreateRetryNotice')) {
            $('supplierCreateRetryNotice').style.display = retry ? 'block' : 'none';
        }
    }

    function openSupplierForm(id = null) {
        if (!canUsePurchasing()) return showToast(t('seller.purchasing.owner_only'));
        if (blockForOtherPendingOperation('supplier_create')) return;
        if (state.pendingSupplierCreate) {
            $('supplierFormModal').style.display = 'flex';
            lockSupplierForm(true, true);
            return;
        }
        clearSupplierForm();
        // `Number(null)` và `Number('')` đều bằng 0. Nếu đổi thẳng như trước,
        // nút "Thêm nhà cung cấp" (gọi không truyền id) bị hiểu nhầm là đang
        // sửa NCC số 0 rồi dừng ở thông báo Đang tải.
        const parsedId = id === null || id === undefined || id === ''
            ? NaN
            : Number(id);
        state.editingSupplierId = Number.isInteger(parsedId) && parsedId > 0
            ? parsedId
            : null;
        const supplier = state.editingSupplierId === null
            ? null
            : state.suppliers.find(item => Number(item.id) === state.editingSupplierId);
        if (state.editingSupplierId !== null && !supplier) {
            showToast(t('common.loading'));
            return;
        }
        if (supplier) {
            $('supplierName').value = supplier.name || '';
            $('supplierPhone').value = supplier.phone || '';
            $('supplierTaxCode').value = supplier.tax_code || '';
            $('supplierAddress').value = supplier.address || '';
            $('supplierNote').value = supplier.note || '';
        }
        $('supplierOpeningSection').style.display = supplier ? 'none' : 'block';
        $('supplierFormTitle').textContent = t(
            supplier ? 'seller.purchasing.edit_supplier' : 'seller.purchasing.new_supplier'
        );
        setActionLabel(
            '[data-supplier-action-label="save"]',
            supplier ? 'common.update' : 'common.save'
        );
        lockSupplierForm(false);
        $('supplierFormModal').style.display = 'flex';
        setTimeout(() => $('supplierName')?.focus(), 0);
    }

    function closeSupplierForm(force = false) {
        if (!force && state.pendingSupplierCreate) {
            showToast(t('seller.purchasing.retry_before_close'));
            return;
        }
        if ($('supplierFormModal')) $('supplierFormModal').style.display = 'none';
        if (!state.pendingSupplierCreate) state.editingSupplierId = null;
    }

    function supplierIdentityPayload() {
        const name = String($('supplierName')?.value || '').trim();
        if (!name) {
            showToast(t('seller.purchasing.supplier_name_required_error'));
            return null;
        }
        return {
            name,
            phone: String($('supplierPhone')?.value || '').trim() || null,
            tax_code: String($('supplierTaxCode')?.value || '').trim() || null,
            address: String($('supplierAddress')?.value || '').trim() || null,
            note: String($('supplierNote')?.value || '').trim() || null
        };
    }

    function newSupplierPayload() {
        const identity = supplierIdentityPayload();
        if (!identity) return null;
        const opening = integerFromInput($('supplierOpeningDebt')?.value || '0');
        if (!Number.isInteger(opening) || opening < 0) {
            showToast(t('seller.purchasing.opening_debt_invalid'));
            return null;
        }
        if (opening > MAX_PURCHASE_VND) {
            showToast(t('seller.purchasing.money_limit', {
                limit: dinhDangTienDoiSoat(MAX_PURCHASE_VND)
            }));
            return null;
        }
        const openingDate = String($('supplierOpeningDate')?.value || '').trim();
        const dueDate = String($('supplierOpeningDueDate')?.value || '').trim();
        if (opening > 0 && !/^\d{4}-\d{2}-\d{2}$/.test(openingDate)) {
            showToast(t('seller.purchasing.opening_date_required'));
            return null;
        }
        // Nợ đầu kỳ có thể đã quá hạn trước ngày cửa hàng bắt đầu nhập dữ liệu
        // vào F-Selling. Ô type="date" và server vẫn kiểm ngày hợp lệ; ở đây
        // không được tự suy ra hạn thanh toán phải sau ngày ghi nhận.
        return {
            ...identity,
            opening_balance: opening,
            opening_date: opening > 0 ? openingDate : null,
            opening_due_date: opening > 0 && dueDate ? dueDate : null,
            opening_note: opening > 0
                ? (String($('supplierOpeningNote')?.value || '').trim() || null)
                : null,
            operation_id: operationId('supplier')
        };
    }

    async function sendNewSupplier(pending) {
        // Persist trước apiCall: F5 ở bất kỳ thời điểm nào sau dòng này vẫn
        // phục hồi đúng opening_balance và operation_id ban đầu.
        pending = persistPendingOperation('supplier_create', pending);
        if (!pending) return;
        state.supplierBusy = true;
        syncGlobalShopLock();
        lockSupplierForm(true);
        try {
            await apiCall(`/suppliers/${pending.shopId}`, 'POST', pending.payload);
            clearPendingOperation('supplier_create', pending);
            syncGlobalShopLock();
            closeSupplierForm(true);
            showToast(t('seller.purchasing.supplier_created'));
            await loadSuppliers();
        } catch (error) {
            if (unknownOutcome(error)) {
                state.pendingSupplierCreate = pending;
                syncGlobalShopLock();
                lockSupplierForm(true, true);
                setActionLabel('[data-supplier-action-label="save"]', 'common.retry');
                showToast(t('seller.purchasing.supplier_retry_notice'));
            } else {
                clearPendingOperation('supplier_create', pending);
                syncGlobalShopLock();
                lockSupplierForm(false);
                showToast(error.message);
            }
        } finally {
            state.supplierBusy = false;
            syncGlobalShopLock();
            if (!state.pendingSupplierCreate) lockSupplierForm(false);
        }
    }

    async function saveSupplier() {
        if (state.supplierBusy) return;
        if (state.pendingSupplierCreate) {
            return sendNewSupplier(state.pendingSupplierCreate);
        }
        const shopId = selectedShopId();
        if (!shopId) return;
        if (state.editingSupplierId === null) {
            const payload = newSupplierPayload();
            if (!payload) return;
            const pending = { shopId, payload: exactCopy(payload) };
            return sendNewSupplier(pending);
        }
        const payload = supplierIdentityPayload();
        if (!payload) return;
        const supplierId = state.editingSupplierId;
        state.supplierBusy = true;
        syncGlobalShopLock();
        lockSupplierForm(true);
        try {
            await apiCall(`/suppliers/member/${supplierId}`, 'PUT', payload);
            closeSupplierForm(true);
            showToast(t('seller.purchasing.supplier_updated'));
            await loadSuppliers();
        } catch (error) {
            showToast(error.message);
        } finally {
            state.supplierBusy = false;
            syncGlobalShopLock();
            lockSupplierForm(false);
        }
    }

    function toggleSupplierStatus(id) {
        const supplier = state.suppliers.find(item => Number(item.id) === Number(id));
        if (!supplier) return;
        const nextActive = supplier.is_active === false;
        showCustomConfirm(
            t(nextActive
                ? 'seller.purchasing.activate_supplier'
                : 'seller.purchasing.deactivate_supplier'),
            t(nextActive
                ? 'seller.purchasing.activate_supplier_confirm'
                : 'seller.purchasing.deactivate_supplier_confirm', { name: supplier.name }),
            async () => {
                try {
                    await apiCall(`/suppliers/member/${id}/status`, 'PUT', { is_active: nextActive });
                    showToast(t('seller.purchasing.supplier_status_updated'));
                    loadSuppliers();
                } catch (error) {
                    showToast(error.message);
                }
            },
            t(nextActive ? 'seller.purchasing.activate' : 'seller.purchasing.deactivate')
        );
    }

    function deleteSupplier(id) {
        const supplier = state.suppliers.find(item => Number(item.id) === Number(id));
        if (!supplier) return;
        showCustomConfirm(
            t('seller.purchasing.delete_supplier_title'),
            t('seller.purchasing.delete_supplier_confirm', { name: supplier.name }),
            async () => {
                try {
                    const response = await apiCall(`/suppliers/member/${id}`, 'DELETE');
                    showToast(t(
                        response?.msg === 'Deactivated'
                            ? 'seller.purchasing.supplier_deactivated_history'
                            : 'seller.purchasing.supplier_deleted'
                    ));
                    loadSuppliers();
                } catch (error) {
                    showToast(error.message);
                }
            },
            t('common.delete')
        );
    }

    function renderSupplierHistory(detail) {
        const supplier = detail?.supplier || detail || {};
        const payables = Array.isArray(detail?.payables) ? detail.payables : [];
        const payments = Array.isArray(detail?.payments) ? detail.payments : [];
        $('supplierHistoryTitle').textContent = t('seller.purchasing.history_for', {
            name: supplier.name || ''
        });
        $('supplierHistorySummary').textContent = t('seller.purchasing.history_balance', {
            balance: dinhDangTienDoiSoat(supplierBalance(supplier)),
            overdue: dinhDangTienDoiSoat(supplierOverdue(supplier))
        });
        const payableRows = payables.map(entry => `<tr>
            <td>${escapeHtml(dateOnly(entry.entry_date || entry.created_at))}</td>
            <td>${escapeHtml(entry.label || entry.source_label || (entry.receipt_id ? receiptCode({ id: entry.receipt_id }) : t('seller.purchasing.opening_debt_short')))}</td>
            <td>${escapeHtml(dinhDangTienDoiSoat(entry.amount || 0))}</td>
            <td class="${Number(entry.remaining_amount || 0) > 0 ? 'purchase-debt-positive' : ''}">${escapeHtml(dinhDangTienDoiSoat(entry.remaining_amount || 0))}</td>
            <td class="${entry.is_overdue ? 'purchase-debt-overdue' : ''}">${escapeHtml(entry.due_date ? dateOnly(entry.due_date) : '—')}</td>
        </tr>`).join('');
        const paymentRows = payments.map(payment => `<tr>
            <td>${escapeHtml(dinhDangNgayGio(payment.created_at || payment.paid_at))}</td>
            <td>${escapeHtml(dinhDangTienDoiSoat(payment.amount || 0))}</td>
            <td>${escapeHtml(t(`seller.purchasing.method_${String(payment.method || '').toLowerCase()}`, { defaultValue: payment.method || '—' }))}</td>
            <td>${escapeHtml(payment.reference || '—')}</td>
            <td>${escapeHtml(payment.note || '—')}</td>
        </tr>`).join('');
        $('supplierHistoryContent').innerHTML = `
            <h4>${escapeHtml(t('seller.purchasing.payables_title'))}</h4>
            <div class="table-responsive"><table class="db-table"><thead><tr>
                <th>${escapeHtml(t('seller.table.date'))}</th><th>${escapeHtml(t('seller.purchasing.source'))}</th>
                <th>${escapeHtml(t('seller.table.total'))}</th><th>${escapeHtml(t('seller.purchasing.remaining'))}</th>
                <th>${escapeHtml(t('seller.purchasing.due_date_short'))}</th>
            </tr></thead><tbody>${payableRows || `<tr><td colspan="5">${escapeHtml(t('common.no_data'))}</td></tr>`}</tbody></table></div>
            <h4 style="margin-top:1.25rem;">${escapeHtml(t('seller.purchasing.payments_title'))}</h4>
            <div class="table-responsive"><table class="db-table"><thead><tr>
                <th>${escapeHtml(t('seller.table.date'))}</th><th>${escapeHtml(t('seller.purchasing.payment_amount'))}</th>
                <th>${escapeHtml(t('seller.purchasing.payment_source'))}</th><th>${escapeHtml(t('seller.purchasing.payment_reference'))}</th>
                <th>${escapeHtml(t('seller.fields.note'))}</th>
            </tr></thead><tbody>${paymentRows || `<tr><td colspan="5">${escapeHtml(t('common.no_data'))}</td></tr>`}</tbody></table></div>`;
    }

    async function openSupplierHistory(id) {
        const shopId = selectedShopId();
        const generation = selectedGeneration();
        if (!shopId) return;
        try {
            const detail = await apiCall(`/suppliers/member/${id}`);
            if (!stillCurrent(shopId, generation)) return;
            state.currentSupplierDetail = detail;
            renderSupplierHistory(detail);
            $('supplierHistoryModal').style.display = 'flex';
        } catch (error) {
            showToast(error.message);
        }
    }

    function closeSupplierHistory() {
        if ($('supplierHistoryModal')) $('supplierHistoryModal').style.display = 'none';
        state.currentSupplierDetail = null;
    }

    function productOptions() {
        if (!cacheThuocShop(currentProductsShopId, selectedShopId())) return [];
        return currentProducts.filter(product => product.is_active !== false);
    }

    function filterPurchaseProductOptions() {
        const select = $('purchaseProductSelect');
        if (!select) return;
        const query = String($('purchaseProductSearch')?.value || '').trim().toLocaleLowerCase('vi');
        const previous = select.value;
        const products = productOptions().filter(product => {
            if (!query) return true;
            return [product.name, product.code, product.barcode]
                .filter(Boolean)
                .some(value => String(value).toLocaleLowerCase('vi').includes(query));
        });
        select.innerHTML = `<option value="">${escapeHtml(t('seller.purchasing.choose_product'))}</option>`
            + products.map(product => `<option value="${Number(product.id)}">${escapeHtml(product.name)} · ${escapeHtml(product.code || '—')}</option>`).join('');
        if ([...select.options].some(option => option.value === previous)) select.value = previous;
    }

    function clearReceiptEditor() {
        state.editingReceiptId = null;
        state.receiptLines = [];
        state.nextLineKey = 1;
        if ($('purchaseSupplierSelect')) $('purchaseSupplierSelect').value = '';
        if ($('purchaseInvoiceNumber')) $('purchaseInvoiceNumber').value = '';
        if ($('purchaseReceivedDate')) $('purchaseReceivedDate').value = todayLocal();
        if ($('purchaseDueDate')) $('purchaseDueDate').value = '';
        if ($('purchaseReceiptNote')) $('purchaseReceiptNote').value = '';
        if ($('purchaseProductSearch')) $('purchaseProductSearch').value = '';
        renderReceiptLines();
        filterPurchaseProductOptions();
    }

    function openPurchaseReceiptForm() {
        if (!canUsePurchasing()) return showToast(t('seller.purchasing.owner_only'));
        if (blockForOtherPendingOperation('receipt_create')) return;
        if (state.pendingReceiptCreate) {
            $('purchaseReceiptEditor').style.display = 'block';
            lockReceiptEditor(true, true);
            return;
        }
        if (!state.suppliers.some(supplier => supplier.is_active !== false)) {
            showToast(t('seller.purchasing.create_supplier_first'));
            switchPurchasingSubTab('suppliers');
            openSupplierForm();
            return;
        }
        clearReceiptEditor();
        fillSupplierSelect();
        $('purchaseReceiptFormTitle').textContent = t('seller.purchasing.new_receipt');
        setActionLabel('[data-purchase-action-label="save-draft"]', 'seller.purchasing.save_draft');
        $('purchaseReceiptRetryNotice').style.display = 'none';
        lockReceiptEditor(false);
        $('purchaseReceiptEditor').style.display = 'block';
        $('purchaseReceiptEditor').scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    function closePurchaseReceiptForm(force = false) {
        if (!force && state.pendingReceiptCreate) {
            showToast(t('seller.purchasing.retry_before_close'));
            return;
        }
        if ($('purchaseReceiptEditor')) $('purchaseReceiptEditor').style.display = 'none';
        if (!state.pendingReceiptCreate) clearReceiptEditor();
    }

    function lockReceiptEditor(locked, retry = false) {
        ['purchaseSupplierSelect', 'purchaseInvoiceNumber', 'purchaseReceivedDate',
            'purchaseDueDate', 'purchaseReceiptNote', 'purchaseProductSearch',
            'purchaseProductSelect'].forEach(id => {
            if ($(id)) $(id).disabled = Boolean(locked);
        });
        document.querySelectorAll('#purchaseReceiptEditor .purchase-line-picker button, #purchaseReceiptLines input, #purchaseReceiptLines button')
            .forEach(element => { element.disabled = Boolean(locked); });
        const save = $('purchaseSaveDraftButton');
        const cancel = $('purchaseCancelEditButton');
        if (save) save.disabled = Boolean(locked && !retry);
        if (cancel) cancel.disabled = Boolean(retry);
        if ($('purchaseReceiptRetryNotice')) {
            $('purchaseReceiptRetryNotice').style.display = retry ? 'block' : 'none';
        }
    }

    function addPurchaseReceiptLine() {
        if (state.pendingReceiptCreate) return;
        if (!cacheThuocShop(currentProductsShopId, selectedShopId())) {
            showToast(t('common.loading'));
            return;
        }
        const productId = Number($('purchaseProductSelect')?.value);
        const product = currentProducts.find(item => Number(item.id) === productId);
        if (!product) return showToast(t('seller.purchasing.choose_product_error'));
        // Hàng theo lô được phép lặp sản phẩm: một chuyến giao có thể có hai
        // hạn sử dụng khác nhau. Hàng thường chỉ cần một dòng rồi sửa số lượng.
        if (
            !product.track_batches
            && state.receiptLines.some(line => Number(line.product_id) === productId)
        ) {
            showToast(t('seller.purchasing.product_already_added'));
            return;
        }
        state.receiptLines.push({
            line_key: state.nextLineKey++,
            product_id: productId,
            product_name: product.name,
            product_code: product.code,
            track_batches: Boolean(product.track_batches),
            quantity: 1,
            unit_cost: '',
            expiry_date: ''
        });
        renderReceiptLines();
    }

    function updatePurchaseReceiptLine(lineKey, field, rawValue) {
        if (state.pendingReceiptCreate) return;
        const line = state.receiptLines.find(item => Number(item.line_key) === Number(lineKey));
        if (!line || !['quantity', 'unit_cost', 'expiry_date'].includes(field)) return;
        line[field] = rawValue;
        updateReceiptTotal();
    }

    function removePurchaseReceiptLine(lineKey) {
        if (state.pendingReceiptCreate) return;
        state.receiptLines = state.receiptLines.filter(
            line => Number(line.line_key) !== Number(lineKey)
        );
        renderReceiptLines();
    }

    function receiptTotalFromLines() {
        let total = 0;
        for (const line of state.receiptLines) {
            const quantity = Number(line.quantity);
            const unitCost = integerFromInput(line.unit_cost);
            const lineTotal = safePurchaseLineTotal(quantity, unitCost);
            if (!Number.isSafeInteger(lineTotal) || lineTotal > MAX_PURCHASE_VND - total) {
                return NaN;
            }
            total += lineTotal;
        }
        return total;
    }

    function updateReceiptTotal() {
        if ($('purchaseReceiptTotal')) {
            const receiptTotal = receiptTotalFromLines();
            $('purchaseReceiptTotal').textContent = Number.isSafeInteger(receiptTotal)
                ? dinhDangTienDoiSoat(receiptTotal)
                : '—';
        }
        state.receiptLines.forEach(line => {
            const cell = $(`purchaseLineTotal_${line.line_key}`);
            if (!cell) return;
            const quantity = Number(line.quantity);
            const unitCost = integerFromInput(line.unit_cost);
            const total = safePurchaseLineTotal(quantity, unitCost);
            cell.textContent = Number.isSafeInteger(total)
                ? dinhDangTienDoiSoat(total)
                : '—';
        });
    }

    function renderReceiptLines() {
        const body = $('purchaseReceiptLines');
        const empty = $('purchaseNoLines');
        if (!body || !empty) return;
        body.innerHTML = '';
        empty.style.display = state.receiptLines.length ? 'none' : 'block';
        state.receiptLines.forEach(line => {
            const productId = Number(line.product_id);
            const lineKey = Number(line.line_key);
            if (!Number.isInteger(productId)) return;
            const expiry = line.track_batches
                ? `<input type="date" value="${escapeHtml(line.expiry_date || '')}" onchange="updatePurchaseReceiptLine(${lineKey}, 'expiry_date', this.value)">`
                : `<span title="${escapeHtml(t('seller.purchasing.no_batch_expiry'))}">—</span>`;
            body.insertAdjacentHTML('beforeend', `<tr>
                <td><strong>${escapeHtml(line.product_name || '')}</strong><br><small>${escapeHtml(line.product_code || '—')}</small>${line.track_batches ? `<br><small>${escapeHtml(t('seller.purchasing.batch_required'))}</small>` : ''}</td>
                <td><input type="number" inputmode="numeric" min="1" max="${MAX_PURCHASE_QUANTITY}" step="1" value="${escapeHtml(line.quantity)}" oninput="updatePurchaseReceiptLine(${lineKey}, 'quantity', this.value)"></td>
                <td><input type="text" inputmode="numeric" autocomplete="off" value="${escapeHtml(line.unit_cost)}" placeholder="0" oninput="updatePurchaseReceiptLine(${lineKey}, 'unit_cost', this.value)"></td>
                <td>${expiry}</td>
                <td id="purchaseLineTotal_${lineKey}">0 ₫</td>
                <td><button class="btn-outline" type="button" onclick="removePurchaseReceiptLine(${lineKey})" title="${escapeHtml(t('common.delete'))}" aria-label="${escapeHtml(t('common.delete'))}" style="color:#B91C1C;"><i class="ph ph-trash"></i></button></td>
            </tr>`);
        });
        updateReceiptTotal();
        if (state.pendingReceiptCreate) lockReceiptEditor(true, true);
    }

    function buildReceiptPayload(includeOperationId) {
        const supplierId = Number($('purchaseSupplierSelect')?.value);
        if (!Number.isInteger(supplierId) || supplierId <= 0) {
            showToast(t('seller.purchasing.supplier_required_error'));
            return null;
        }
        if (!state.receiptLines.length) {
            showToast(t('seller.purchasing.lines_required'));
            return null;
        }
        const receivedDate = String($('purchaseReceivedDate')?.value || '').trim();
        const dueDate = String($('purchaseDueDate')?.value || '').trim();
        if (!/^\d{4}-\d{2}-\d{2}$/.test(receivedDate)) {
            showToast(t('seller.purchasing.received_date_required'));
            return null;
        }
        // Khi nhập lại chứng từ lịch sử, hạn thanh toán có thể đã nằm trước
        // ngày nhận hàng được ghi nhận trong hệ thống. Giữ nguyên ngày người
        // dùng khai; ô type="date" và server chịu trách nhiệm kiểm định dạng.
        const items = [];
        const quantityByProduct = new Map();
        let receiptTotal = 0;
        for (const line of state.receiptLines) {
            const quantity = Number(line.quantity);
            const unitCost = integerFromInput(line.unit_cost);
            if (!Number.isInteger(quantity) || quantity <= 0) {
                showToast(t('seller.purchasing.quantity_invalid', { name: line.product_name }));
                return null;
            }
            if (quantity > MAX_PURCHASE_QUANTITY) {
                showToast(t('seller.purchasing.quantity_limit', {
                    name: line.product_name,
                    limit: dinhDangSoSeller(MAX_PURCHASE_QUANTITY)
                }));
                return null;
            }
            if (!Number.isInteger(unitCost) || unitCost < 0) {
                showToast(t('seller.purchasing.unit_cost_invalid', { name: line.product_name }));
                return null;
            }
            if (unitCost > MAX_PURCHASE_VND) {
                showToast(t('seller.purchasing.money_limit', {
                    limit: dinhDangTienDoiSoat(MAX_PURCHASE_VND)
                }));
                return null;
            }
            const lineTotal = safePurchaseLineTotal(quantity, unitCost);
            if (!Number.isSafeInteger(lineTotal)) {
                showToast(t('seller.purchasing.line_total_limit', {
                    name: line.product_name,
                    limit: dinhDangTienDoiSoat(MAX_PURCHASE_VND)
                }));
                return null;
            }
            if (lineTotal > MAX_PURCHASE_VND - receiptTotal) {
                showToast(t('seller.purchasing.receipt_total_limit', {
                    limit: dinhDangTienDoiSoat(MAX_PURCHASE_VND)
                }));
                return null;
            }
            receiptTotal += lineTotal;

            const productId = Number(line.product_id);
            const accumulated = (quantityByProduct.get(productId) || 0) + quantity;
            const product = productOptions().find(item => Number(item.id) === productId);
            const currentStock = Number(product?.stock || 0);
            if (
                accumulated > MAX_PURCHASE_QUANTITY
                || (Number.isSafeInteger(currentStock)
                    && currentStock > MAX_PURCHASE_QUANTITY - accumulated)
            ) {
                showToast(t('seller.purchasing.stock_after_limit', {
                    name: line.product_name,
                    limit: dinhDangSoSeller(MAX_PURCHASE_QUANTITY)
                }));
                return null;
            }
            quantityByProduct.set(productId, accumulated);
            const expiry = String(line.expiry_date || '').trim();
            if (line.track_batches && !/^\d{4}-\d{2}-\d{2}$/.test(expiry)) {
                showToast(t('seller.purchasing.expiry_required', { name: line.product_name }));
                return null;
            }
            items.push({
                product_id: Number(line.product_id),
                quantity,
                unit_cost: unitCost,
                expiry_date: line.track_batches ? expiry : null
            });
        }
        const payload = {
            supplier_id: supplierId,
            supplier_invoice_number: String($('purchaseInvoiceNumber')?.value || '').trim() || null,
            received_date: receivedDate,
            due_date: dueDate || null,
            note: String($('purchaseReceiptNote')?.value || '').trim() || null,
            items
        };
        if (includeOperationId) payload.operation_id = operationId('purchase');
        return payload;
    }

    async function sendNewReceipt(pending) {
        pending = persistPendingOperation('receipt_create', pending);
        if (!pending) return;
        state.receiptBusy = true;
        syncGlobalShopLock();
        lockReceiptEditor(true);
        try {
            await apiCall(`/purchase-receipts/${pending.shopId}`, 'POST', pending.payload);
            clearPendingOperation('receipt_create', pending);
            syncGlobalShopLock();
            closePurchaseReceiptForm(true);
            showToast(t('seller.purchasing.receipt_saved'));
            await loadPurchaseReceipts();
        } catch (error) {
            if (unknownOutcome(error)) {
                state.pendingReceiptCreate = pending;
                syncGlobalShopLock();
                lockReceiptEditor(true, true);
                setActionLabel('[data-purchase-action-label="save-draft"]', 'common.retry');
                showToast(t('seller.purchasing.retry_exact_notice'));
            } else {
                clearPendingOperation('receipt_create', pending);
                syncGlobalShopLock();
                lockReceiptEditor(false);
                showToast(error.message);
            }
        } finally {
            state.receiptBusy = false;
            syncGlobalShopLock();
            if (!state.pendingReceiptCreate) lockReceiptEditor(false);
        }
    }

    async function savePurchaseReceiptDraft() {
        if (state.receiptBusy) return;
        if (state.pendingReceiptCreate) return sendNewReceipt(state.pendingReceiptCreate);
        const shopId = selectedShopId();
        if (!shopId) return;
        const isNew = state.editingReceiptId === null;
        const payload = buildReceiptPayload(isNew);
        if (!payload) return;
        if (isNew) {
            return sendNewReceipt({
                shopId,
                payload: exactCopy(payload),
                lines: exactCopy(state.receiptLines)
            });
        }
        const receiptId = state.editingReceiptId;
        state.receiptBusy = true;
        syncGlobalShopLock();
        lockReceiptEditor(true);
        try {
            await apiCall(`/purchase-receipts/receipt/${receiptId}`, 'PUT', payload);
            closePurchaseReceiptForm(true);
            showToast(t('seller.purchasing.receipt_updated'));
            await loadPurchaseReceipts();
        } catch (error) {
            showToast(error.message);
        } finally {
            state.receiptBusy = false;
            syncGlobalShopLock();
            lockReceiptEditor(false);
        }
    }

    function receiptToEditor(receipt) {
        state.editingReceiptId = Number(receipt.id);
        $('purchaseSupplierSelect').value = String(receipt.supplier_id || '');
        $('purchaseInvoiceNumber').value = receipt.supplier_invoice_number || '';
        $('purchaseReceivedDate').value = String(receipt.received_date || '').slice(0, 10) || todayLocal();
        $('purchaseDueDate').value = String(receipt.due_date || '').slice(0, 10);
        $('purchaseReceiptNote').value = receipt.note || '';
        state.receiptLines = receiptItems(receipt).map(item => {
            const product = currentProducts.find(p => Number(p.id) === Number(item.product_id));
            return {
                line_key: state.nextLineKey++,
                product_id: Number(item.product_id),
                product_name: item.product_name || product?.name || '',
                product_code: item.product_code || product?.code || '',
                track_batches: item.track_batches ?? Boolean(product?.track_batches),
                quantity: Number(item.quantity),
                unit_cost: Number(item.unit_cost),
                expiry_date: item.expiry_date || ''
            };
        });
        $('purchaseReceiptFormTitle').textContent = t('seller.purchasing.edit_receipt', {
            code: receiptCode(receipt)
        });
        setActionLabel('[data-purchase-action-label="save-draft"]', 'seller.purchasing.update_draft');
        renderReceiptLines();
        lockReceiptEditor(false);
        $('purchaseReceiptEditor').style.display = 'block';
        $('purchaseReceiptEditor').scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    async function editPurchaseReceipt(id) {
        if (state.pendingReceiptCreate) return showToast(t('seller.purchasing.retry_before_close'));
        const shopId = selectedShopId();
        const generation = selectedGeneration();
        try {
            const receipt = await apiCall(`/purchase-receipts/receipt/${id}`);
            if (!stillCurrent(shopId, generation)) return;
            if (receiptStatus(receipt) !== 'DRAFT') {
                showToast(t('seller.purchasing.confirmed_immutable'));
                return;
            }
            fillSupplierSelect();
            receiptToEditor(receipt);
        } catch (error) {
            showToast(error.message);
        }
    }

    function deletePurchaseReceipt(id) {
        const receipt = state.receipts.find(item => Number(item.id) === Number(id));
        if (!receipt || receiptStatus(receipt) !== 'DRAFT') return;
        showCustomConfirm(
            t('seller.purchasing.delete_receipt_title'),
            t('seller.purchasing.delete_receipt_confirm', { code: receiptCode(receipt) }),
            async () => {
                try {
                    await apiCall(`/purchase-receipts/receipt/${id}`, 'DELETE');
                    showToast(t('seller.purchasing.receipt_deleted'));
                    loadPurchaseReceipts();
                } catch (error) {
                    showToast(error.message);
                }
            },
            t('common.delete')
        );
    }

    function renderConfirmSummary(receipt) {
        if (!receipt || !$('purchaseConfirmSummary')) return;
        $('purchaseConfirmSummary').innerHTML = `
            <div class="purchase-detail-meta">
                <div><small>${escapeHtml(t('seller.purchasing.receipt_code'))}</small><br><strong>${escapeHtml(receiptCode(receipt))}</strong></div>
                <div><small>${escapeHtml(t('seller.purchasing.supplier'))}</small><br><strong>${escapeHtml(receipt.supplier_name || '')}</strong></div>
                <div><small>${escapeHtml(t('seller.purchasing.items_count'))}</small><br><strong>${escapeHtml(dinhDangSoSeller(receiptItems(receipt).length))}</strong></div>
                <div><small>${escapeHtml(t('seller.purchasing.receipt_total'))}</small><br><strong>${escapeHtml(dinhDangTienDoiSoat(receipt.total_amount || 0))}</strong></div>
            </div>`;
    }

    function updatePurchaseConfirmPreview() {
        const receipt = state.confirmReceipt;
        if (!receipt) return;
        const total = Number(receipt.total_amount || 0);
        const raw = String($('purchaseConfirmPaid')?.value || '').trim();
        const paid = raw === '' ? NaN : integerFromInput(raw);
        const remaining = Number.isInteger(paid) && paid >= 0 && paid <= total
            ? total - paid
            : total;
        if ($('purchaseConfirmRemaining')) {
            $('purchaseConfirmRemaining').textContent = dinhDangTienDoiSoat(remaining);
        }
        if ($('purchaseConfirmPaymentFields')) {
            $('purchaseConfirmPaymentFields').style.display = paid === 0 ? 'none' : 'block';
        }
    }

    function updatePurchaseConfirmPaymentRules() {
        const method = $('purchaseConfirmMethod')?.value;
        if ($('purchaseConfirmReferenceHint')) {
            $('purchaseConfirmReferenceHint').textContent = t(
                method === 'TRANSFER'
                    ? 'seller.purchasing.reference_transfer_hint'
                    : 'seller.purchasing.reference_optional_hint'
            );
        }
        if ($('purchaseConfirmNoteHint')) {
            $('purchaseConfirmNoteHint').textContent = t(
                method === 'OUTSIDE'
                    ? 'seller.purchasing.outside_note_required_hint'
                    : 'seller.purchasing.note_optional_hint'
            );
        }
    }

    function lockConfirmModal(locked, retry = false) {
        ['purchaseConfirmPaid', 'purchaseConfirmMethod', 'purchaseConfirmReference',
            'purchaseConfirmNote'].forEach(id => {
            if ($(id)) $(id).disabled = Boolean(locked);
        });
        if ($('purchaseConfirmButton')) $('purchaseConfirmButton').disabled = Boolean(locked && !retry);
        if ($('purchaseConfirmCancelButton')) $('purchaseConfirmCancelButton').disabled = Boolean(retry);
        if ($('purchaseConfirmRetryNotice')) {
            $('purchaseConfirmRetryNotice').style.display = retry ? 'block' : 'none';
        }
    }

    async function openPurchaseConfirmModal(id) {
        if (blockForOtherPendingOperation('receipt_confirm')) return;
        if (state.pendingReceiptConfirm) {
            $('purchaseConfirmModal').style.display = 'flex';
            lockConfirmModal(true, true);
            return;
        }
        const shopId = selectedShopId();
        const generation = selectedGeneration();
        try {
            const receipt = await apiCall(`/purchase-receipts/receipt/${id}`);
            if (!stillCurrent(shopId, generation)) return;
            if (receiptStatus(receipt) !== 'DRAFT') {
                showToast(t('seller.purchasing.confirmed_immutable'));
                loadPurchaseReceipts();
                return;
            }
            state.confirmReceipt = receipt;
            renderConfirmSummary(receipt);
            applyPaymentMethodRoleVisibility();
            $('purchaseConfirmPaid').value = '';
            $('purchaseConfirmMethod').value = '';
            $('purchaseConfirmReference').value = '';
            $('purchaseConfirmNote').value = '';
            lockConfirmModal(false);
            updatePurchaseConfirmPreview();
            updatePurchaseConfirmPaymentRules();
            $('purchaseConfirmModal').style.display = 'flex';
            setTimeout(() => $('purchaseConfirmPaid')?.focus(), 0);
        } catch (error) {
            showToast(error.message);
        }
    }

    function closePurchaseConfirmModal(force = false) {
        if (!force && state.pendingReceiptConfirm) {
            showToast(t('seller.purchasing.retry_before_close'));
            return;
        }
        if ($('purchaseConfirmModal')) $('purchaseConfirmModal').style.display = 'none';
        if (!state.pendingReceiptConfirm) state.confirmReceipt = null;
    }

    function buildConfirmPayload() {
        const receipt = state.confirmReceipt;
        if (!receipt) return null;
        const draftFingerprint = String(receipt.draft_fingerprint || '').trim();
        if (!/^[0-9a-f]{64}$/.test(draftFingerprint)) {
            // Không có dấu vân tay thì không thể biết đây còn là đúng bản nháp
            // người dùng vừa xem. Đóng modal để lần bấm tiếp theo bắt buộc tải
            // lại chi tiết thay vì chốt mù dữ liệu đang giữ trong RAM.
            closePurchaseConfirmModal(true);
            loadPurchaseReceipts();
            showToast(t('seller.actions.reload'));
            return null;
        }
        const raw = String($('purchaseConfirmPaid')?.value || '').trim();
        const paid = raw === '' ? NaN : integerFromInput(raw);
        const total = Number(receipt.total_amount || 0);
        if (!Number.isInteger(paid) || paid < 0 || paid > total) {
            showToast(t('seller.purchasing.paid_invalid', {
                total: dinhDangTienDoiSoat(total)
            }));
            return null;
        }
        if (paid > MAX_PURCHASE_VND) {
            showToast(t('seller.purchasing.money_limit', {
                limit: dinhDangTienDoiSoat(MAX_PURCHASE_VND)
            }));
            return null;
        }
        const method = paid > 0 ? String($('purchaseConfirmMethod')?.value || '') : null;
        const reference = paid > 0
            ? (String($('purchaseConfirmReference')?.value || '').trim() || null)
            : null;
        const note = paid > 0
            ? (String($('purchaseConfirmNote')?.value || '').trim() || null)
            : null;
        if (paid > 0 && !availablePaymentMethods().includes(method)) {
            showToast(t('seller.purchasing.payment_method_required'));
            return null;
        }
        if (paid > 0 && method === 'OUTSIDE' && !note) {
            showToast(t('seller.purchasing.outside_note_required'));
            return null;
        }
        return {
            operation_id: operationId('purchase-confirm'),
            draft_fingerprint: draftFingerprint,
            paid_amount: paid,
            method,
            note,
            reference
        };
    }

    async function sendReceiptConfirm(pending) {
        pending = persistPendingOperation('receipt_confirm', pending);
        if (!pending) return;
        state.confirmBusy = true;
        syncGlobalShopLock();
        lockConfirmModal(true);
        try {
            await apiCall(
                `/purchase-receipts/receipt/${pending.receiptId}/confirm`,
                'POST',
                pending.payload
            );
            clearPendingOperation('receipt_confirm', pending);
            syncGlobalShopLock();
            closePurchaseConfirmModal(true);
            showToast(t('seller.purchasing.receipt_confirmed'));
            await Promise.all([loadPurchaseReceipts(), loadSuppliers(), loadProducts()]);
        } catch (error) {
            if (unknownOutcome(error)) {
                state.pendingReceiptConfirm = pending;
                syncGlobalShopLock();
                lockConfirmModal(true, true);
                setActionLabel('[data-purchase-action-label="confirm"]', 'common.retry');
                showToast(t('seller.purchasing.confirm_retry_notice'));
            } else if (error?.status === 409) {
                // Nội dung nháp/trạng thái có thể đã đổi ở phiên khác. Không
                // mở khóa modal cũ vì bấm lại sẽ gửi chính dữ liệu người dùng
                // chưa xem. Đóng + tải danh sách; muốn chốt phải bấm lại nút
                // xác nhận để GET chi tiết và fingerprint mới.
                clearPendingOperation('receipt_confirm', pending);
                syncGlobalShopLock();
                setActionLabel(
                    '[data-purchase-action-label="confirm"]',
                    'seller.purchasing.confirm_submit'
                );
                closePurchaseConfirmModal(true);
                await loadPurchaseReceipts();
                showToast(error.message);
            } else {
                clearPendingOperation('receipt_confirm', pending);
                syncGlobalShopLock();
                lockConfirmModal(false);
                showToast(error.message);
            }
        } finally {
            state.confirmBusy = false;
            syncGlobalShopLock();
            if (!state.pendingReceiptConfirm) lockConfirmModal(false);
        }
    }

    async function confirmPurchaseReceipt() {
        if (state.confirmBusy) return;
        if (state.pendingReceiptConfirm) return sendReceiptConfirm(state.pendingReceiptConfirm);
        const receipt = state.confirmReceipt;
        if (!receipt) return;
        const payload = buildConfirmPayload();
        if (!payload) return;
        return sendReceiptConfirm({
            shopId: selectedShopId(),
            receiptId: Number(receipt.id),
            payload: exactCopy(payload),
            receipt: exactCopy(receipt)
        });
    }

    function updateSupplierPaymentPreview() {
        const supplier = state.paymentSupplier;
        if (!supplier) return;
        const before = supplierBalance(supplier);
        const amount = integerFromInput($('supplierPaymentAmount')?.value || '');
        const after = Number.isInteger(amount) && amount > 0 && amount <= before
            ? before - amount
            : before;
        $('supplierPaymentBefore').textContent = dinhDangTienDoiSoat(before);
        $('supplierPaymentAfter').textContent = dinhDangTienDoiSoat(after);
    }

    function updateSupplierPaymentRules() {
        const method = $('supplierPaymentMethod')?.value;
        if ($('supplierPaymentReferenceHint')) {
            $('supplierPaymentReferenceHint').textContent = t(
                method === 'TRANSFER'
                    ? 'seller.purchasing.reference_transfer_hint'
                    : 'seller.purchasing.reference_optional_hint'
            );
        }
        if ($('supplierPaymentNoteHint')) {
            $('supplierPaymentNoteHint').textContent = t(
                method === 'OUTSIDE'
                    ? 'seller.purchasing.outside_note_required_hint'
                    : 'seller.purchasing.note_optional_hint'
            );
        }
    }

    function lockPaymentModal(locked, retry = false) {
        ['supplierPaymentAmount', 'supplierPaymentMethod', 'supplierPaymentReference',
            'supplierPaymentNote'].forEach(id => {
            if ($(id)) $(id).disabled = Boolean(locked);
        });
        if ($('supplierPaymentSubmit')) $('supplierPaymentSubmit').disabled = Boolean(locked && !retry);
        if ($('supplierPaymentCancelButton')) $('supplierPaymentCancelButton').disabled = Boolean(retry);
        if ($('supplierPaymentRetryNotice')) {
            $('supplierPaymentRetryNotice').style.display = retry ? 'block' : 'none';
        }
    }

    function openSupplierPaymentModal(id) {
        if (blockForOtherPendingOperation('supplier_payment')) return;
        if (state.pendingSupplierPayment) {
            $('supplierPaymentModal').style.display = 'flex';
            lockPaymentModal(true, true);
            return;
        }
        const supplier = state.suppliers.find(item => Number(item.id) === Number(id));
        if (!supplier || supplierBalance(supplier) <= 0) return;
        state.paymentSupplier = supplier;
        applyPaymentMethodRoleVisibility();
        $('supplierPaymentTitle').textContent = t('seller.purchasing.pay_supplier_name', {
            name: supplier.name
        });
        $('supplierPaymentDescription').textContent = t('seller.purchasing.payment_desc', {
            balance: dinhDangTienDoiSoat(supplierBalance(supplier))
        });
        $('supplierPaymentAmount').value = '';
        $('supplierPaymentMethod').value = '';
        $('supplierPaymentReference').value = '';
        $('supplierPaymentNote').value = '';
        lockPaymentModal(false);
        updateSupplierPaymentPreview();
        updateSupplierPaymentRules();
        $('supplierPaymentModal').style.display = 'flex';
        setTimeout(() => $('supplierPaymentAmount')?.focus(), 0);
    }

    function closeSupplierPaymentModal(force = false) {
        if (!force && state.pendingSupplierPayment) {
            showToast(t('seller.purchasing.retry_before_close'));
            return;
        }
        if ($('supplierPaymentModal')) $('supplierPaymentModal').style.display = 'none';
        if (!state.pendingSupplierPayment) state.paymentSupplier = null;
    }

    function buildSupplierPaymentPayload() {
        const supplier = state.paymentSupplier;
        if (!supplier) return null;
        const amount = integerFromInput($('supplierPaymentAmount')?.value || '');
        const balance = supplierBalance(supplier);
        if (!Number.isInteger(amount) || amount <= 0 || amount > balance) {
            showToast(t('seller.purchasing.payment_amount_invalid', {
                balance: dinhDangTienDoiSoat(balance)
            }));
            return null;
        }
        if (amount > MAX_PURCHASE_VND) {
            showToast(t('seller.purchasing.money_limit', {
                limit: dinhDangTienDoiSoat(MAX_PURCHASE_VND)
            }));
            return null;
        }
        const method = String($('supplierPaymentMethod')?.value || '');
        const reference = String($('supplierPaymentReference')?.value || '').trim() || null;
        const note = String($('supplierPaymentNote')?.value || '').trim() || null;
        if (!availablePaymentMethods().includes(method)) {
            showToast(t('seller.purchasing.payment_method_required'));
            return null;
        }
        if (method === 'OUTSIDE' && !note) {
            showToast(t('seller.purchasing.outside_note_required'));
            return null;
        }
        return {
            amount,
            method,
            note,
            reference,
            operation_id: operationId('supplier-payment')
        };
    }

    async function sendSupplierPayment(pending) {
        pending = persistPendingOperation('supplier_payment', pending);
        if (!pending) return;
        state.paymentBusy = true;
        syncGlobalShopLock();
        lockPaymentModal(true);
        try {
            await apiCall(
                `/suppliers/member/${pending.supplierId}/payments`,
                'POST',
                pending.payload
            );
            clearPendingOperation('supplier_payment', pending);
            syncGlobalShopLock();
            closeSupplierPaymentModal(true);
            showToast(t('seller.purchasing.payment_saved'));
            await Promise.all([loadSuppliers(), loadPurchaseReceipts()]);
        } catch (error) {
            if (unknownOutcome(error)) {
                state.pendingSupplierPayment = pending;
                syncGlobalShopLock();
                lockPaymentModal(true, true);
                setActionLabel('[data-purchase-action-label="pay"]', 'common.retry');
                showToast(t('seller.purchasing.payment_retry_notice'));
            } else {
                clearPendingOperation('supplier_payment', pending);
                syncGlobalShopLock();
                lockPaymentModal(false);
                showToast(error.message);
            }
        } finally {
            state.paymentBusy = false;
            syncGlobalShopLock();
            if (!state.pendingSupplierPayment) lockPaymentModal(false);
        }
    }

    async function submitSupplierPayment() {
        if (state.paymentBusy) return;
        if (state.pendingSupplierPayment) return sendSupplierPayment(state.pendingSupplierPayment);
        const supplier = state.paymentSupplier;
        if (!supplier) return;
        const payload = buildSupplierPaymentPayload();
        if (!payload) return;
        return sendSupplierPayment({
            shopId: selectedShopId(),
            supplierId: Number(supplier.id),
            payload: exactCopy(payload),
            supplier: exactCopy(supplier)
        });
    }

    function renderReceiptDetail(receipt) {
        if (!receipt) return;
        $('purchaseReceiptDetailTitle').textContent = t('seller.purchasing.receipt_detail_code', {
            code: receiptCode(receipt)
        });
        $('purchaseReceiptDetailSummary').textContent = t('seller.purchasing.receipt_detail_summary', {
            supplier: receipt.supplier_name || '',
            status: t(receiptStatus(receipt) === 'DRAFT'
                ? 'seller.purchasing.status_draft'
                : 'seller.purchasing.status_confirmed')
        });
        const rows = receiptItems(receipt).map(item => `<tr>
            <td>${escapeHtml(item.product_name || '')}${item.product_code ? `<br><small>${escapeHtml(item.product_code)}</small>` : ''}</td>
            <td>${escapeHtml(dinhDangSoSeller(item.quantity || 0))}</td>
            <td>${escapeHtml(dinhDangTienDoiSoat(item.unit_cost || 0))}</td>
            <td>${escapeHtml(item.expiry_date ? dateOnly(item.expiry_date) : '—')}</td>
            <td>${escapeHtml(dinhDangTienDoiSoat(item.line_total ?? Number(item.quantity || 0) * Number(item.unit_cost || 0)))}</td>
        </tr>`).join('');
        $('purchaseReceiptDetailContent').innerHTML = `
            <div class="purchase-detail-meta">
                <div><small>${escapeHtml(t('seller.purchasing.supplier_invoice_number'))}</small><br><strong>${escapeHtml(receipt.supplier_invoice_number || '—')}</strong></div>
                <div><small>${escapeHtml(t('seller.purchasing.received_date'))}</small><br><strong>${escapeHtml(dateOnly(receipt.received_date))}</strong></div>
                <div><small>${escapeHtml(t('seller.purchasing.due_date_short'))}</small><br><strong>${escapeHtml(receipt.due_date ? dateOnly(receipt.due_date) : '—')}</strong></div>
                <div><small>${escapeHtml(t('seller.table.status'))}</small><br>${statusBadge(receiptStatus(receipt))}</div>
                <div><small>${escapeHtml(t('seller.purchasing.created_at'))}</small><br><strong>${escapeHtml(dinhDangNgayGio(receipt.created_at))}</strong></div>
                <div><small>${escapeHtml(t('seller.purchasing.confirmed_at'))}</small><br><strong>${escapeHtml(receipt.confirmed_at ? dinhDangNgayGio(receipt.confirmed_at) : '—')}</strong></div>
            </div>
            <div class="table-responsive"><table class="db-table"><thead><tr>
                <th>${escapeHtml(t('seller.table.product'))}</th><th>${escapeHtml(t('seller.table.quantity_short'))}</th>
                <th>${escapeHtml(t('seller.table.unit_price'))}</th><th>${escapeHtml(t('seller.purchasing.expiry_date'))}</th>
                <th>${escapeHtml(t('seller.table.line_total'))}</th>
            </tr></thead><tbody>${rows}</tbody></table></div>
            <div class="purchase-detail-meta">
                <div><small>${escapeHtml(t('seller.purchasing.receipt_total'))}</small><br><strong>${escapeHtml(dinhDangTienDoiSoat(receipt.total_amount || 0))}</strong></div>
                <div><small>${escapeHtml(t('seller.purchasing.paid'))}</small><br><strong>${escapeHtml(dinhDangTienDoiSoat(receipt.paid_amount || 0))}</strong></div>
                <div><small>${escapeHtml(t('seller.purchasing.remaining'))}</small><br><strong>${escapeHtml(dinhDangTienDoiSoat(receipt.remaining_amount || 0))}</strong></div>
                <div><small>${escapeHtml(t('seller.fields.note'))}</small><br><strong>${escapeHtml(receipt.note || '—')}</strong></div>
            </div>`;
    }

    async function openPurchaseReceiptDetail(id) {
        const shopId = selectedShopId();
        const generation = selectedGeneration();
        try {
            const receipt = await apiCall(`/purchase-receipts/receipt/${id}`);
            if (!stillCurrent(shopId, generation)) return;
            state.currentReceiptDetail = receipt;
            renderReceiptDetail(receipt);
            $('purchaseReceiptDetailModal').style.display = 'flex';
        } catch (error) {
            showToast(error.message);
        }
    }

    function closePurchaseReceiptDetail() {
        if ($('purchaseReceiptDetailModal')) $('purchaseReceiptDetailModal').style.display = 'none';
        state.currentReceiptDetail = null;
    }

    function rerender() {
        renderSuppliers();
        renderReceipts();
        renderReceiptLines();
        fillSupplierSelect();
        filterPurchaseProductOptions();
        updateSummaryCards();
        if (state.currentSupplierDetail) renderSupplierHistory(state.currentSupplierDetail);
        if (state.currentReceiptDetail) renderReceiptDetail(state.currentReceiptDetail);
        if (state.confirmReceipt) {
            renderConfirmSummary(state.confirmReceipt);
            updatePurchaseConfirmPreview();
            updatePurchaseConfirmPaymentRules();
        }
        if (state.paymentSupplier) {
            $('supplierPaymentTitle').textContent = t('seller.purchasing.pay_supplier_name', {
                name: state.paymentSupplier.name
            });
            $('supplierPaymentDescription').textContent = t('seller.purchasing.payment_desc', {
                balance: dinhDangTienDoiSoat(supplierBalance(state.paymentSupplier))
            });
            updateSupplierPaymentPreview();
            updateSupplierPaymentRules();
        }
        if ($('purchaseReceiptEditor')?.style.display !== 'none') {
            $('purchaseReceiptFormTitle').textContent = t(
                state.editingReceiptId === null
                    ? 'seller.purchasing.new_receipt'
                    : 'seller.purchasing.edit_receipt',
                { code: state.editingReceiptId || '' }
            );
        }
        if ($('supplierFormModal')?.style.display === 'flex') {
            $('supplierFormTitle').textContent = t(
                state.editingSupplierId === null
                    ? 'seller.purchasing.new_supplier'
                    : 'seller.purchasing.edit_supplier'
            );
        }
        setActionLabel(
            '[data-purchase-action-label="save-draft"]',
            state.pendingReceiptCreate
                ? 'common.retry'
                : (state.editingReceiptId === null
                    ? 'seller.purchasing.save_draft'
                    : 'seller.purchasing.update_draft')
        );
        setActionLabel(
            '[data-supplier-action-label="save"]',
            state.pendingSupplierCreate
                ? 'common.retry'
                : (state.editingSupplierId === null ? 'common.save' : 'common.update')
        );
        setActionLabel(
            '[data-purchase-action-label="confirm"]',
            state.pendingReceiptConfirm ? 'common.retry' : 'seller.purchasing.confirm_submit'
        );
        setActionLabel(
            '[data-purchase-action-label="pay"]',
            state.pendingSupplierPayment ? 'common.retry' : 'seller.purchasing.payment_submit'
        );
    }

    // Script nằm cuối seller.html nên hai select đã tồn tại ở thời điểm này.
    // ADMIN không có màn mở ca/két; ẩn lựa chọn không thể thực hiện được trước
    // khi người dùng mở modal để họ chỉ thấy hai nguồn tiền hợp lệ với UI đó.
    applyPaymentMethodRoleVisibility();

    // Chỉ đóng modal khi kết quả request đã rõ. Khi kết quả mạng chưa chắc chắn,
    // nút Đóng/Escape đều bị chặn để không làm mất operation_id cần retry.
    document.addEventListener('click', event => {
        const mainTabButton = event.target.closest?.('.tab-btn[data-main-tab]');
        if (
            !mainTabButton
            || mainTabButton.dataset.mainTab === 'purchasing'
            || !hasUnknownOperation()
        ) return;
        event.preventDefault();
        event.stopImmediatePropagation();
        switchTab('purchasing', $('tabPurchasing'));
        restorePendingUi(true);
    }, true);

    document.addEventListener('keydown', event => {
        if (event.key !== 'Escape') return;
        if ($('supplierPaymentModal')?.style.display === 'flex') closeSupplierPaymentModal();
        else if ($('purchaseConfirmModal')?.style.display === 'flex') closePurchaseConfirmModal();
        else if ($('supplierFormModal')?.style.display === 'flex') closeSupplierForm();
        else if ($('supplierHistoryModal')?.style.display === 'flex') closeSupplierHistory();
        else if ($('purchaseReceiptDetailModal')?.style.display === 'flex') closePurchaseReceiptDetail();
    });

    ['supplierFormModal', 'purchaseConfirmModal', 'supplierPaymentModal',
        'supplierHistoryModal', 'purchaseReceiptDetailModal'].forEach(id => {
        $(id)?.addEventListener('click', event => {
            if (event.target !== event.currentTarget) return;
            if (id === 'supplierFormModal') closeSupplierForm();
            if (id === 'purchaseConfirmModal') closePurchaseConfirmModal();
            if (id === 'supplierPaymentModal') closeSupplierPaymentModal();
            if (id === 'supplierHistoryModal') closeSupplierHistory();
            if (id === 'purchaseReceiptDetailModal') closePurchaseReceiptDetail();
        });
    });

    Object.assign(global, {
        switchPurchasingSubTab,
        loadSuppliers,
        loadPurchaseReceipts,
        openSupplierForm,
        closeSupplierForm,
        saveSupplier,
        toggleSupplierStatus,
        deleteSupplier,
        openSupplierHistory,
        closeSupplierHistory,
        openSupplierPaymentModal,
        closeSupplierPaymentModal,
        updateSupplierPaymentPreview,
        updateSupplierPaymentRules,
        submitSupplierPayment,
        openPurchaseReceiptForm,
        closePurchaseReceiptForm,
        filterPurchaseProductOptions,
        addPurchaseReceiptLine,
        updatePurchaseReceiptLine,
        removePurchaseReceiptLine,
        savePurchaseReceiptDraft,
        editPurchaseReceipt,
        deletePurchaseReceipt,
        openPurchaseConfirmModal,
        closePurchaseConfirmModal,
        updatePurchaseConfirmPreview,
        updatePurchaseConfirmPaymentRules,
        confirmPurchaseReceipt,
        openPurchaseReceiptDetail,
        closePurchaseReceiptDetail
    });

    global.FSellingPurchasing = Object.freeze({
        load,
        rerender,
        resetForShopChange,
        productsUpdated: filterPurchaseProductOptions
    });
})(window);
