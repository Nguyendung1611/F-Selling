// POS dùng chung cho chủ shop (SELLER) và nhân viên (STAFF).
(function () {
    const role = localStorage.getItem('role');
    if(role !== 'SELLER' && role !== 'STAFF') redirectToLogin();
})();
let allShops = [];
let currentShopId = parseInt(localStorage.getItem('currentShopId'));

let cart = [];
let products = [];
let categories = [];
let currentCategoryId = null;
let currentVoucher = null;
let selectedCustomerId = null;  // C2d: khách gắn vào đơn (null = vãng lai)
let discount = 0;
let subtotal = 0;
let total = 0;
let paymentMethod = 'transfer';
let currentOrderId = null;
let lastPaymentNoticeKey = null;
let activeShift = null;
let shiftRequestId = 0;
let movementType = 'PAY_IN';
let movementOperationId = null;
let cashTenderedAmount = 0;
let checkoutBusy = false;
let pendingCashOrderId = null;
let checkoutOperationId = null;
let pendingCheckoutState = null;
let pendingMovementState = null;
let voucherMessageKey = null;
let voucherMessageRaw = '';
let shiftBarState = 'loading';
let shiftBarMessage = '';
let lastPaymentStatus = null;

const POS_CHECKOUT_STORAGE_PREFIX = 'fselling.pos.checkout.v2';
const POS_MOVEMENT_STORAGE_PREFIX = 'fselling.pos.movement.v1';

function dich(key, options = {}) {
    return window.t ? window.t(key, options) : (options.defaultValue || key);
}

// Bản dịch là plain text. Khi đặt cạnh markup/icon bằng innerHTML vẫn escape
// giống dữ liệu người dùng để catalog không thể vô tình trở thành HTML.
function dichHtml(key, options = {}) {
    return escapeHtml(dich(key, options));
}

function dinhDangSoPOS(value) {
    if (window.FSellingI18n?.formatNumber) {
        return window.FSellingI18n.formatNumber(value, { maximumFractionDigits: 0 });
    }
    return Math.round(Number(value) || 0).toLocaleString('vi-VN');
}

function htmlNut(icon, key, options = {}) {
    return `<i class="ph ${icon}"></i> ${dichHtml(key, options)}`;
}

function sessionKey(prefix, suffix = '') {
    const username = localStorage.getItem('username') || 'anonymous';
    return `${prefix}:${username}${suffix ? `:${suffix}` : ''}`;
}

function docSessionJson(key) {
    try {
        const raw = sessionStorage.getItem(key);
        return raw ? JSON.parse(raw) : null;
    } catch (e) {
        console.warn('Không đọc được trạng thái POS trong sessionStorage:', e);
        return null;
    }
}

function ghiSessionJson(key, value) {
    try {
        sessionStorage.setItem(key, JSON.stringify(value));
    } catch (e) {
        // POS vẫn hoạt động khi trình duyệt chặn storage, nhưng không thể tự phục
        // hồi qua reload. Không được làm vỡ luồng bán hàng chỉ vì lỗi quota.
        console.warn('Không lưu được trạng thái POS trong sessionStorage:', e);
    }
}

function xoaSessionKey(key) {
    try {
        sessionStorage.removeItem(key);
    } catch (e) {
        console.warn('Không xóa được trạng thái POS trong sessionStorage:', e);
    }
}

function checkoutStorageKey() {
    return sessionKey(POS_CHECKOUT_STORAGE_PREFIX);
}

function docCheckoutDangDo() {
    const state = docSessionJson(checkoutStorageKey());
    if (!state || state.version !== 2) return null;
    if (state.username !== (localStorage.getItem('username') || 'anonymous')) return null;
    return state;
}

function luuCheckoutDangDo(state) {
    pendingCheckoutState = {
        ...state,
        version: 2,
        username: localStorage.getItem('username') || 'anonymous',
        saved_at: new Date().toISOString()
    };
    ghiSessionJson(checkoutStorageKey(), pendingCheckoutState);
    return pendingCheckoutState;
}

function xoaCheckoutDangDo() {
    pendingCheckoutState = null;
    xoaSessionKey(checkoutStorageKey());
}

function movementStorageKey(shiftId) {
    return sessionKey(POS_MOVEMENT_STORAGE_PREFIX, String(shiftId || 'none'));
}

function docMovementDangDo(shiftId) {
    const state = docSessionJson(movementStorageKey(shiftId));
    if (!state || state.version !== 1 || Number(state.shift_id) !== Number(shiftId)) return null;
    return state;
}

function luuMovementDangDo(state) {
    pendingMovementState = {
        ...state,
        version: 1,
        username: localStorage.getItem('username') || 'anonymous',
        saved_at: new Date().toISOString()
    };
    ghiSessionJson(movementStorageKey(state.shift_id), pendingMovementState);
    return pendingMovementState;
}

function xoaMovementDangDo(state = pendingMovementState) {
    if (state?.shift_id) xoaSessionKey(movementStorageKey(state.shift_id));
    pendingMovementState = null;
    movementOperationId = null;
}

function laLoi4xx(error) {
    return Number(error?.status) >= 400 && Number(error?.status) < 500;
}

async function loadShop() {
    try {
        const res = await apiCall('/shops');
        allShops = res.filter(s => s.is_active !== false); // fallback if undefined
        pendingCheckoutState = docCheckoutDangDo();
        const pendingShopId = Number(pendingCheckoutState?.shop_id);
        const coQuyenShopDangCho =
            pendingShopId && allShops.some(s => s.id === pendingShopId);
        if (pendingCheckoutState && !coQuyenShopDangCho) {
            // Shop đã bị xóa/khóa hoặc tài khoản không còn quyền truy cập:
            // không giữ một thao tác vĩnh viễn mà người dùng không thể xử lý.
            xoaCheckoutDangDo();
            showToast(dich('pos.order.stale_state_removed'));
        } else if (coQuyenShopDangCho) {
            // Một đơn chưa rõ kết quả phải kéo tab về đúng shop của nó. Nếu giữ
            // shop mới từ localStorage, nút retry/hủy có thể thao tác nhầm quầy.
            currentShopId = pendingShopId;
            localStorage.setItem('currentShopId', currentShopId);
        }
        const sel = document.getElementById('shopSelect');
        sel.innerHTML = `<option value="">${dichHtml('pos.shop.select')}</option>`;
        allShops.forEach(s => {
            sel.innerHTML += `<option value="${s.id}" ${s.id === currentShopId ? 'selected' : ''}>${escapeHtml(s.name)}</option>`;
        });
        if(allShops.length > 0 && !currentShopId) {
            currentShopId = allShops[0].id;
            localStorage.setItem('currentShopId', currentShopId);
            sel.value = currentShopId;
        }
        await Promise.all([loadCategories(), loadProducts(), loadCurrentShift()]);
        phucHoiCheckoutDangDo();
    } catch(e) {
        showToast(e.message || dich('pos.order.load_shops_error'));
    }
}

async function changeShopPOS() {
    const val = document.getElementById('shopSelect').value;
    if(!val) return;
    const shopMoi = parseInt(val);
    if (checkoutOperationId || currentOrderId || pendingCashOrderId) {
        document.getElementById('shopSelect').value = String(currentShopId);
        return showToast(dich('pos.order.finish_before_shop'));
    }
    if (activeShift && shopMoi !== currentShopId) {
        document.getElementById('shopSelect').value = String(currentShopId);
        return showToast(dich('pos.order.close_shift_before_shop'));
    }
    currentShopId = shopMoi;
    localStorage.setItem('currentShopId', currentShopId);
    resetPOS();
    await Promise.all([loadCategories(), loadProducts(), loadCurrentShift()]);
}

async function loadProducts() {
    if(!currentShopId) return;
    try {
        const res = await apiCall(`/products/${currentShopId}`);
        products = res.filter(p => p.is_active !== false && p.category_is_active !== false);
        filterAndRenderProducts();
    } catch (e) { showToast(e.message); }
}

async function loadCategories() {
    if(!currentShopId) return;
    try {
        const res = await apiCall(`/categories/${currentShopId}`);
        categories = res.filter(c => c.is_active !== false);
        renderCategories();
    } catch (e) { console.error(e); }
}

function renderCategories() {
    const container = document.getElementById('categoryFilter');
    if(!container) return;
    container.innerHTML = `<button class="category-btn ${!currentCategoryId ? 'active' : ''}" onclick="filterByCategory(null)">${dichHtml('pos.products.all_categories')}</button>`;
    categories.forEach(c => {
        container.innerHTML += `<button class="category-btn ${currentCategoryId === c.id ? 'active' : ''}" onclick="filterByCategory(${c.id})">${escapeHtml(c.name)}</button>`;
    });
}

function filterByCategory(catId) {
    currentCategoryId = catId;
    renderCategories();
    filterAndRenderProducts();
}

function filterAndRenderProducts() {
    let filtered = products;
    if (currentCategoryId) {
        filtered = filtered.filter(p => p.category_id === currentCategoryId);
    }
    const searchVal = document.getElementById('searchProd').value.toLowerCase();
    if (searchVal) {
        filtered = filtered.filter(p => (p.code && p.code.toLowerCase() === searchVal) || p.name.toLowerCase().includes(searchVal));
    }
    renderProducts(filtered);
}

function renderProducts(list) {
    const grid = document.getElementById('productGrid');
    grid.innerHTML = '';
    list.forEach(p => {
        const imgUrl = p.image_url ? p.image_url : 'https://placehold.co/150x150/1E293B/FFF?text=SP';
        const div = document.createElement('div');
        div.className = 'product-card';
        div.innerHTML = `
            <div class="product-stock" style="color: white;">${dichHtml('pos.products.stock', { count: p.stock })}</div>
            <img src="${imgUrl}" onerror="this.src='https://via.placeholder.com/150x150?text=Error'" class="product-img">
            <div class="product-info">
                <div class="product-name" title="${escapeHtml(p.name)}">${escapeHtml(p.name)}</div>
                <div class="product-price">${escapeHtml(dinhDangTien(p.price))}</div>
            </div>
        `;
        div.onclick = () => addToCart(p);
        grid.appendChild(div);
    });
}

// Tìm kiếm
document.getElementById('searchProd').addEventListener('input', (e) => {
    filterAndRenderProducts();
});

// ===== Quét mã vạch =====

/**
 * Tìm trong danh sách đã tải: ưu tiên mã vạch, sau đó tới mã nội bộ (SP-xxx).
 * Cả hai mã đều được database đảm bảo duy nhất trong mỗi shop, nên khớp được là
 * chắc chắn đúng một sản phẩm.
 */
function timTheoMaQuet(ma) {
    return products.find(p => p.barcode && p.barcode.toUpperCase() === ma)
        || products.find(p => p.code && p.code.toUpperCase() === ma);
}

async function xuLyQuetPOS(ma) {
    const sp = timTheoMaQuet(ma);
    if (sp) {
        addToCart(sp) ? BarcodeScanner.bipOk() : BarcodeScanner.bipLoi();
        return;
    }

    // Không có trong danh sách đang giữ: có thể danh sách đã cũ (nhân viên khác
    // vừa thêm sản phẩm). Hỏi lại server rồi mới kết luận là không tìm thấy.
    try {
        const spMoi = await apiCall(`/products/${currentShopId}/barcode/${encodeURIComponent(ma)}`);
        addToCart(spMoi) ? BarcodeScanner.bipOk() : BarcodeScanner.bipLoi();
        loadProducts();  // đồng bộ lại để lượt quét sau khớp ngay tại máy
    } catch (e) {
        BarcodeScanner.bipLoi();
        showToast(dich('pos.products.barcode_not_found', { code: ma }));
    }
}

BarcodeScanner.batDau(xuLyQuetPOS);

// Trả về true nếu thực sự thêm được. Lượt quét dựa vào kết quả này để bíp đúng:
// bíp "xong" trong khi hàng không vào giỏ là kiểu sai nguy hiểm nhất ở quầy.
//
// Dòng trong giỏ được gộp theo product_id chứ không theo tên: hai sản phẩm khác
// nhau mà trùng tên từng bị cộng dồn vào một dòng, tính tiền sai.
function dangKhoaChinhSuaDon() {
    if (currentOrderId || pendingCashOrderId) {
        showToast(dich('pos.cart.locked_created'));
        return true;
    }
    if (checkoutOperationId) {
        showToast(dich('pos.cart.locked_unknown'));
        return true;
    }
    return false;
}

function addToCart(p) {
    try {
        if (dangKhoaChinhSuaDon()) return false;
        if(!cart) cart = [];
        if(p.stock <= 0) { showToast(dich('pos.products.out_of_stock')); return false; }
        const existing = cart.find(i => i.product_id === p.id);
        if(existing) {
            if(existing.quantity >= p.stock) { showToast(dich('pos.products.exceeds_stock')); return false; }
            existing.quantity++;
        }
        else cart.push({ product_id: p.id, product_name: p.name, price: p.price, quantity: 1, max_stock: p.stock });
        calcCart();
        return true;
    } catch (err) {
        console.error("Lỗi thêm vào giỏ:", err);
        showToast(dich('pos.products.add_error'));
        return false;
    }
}

function updateQty(index, delta) {
    if (dangKhoaChinhSuaDon()) return;
    const item = cart[index];
    if(item.quantity + delta > item.max_stock) return showToast(dich('pos.products.exceeds_stock'));
    if(item.quantity + delta <= 0) cart.splice(index, 1);
    else item.quantity += delta;
    calcCart();
}

function removeItem(index) {
    if (dangKhoaChinhSuaDon()) return;
    cart.splice(index, 1);
    calcCart();
}

function calcCart() {
    try {
        if(!cart) cart = [];
        subtotal = cart.reduce((sum, item) => sum + (item.price * item.quantity), 0);
        if(currentVoucher) applyVoucher(); // Re-apply voucher logic
        else { discount = 0; total = subtotal; updateUI(); }
    } catch (err) {
        console.error("Lỗi tính tiền:", err);
    }
}

async function applyVoucher() {
    if (dangKhoaChinhSuaDon()) return;
    const code = document.getElementById('voucherInput').value.toUpperCase();
    if(!code) {
        currentVoucher = null; discount = 0; total = subtotal;
        voucherMessageKey = null;
        voucherMessageRaw = '';
        document.getElementById('voucherMsg').innerText = "";
        updateUI(); return;
    }
    if(subtotal === 0) return;

    const formData = new FormData();
    formData.append('subtotal', subtotal);
    formData.append('voucher_code', code);

    try {
        const res = await fetch(`/api/vouchers/apply/${currentShopId}`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${getToken()}`,
                'Accept-Language': getCurrentLocale()
            },
            body: formData
        });
        let data;
        try {
            data = await res.json();
        } catch (parseError) {
            const error = new Error(dich('common.api_error'));
            error.translationKey = 'common.api_error';
            throw error;
        }
        if(!res.ok) {
            currentVoucher = null; discount = 0; total = subtotal;
            voucherMessageKey = null;
            voucherMessageRaw = data.detail || '';
            document.getElementById('voucherMsg').innerText = voucherMessageRaw;
            document.getElementById('voucherMsg').style.color = '#EF4444';
        } else {
            currentVoucher = code;
            discount = data.discount_amount;
            total = data.new_total;
            voucherMessageKey = 'pos.voucher.success';
            voucherMessageRaw = '';
            document.getElementById('voucherMsg').innerText = dich(voucherMessageKey);
            document.getElementById('voucherMsg').style.color = 'var(--success)';
        }
        updateUI();
    } catch(e) {
        currentVoucher = null;
        discount = 0;
        total = subtotal;
        voucherMessageKey = e.translationKey || 'common.network_error';
        voucherMessageRaw = '';
        const voucherMessage = document.getElementById('voucherMsg');
        voucherMessage.innerText = dich(voucherMessageKey);
        voucherMessage.style.color = '#EF4444';
        updateUI();
    }
}

function updateUI() {
    const container = document.getElementById('cartContainer');
    container.innerHTML = '';
    cart.forEach((item, index) => {
        // Hiện cả phép nhân lẫn thành tiền: quét nhanh nhiều món thì không ai
        // nhớ đã quét mấy lần món nào, nhìn thành tiền là thấy ngay bất thường.
        const thanhTien = item.price * item.quantity;
        container.innerHTML += `
            <div class="cart-item">
                <div class="cart-o-ten">
                    <div class="cart-name" title="${escapeHtml(item.product_name)}">${escapeHtml(item.product_name)}</div>
                    <div class="cart-donGia">${escapeHtml(dinhDangTien(item.price))} × ${dinhDangSoPOS(item.quantity)}</div>
                </div>
                <div class="cart-o-sl" style="display: flex; gap: 0.3rem; align-items: center; color: white;">
                    <button class="btn-qty" onclick="updateQty(${index}, -1)">-</button>
                    <span>${item.quantity}</span>
                    <button class="btn-qty" onclick="updateQty(${index}, 1)">+</button>
                </div>
                <div class="cart-thanhTien cart-o-tien">${escapeHtml(dinhDangTien(thanhTien))}</div>
                <button class="btn-del cart-o-xoa" onclick="removeItem(${index})"><i class="ph ph-trash"></i></button>
            </div>
        `;
    });

    document.getElementById('txtSubtotal').innerText = dinhDangTien(subtotal);
    document.getElementById('txtDiscount').innerText = dinhDangTien(-discount);
    document.getElementById('txtTotal').innerText = dinhDangTien(total);
    renderCashQuickAmounts();
    capNhatTienKhachDua();
}

function setMethod(m) {
    if (currentOrderId || pendingCashOrderId) {
        return showToast(dich('pos.checkout.method_locked'));
    }
    if (checkoutOperationId && !currentOrderId) {
        return showToast(dich('pos.checkout.method_retry_first'));
    }
    apDungPhuongThucThanhToan(m, true);
}

function apDungPhuongThucThanhToan(m, focusCash = false) {
    paymentMethod = m;
    document.getElementById('btnMethodQR').classList.remove('active');
    document.getElementById('btnMethodCash').classList.remove('active');
    if(m==='transfer') document.getElementById('btnMethodQR').classList.add('active');
    else document.getElementById('btnMethodCash').classList.add('active');
    
    const cashSection = document.getElementById('cashTenderSection');
    if (cashSection) cashSection.style.display = m === 'cash' ? 'block' : 'none';

    // QR của đơn cũ không được nằm cạnh luồng thu tiền mặt.
    if(m === 'cash') {
        document.getElementById('qrSection').style.display = 'none';
        if (focusCash) setTimeout(() => document.getElementById('cashTenderedInput')?.focus(), 0);
    }
    renderCashQuickAmounts();
    capNhatTienKhachDua();
}

// ===== Tiền khách đưa / tiền thối =====

function docGiaTriTien(value) {
    const digits = String(value ?? '').replace(/\D/g, '');
    if (!digits) return 0;
    const amount = Number(digits);
    return Number.isSafeInteger(amount) ? amount : 0;
}

function dinhDangONhapTien(input) {
    if (!input) return 0;
    const raw = String(input.value || '');
    const amount = docGiaTriTien(raw);
    input.value = raw.replace(/\D/g, '') ? dinhDangSoPOS(amount) : '';
    return amount;
}

function datGiaTriTien(inputId, amount) {
    const input = document.getElementById(inputId);
    if (!input) return;
    input.value = dinhDangSoPOS(Math.max(0, Math.round(Number(amount) || 0)));
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.focus();
}

function renderCashQuickAmounts() {
    const box = document.getElementById('cashQuickAmounts');
    if (!box) return;
    const canThu = Math.max(0, Math.round(Number(total) || 0));
    const moc = [
        canThu,
        Math.ceil(canThu / 50000) * 50000,
        Math.ceil(canThu / 100000) * 100000,
        Math.ceil(canThu / 500000) * 500000
    ];
    const amounts = [...new Set(moc)].filter(n => n >= canThu).slice(0, 4);
    if (!amounts.length) amounts.push(0);
    box.innerHTML = amounts.map((amount, index) => `
        <button type="button" onclick="datTienKhachDua(${amount})">
            ${index === 0 ? dichHtml('pos.cash.enough') : ''}${escapeHtml(dinhDangTien(amount))}
        </button>`).join('');
}

function datTienKhachDua(amount) {
    datGiaTriTien('cashTenderedInput', amount);
}

function capNhatTienKhachDua() {
    const input = document.getElementById('cashTenderedInput');
    cashTenderedAmount = input ? docGiaTriTien(input.value) : 0;
    if (pendingCheckoutState?.payment_method === 'cash') {
        pendingCheckoutState.tendered_amount = cashTenderedAmount;
        luuCheckoutDangDo(pendingCheckoutState);
    }
    const status = document.getElementById('cashChangeStatus');
    const output = document.getElementById('txtCashChange');
    if (!status || !output) return capNhatNutCheckout();

    const change = cashTenderedAmount - total;
    status.classList.toggle('is-short', paymentMethod === 'cash' && change < 0);
    if (paymentMethod === 'cash' && change < 0) {
        status.firstElementChild.innerText = dich('pos.cash.remaining');
        output.innerText = dinhDangTien(Math.abs(change));
    } else {
        status.firstElementChild.innerText = dich('pos.cash.change');
        output.innerText = dinhDangTien(Math.max(0, change));
    }
    capNhatNutCheckout();
}

function capNhatNutCheckout() {
    const button = document.getElementById('btnCheckout');
    if (!button) return;
    const pendingNotice = document.getElementById('cashPendingNotice');
    const pendingText = document.getElementById('cashPendingText');
    if (pendingNotice) pendingNotice.style.display = pendingCashOrderId ? 'block' : 'none';
    if (pendingText && pendingCashOrderId) {
        pendingText.innerText = dich('pos.cash.pending_order', { id: pendingCashOrderId });
    }
    const thieuTien = paymentMethod === 'cash' && cashTenderedAmount < total;
    const donQRDangCho = currentOrderId !== null && !pendingCashOrderId;
    button.disabled = checkoutBusy || !activeShift || cart.length === 0 || thieuTien || donQRDangCho;
    button.innerHTML = pendingCashOrderId
        ? htmlNut('ph-arrow-clockwise', 'pos.checkout.retry_cash')
        : (checkoutOperationId
            ? htmlNut('ph-arrow-clockwise', 'pos.checkout.retry_create')
            : htmlNut('ph-check-circle', 'pos.checkout.complete'));
    if (!activeShift) button.title = dich('pos.checkout.open_shift_title');
    else if (cart.length === 0) button.title = dich('pos.cart.empty');
    else if (thieuTien) button.title = dich('pos.checkout.cash_short_title');
    else if (donQRDangCho) button.title = dich('pos.checkout.waiting_title');
    else button.title = '';
}

function taoTrangThaiCheckout(body) {
    const customerText = selectedCustomerId !== null
        ? document.getElementById('khachDaChon')?.innerText || ''
        : '';
    return luuCheckoutDangDo({
        phase: 'creating',
        shop_id: currentShopId,
        operation_id: body.operation_id,
        order_id: null,
        create_payload: JSON.parse(JSON.stringify(body)),
        payment_method: paymentMethod,
        tendered_amount: cashTenderedAmount,
        confirmed_total: Number(total) || 0,
        server_total: null,
        server_total_confirmed: false,
        cart: cart.map(item => ({ ...item })),
        subtotal: Number(subtotal) || 0,
        discount: Number(discount) || 0,
        total: Number(total) || 0,
        voucher_code: currentVoucher,
        selected_customer_id: selectedCustomerId,
        selected_customer_text: customerText,
        qr_url: null
    });
}

function phucHoiCheckoutDangDo() {
    const state = pendingCheckoutState || docCheckoutDangDo();
    if (!state || Number(state.shop_id) !== Number(currentShopId)) return false;
    if (!['creating', 'cash_pending', 'transfer_pending'].includes(state.phase)) return false;

    pendingCheckoutState = state;
    checkoutOperationId = state.phase === 'creating' ? state.operation_id : null;
    currentOrderId = state.order_id ? Number(state.order_id) : null;
    pendingCashOrderId = state.phase === 'cash_pending' && currentOrderId
        ? currentOrderId
        : null;

    const restoredCart = Array.isArray(state.cart) && state.cart.length
        ? state.cart
        : (state.create_payload?.items || []).map(item => ({
            ...item,
            max_stock: Number.MAX_SAFE_INTEGER
        }));
    cart = restoredCart.map(item => ({ ...item }));
    currentVoucher = state.voucher_code || null;
    selectedCustomerId = state.selected_customer_id ?? null;
    subtotal = Number(state.subtotal);
    if (!Number.isFinite(subtotal)) {
        subtotal = cart.reduce((sum, item) => sum + Number(item.price || 0) * Number(item.quantity || 0), 0);
    }
    discount = Number(state.discount) || 0;
    const restoredTotal = state.server_total ?? state.total ?? state.confirmed_total;
    total = Number.isFinite(Number(restoredTotal)) ? Number(restoredTotal) : Math.max(0, subtotal - discount);
    cashTenderedAmount = Number(state.tendered_amount) || 0;

    const voucherInput = document.getElementById('voucherInput');
    if (voucherInput) voucherInput.value = currentVoucher || '';
    const cashInput = document.getElementById('cashTenderedInput');
    if (cashInput) {
        cashInput.value = cashTenderedAmount
            ? dinhDangSoPOS(cashTenderedAmount)
            : '';
    }
    if (selectedCustomerId !== null) {
        const selected = document.getElementById('khachDaChon');
        if (selected) {
            selected.removeAttribute('data-i18n');
            selected.innerText = state.selected_customer_text
                || dich('pos.customer.numbered', { id: selectedCustomerId });
        }
        const chooser = document.getElementById('khachChuaChon');
        const clearButton = document.getElementById('khachBoChon');
        if (chooser) chooser.style.display = 'none';
        if (clearButton) clearButton.style.display = 'block';
    }

    apDungPhuongThucThanhToan(state.payment_method === 'cash' ? 'cash' : 'transfer');
    updateUI();

    if (state.phase === 'transfer_pending' && currentOrderId) {
        if (state.qr_url) document.getElementById('qrImage').src = state.qr_url;
        document.getElementById('qrTotalTxt').innerText = dinhDangTien(state.server_total ?? total);
        document.getElementById('qrSection').style.display = 'block';
        startPaymentPolling();
        showToast(dich('pos.payment.restored_transfer', { id: currentOrderId }));
    } else if (state.phase === 'cash_pending' && currentOrderId) {
        showToast(dich('pos.payment.restored_cash', { id: currentOrderId }));
    } else {
        showToast(dich('pos.payment.restored_unknown'));
    }
    capNhatNutCheckout();
    return true;
}

// ===== Ca làm việc và sổ tiền mặt =====

function taoOperationId() {
    if (window.crypto && typeof window.crypto.randomUUID === 'function') {
        return window.crypto.randomUUID();
    }
    return `${Date.now()}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`;
}

function capNhatThanhCa(state = activeShift ? 'open' : 'closed', message = '') {
    shiftBarState = state;
    shiftBarMessage = message;
    const bar = document.getElementById('shiftBar');
    const text = document.getElementById('shiftStatusText');
    const meta = document.getElementById('shiftStatusMeta');
    const openButton = document.getElementById('btnOpenShift');
    const movementButton = document.getElementById('btnCashMovement');
    const closeButton = document.getElementById('btnCloseShift');
    if (!bar || !text || !meta) return;

    bar.classList.remove('is-loading', 'is-open', 'is-closed', 'is-error');
    bar.classList.add(`is-${state}`);

    if (state === 'loading') {
        text.innerText = dich('pos.shift.checking');
        meta.innerText = dich('pos.shift.server_status');
        openButton.style.display = 'none';
        movementButton.style.display = 'none';
        closeButton.style.display = 'none';
    } else if (state === 'open' && activeShift) {
        const nguoiMo = activeShift.opened_by_username
            || localStorage.getItem('username')
            || dich('pos.shift.employee');
        text.innerText = dich('pos.shift.opened', { id: activeShift.id });
        meta.innerText = dich('pos.shift.opened_meta', {
            username: nguoiMo,
            time: dinhDangNgayGio(activeShift.opened_at)
        });
        openButton.style.display = 'none';
        movementButton.style.display = '';
        closeButton.style.display = '';
    } else if (state === 'error') {
        text.innerText = dich('pos.shift.unknown');
        meta.innerText = message || dich('pos.shift.connection_help');
        openButton.style.display = 'none';
        movementButton.style.display = 'none';
        closeButton.style.display = 'none';
    } else {
        text.innerText = dich('pos.shift.not_open');
        meta.innerText = dich('pos.shift.not_open_help');
        openButton.style.display = '';
        movementButton.style.display = 'none';
        closeButton.style.display = 'none';
    }
    capNhatNutCheckout();
}

async function loadCurrentShift(hienLoi = true) {
    if (!currentShopId) {
        activeShift = null;
        capNhatThanhCa('closed');
        return null;
    }
    const requestId = ++shiftRequestId;
    capNhatThanhCa('loading');
    try {
        const res = await apiCall(`/shifts/current/${currentShopId}`);
        if (requestId !== shiftRequestId) return activeShift;
        activeShift = res?.shift || null;
        capNhatThanhCa(activeShift ? 'open' : 'closed');
        return activeShift;
    } catch (e) {
        if (requestId !== shiftRequestId) return activeShift;
        activeShift = null;
        capNhatThanhCa('error', e.message);
        if (hienLoi) showToast(e.message || dich('pos.shift.load_error'));
        return null;
    }
}

let modalCaFocusTruoc = null;

function hienModalCa(modalId, focusId) {
    const modal = document.getElementById(modalId);
    if (!modal) return;
    modalCaFocusTruoc = document.activeElement;
    modal.style.display = 'flex';
    document.body.classList.add('pos-modal-open');
    setTimeout(() => document.getElementById(focusId)?.focus(), 0);
}

function dongModalCa(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) modal.style.display = 'none';
    const conModalMo = [...document.querySelectorAll('.pos-modal')]
        .some(el => el.style.display === 'flex');
    if (!conModalMo) document.body.classList.remove('pos-modal-open');
    if (modalCaFocusTruoc && typeof modalCaFocusTruoc.focus === 'function') {
        modalCaFocusTruoc.focus();
    }
    modalCaFocusTruoc = null;
}

function datNutDangXuLy(buttonId, dangXuLy, translationKey = 'pos.processing') {
    const button = document.getElementById(buttonId);
    if (!button) return;
    if (dangXuLy) {
        if (!button.dataset.processingKey) button.dataset.normalHtml = button.innerHTML;
        button.dataset.processingKey = translationKey;
        button.innerHTML = htmlNut('ph-spinner-gap ph-spin', translationKey);
        button.disabled = true;
    } else {
        if (button.dataset.normalHtml) {
            button.innerHTML = button.dataset.normalHtml;
            window.FSellingI18n?.apply?.(button);
        }
        delete button.dataset.processingKey;
        delete button.dataset.normalHtml;
        button.disabled = false;
    }
}

function moModalMoCa() {
    if (!currentShopId) return showToast(dich('pos.shift.select_shop'));
    if (activeShift) return showToast(dich('pos.shift.already_open'));
    document.getElementById('openingCashInput').value = '0';
    document.getElementById('openingShiftNote').value = '';
    hienModalCa('openShiftModal', 'openingCashInput');
}

async function moCa() {
    if (!currentShopId || activeShift) return;
    const openingCash = docGiaTriTien(document.getElementById('openingCashInput').value);
    const note = document.getElementById('openingShiftNote').value.trim();
    datNutDangXuLy('btnSubmitOpenShift', true, 'pos.shift.opening');
    try {
        activeShift = await apiCall(`/shifts/${currentShopId}/open`, 'POST', {
            opening_cash_amount: openingCash,
            note: note || null
        });
        dongModalCa('openShiftModal');
        capNhatThanhCa('open');
        showToast(dich('pos.shift.opened_success', { id: activeShift.id }));
    } catch (e) {
        showToast(e.message);
        // Nếu phản hồi bị mất sau khi server đã mở ca, lần tải này lấy lại đúng
        // ca server-side thay vì để người dùng tưởng chưa mở.
        await loadCurrentShift(false);
        if (activeShift) dongModalCa('openShiftModal');
    } finally {
        datNutDangXuLy('btnSubmitOpenShift', false);
    }
}

function chonLoaiThuChi(type, persistDraft = true) {
    movementType = type === 'PAY_OUT' ? 'PAY_OUT' : 'PAY_IN';
    document.getElementById('btnMovementIn').classList.toggle('active', movementType === 'PAY_IN');
    document.getElementById('btnMovementOut').classList.toggle('active', movementType === 'PAY_OUT');
    document.getElementById('movementNote').placeholder =
        dich(movementType === 'PAY_IN' ? 'pos.movement.note_in' : 'pos.movement.note_out');
    if (persistDraft) capNhatMovementDraft();
}

function khoaFormMovement(locked) {
    document.getElementById('btnMovementIn').disabled = locked;
    document.getElementById('btnMovementOut').disabled = locked;
    document.getElementById('movementAmountInput').disabled = locked;
    document.getElementById('movementNote').disabled = locked;
    const submit = document.getElementById('btnSubmitMovement');
    if (submit && !submit.disabled) {
        submit.innerHTML = locked
            ? htmlNut('ph-arrow-clockwise', 'pos.movement.retry_exact')
            : htmlNut('ph-check-circle', 'pos.movement.record');
    }
}

function capNhatMovementDraft() {
    if (!activeShift || pendingMovementState?.submitted) return;
    if (!pendingMovementState) {
        pendingMovementState = {
            shift_id: activeShift.id,
            operation_id: movementOperationId || taoOperationId(),
            submitted: false,
            draft: {}
        };
    }
    movementOperationId = pendingMovementState.operation_id;
    pendingMovementState.draft = {
        movement_type: movementType,
        amount: docGiaTriTien(document.getElementById('movementAmountInput')?.value),
        note: document.getElementById('movementNote')?.value.trim() || ''
    };
    luuMovementDangDo(pendingMovementState);
}

function moModalThuChi() {
    if (!activeShift) return showToast(dich('pos.shift.open_before_movement'));
    pendingMovementState = docMovementDangDo(activeShift.id);
    if (!pendingMovementState) {
        pendingMovementState = luuMovementDangDo({
            shift_id: activeShift.id,
            operation_id: taoOperationId(),
            submitted: false,
            draft: { movement_type: 'PAY_IN', amount: 0, note: '' },
            payload: null
        });
    }
    movementOperationId = pendingMovementState.operation_id;
    const values = pendingMovementState.submitted
        ? pendingMovementState.payload
        : pendingMovementState.draft;
    movementType = values?.movement_type === 'PAY_OUT' ? 'PAY_OUT' : 'PAY_IN';
    document.getElementById('movementAmountInput').value =
        Number(values?.amount) > 0 ? dinhDangSoPOS(values.amount) : '';
    document.getElementById('movementNote').value = values?.note || '';
    chonLoaiThuChi(movementType, false);
    khoaFormMovement(Boolean(pendingMovementState.submitted));
    hienModalCa('cashMovementModal', 'movementAmountInput');
}

async function ghiNhanThuChi() {
    if (!activeShift) return showToast(dich('pos.shift.closed_or_missing'));
    let state = pendingMovementState || docMovementDangDo(activeShift.id);
    let payload = state?.submitted ? state.payload : null;
    if (!payload) {
        const amountInput = document.getElementById('movementAmountInput');
        const amount = docGiaTriTien(amountInput.value);
        const note = document.getElementById('movementNote').value.trim();
        if (amount <= 0) {
            amountInput.focus();
            return showToast(dich('pos.movement.amount_required'));
        }
        if (!note) {
            document.getElementById('movementNote').focus();
            return showToast(dich('pos.movement.reason_required'));
        }
        if (!state) {
            state = {
                shift_id: activeShift.id,
                operation_id: movementOperationId || taoOperationId()
            };
        }
        payload = {
            movement_type: movementType,
            amount,
            note,
            operation_id: state.operation_id
        };
        // Từ thời điểm request đầu tiên rời browser, payload bị khóa. Nếu response
        // mất, retry bắt buộc gửi lại đúng cả operation_id lẫn nội dung.
        state = luuMovementDangDo({
            ...state,
            submitted: true,
            payload,
            draft: { movement_type: movementType, amount, note }
        });
    }
    pendingMovementState = state;
    movementOperationId = state.operation_id;
    khoaFormMovement(true);
    datNutDangXuLy('btnSubmitMovement', true, 'pos.movement.recording');
    try {
        const res = await apiCall(`/shifts/${state.shift_id}/movements`, 'POST', payload);
        if (res?.shift) activeShift = res.shift;
        dongModalCa('cashMovementModal');
        capNhatThanhCa('open');
        showToast(dich(
            payload.movement_type === 'PAY_IN'
                ? 'pos.movement.in_success'
                : 'pos.movement.out_success',
            { amount: dinhDangTien(payload.amount) }
        ));
        xoaMovementDangDo(state);
    } catch (e) {
        if (laLoi4xx(e)) {
            // 4xx là kết quả xác định: server đã từ chối payload này. Xóa op cũ
            // để người dùng sửa và gửi một thao tác mới.
            xoaMovementDangDo(state);
            khoaFormMovement(false);
            showToast(dich('pos.movement.fix_retry', { message: e.message }));
        } else {
            // Network/5xx: không biết server đã commit chưa, nên giữ nguyên state
            // và khóa form cho tới khi retry cùng payload trả về kết quả rõ ràng.
            pendingMovementState = state;
            luuMovementDangDo(state);
            showToast(dich('pos.movement.network_retry', { message: e.message }));
        }
        await loadCurrentShift(false);
    } finally {
        datNutDangXuLy('btnSubmitMovement', false);
        khoaFormMovement(Boolean(pendingMovementState?.submitted));
    }
}

async function moModalKetCa() {
    if (!activeShift) return showToast(dich('pos.shift.no_open_shift'));
    const movementDangDo = docMovementDangDo(activeShift.id);
    if (movementDangDo?.submitted) {
        return showToast(dich('pos.shift.finish_movement_first'));
    }
    if (cart.length > 0 || currentOrderId) {
        return showToast(dich('pos.shift.finish_order_first'));
    }
    await loadCurrentShift(false);
    if (!activeShift) return showToast(dich('pos.shift.unavailable'));

    document.getElementById('closeOpeningCash').innerText =
        dinhDangTien(activeShift.opening_cash_amount || 0);
    document.getElementById('closeExpectedCash').innerText =
        Number.isFinite(Number(activeShift.expected_cash_amount))
            ? dinhDangTien(activeShift.expected_cash_amount)
            : '—';
    document.getElementById('actualCashInput').value = '';
    document.getElementById('closingShiftNote').value = '';
    capNhatChenhLechKetCa();
    hienModalCa('closeShiftModal', 'actualCashInput');
}

function capNhatChenhLechKetCa() {
    const input = document.getElementById('actualCashInput');
    const box = document.getElementById('closeDifference');
    if (!input || !box) return;
    const coNhap = /\d/.test(input.value);
    const expected = Number(activeShift?.expected_cash_amount);
    if (!coNhap || !Number.isFinite(expected)) {
        box.className = 'shift-difference neutral';
        box.innerText = dich(
            coNhap ? 'pos.shift.close_no_expected' : 'pos.shift.close_count_prompt'
        );
        return;
    }
    const counted = docGiaTriTien(input.value);
    const variance = counted - expected;
    if (variance === 0) {
        box.className = 'shift-difference';
        box.innerText = dich('pos.shift.close_match');
    } else if (variance < 0) {
        box.className = 'shift-difference is-short';
        box.innerText = dich('pos.shift.close_short', {
            amount: dinhDangTien(Math.abs(variance))
        });
    } else {
        box.className = 'shift-difference';
        box.innerText = dich('pos.shift.close_over', {
            amount: dinhDangTien(variance)
        });
    }
}

async function ketCa() {
    if (!activeShift) return showToast(dich('pos.shift.closed_or_missing'));
    const input = document.getElementById('actualCashInput');
    if (!/\d/.test(input.value)) {
        input.focus();
        return showToast(dich('pos.shift.close_enter_counted'));
    }
    const counted = docGiaTriTien(input.value);
    const expected = Number(activeShift.expected_cash_amount);
    const noteEl = document.getElementById('closingShiftNote');
    const note = noteEl.value.trim();
    if (Number.isFinite(expected) && counted !== expected && !note) {
        noteEl.focus();
        return showToast(dich('pos.shift.close_note_required'));
    }

    datNutDangXuLy('btnSubmitCloseShift', true, 'pos.shift.closing');
    try {
        const closedShift = await apiCall(`/shifts/${activeShift.id}/close`, 'POST', {
            counted_cash_amount: counted,
            note: note || null
        });
        const variance = Number(closedShift?.variance_amount || 0);
        activeShift = null;
        dongModalCa('closeShiftModal');
        capNhatThanhCa('closed');
        showToast(
            variance === 0
                ? dich('pos.shift.closed_match')
                : dich('pos.shift.closed_variance', {
                    kind: dich(variance < 0
                        ? 'pos.shift.variance_short'
                        : 'pos.shift.variance_over'),
                    amount: dinhDangTien(Math.abs(variance))
                })
        );
    } catch (e) {
        showToast(e.message);
        await loadCurrentShift(false);
        if (!activeShift) dongModalCa('closeShiftModal');
    } finally {
        datNutDangXuLy('btnSubmitCloseShift', false);
    }
}

/**
 * Hộp xác nhận dựng trong trang, trả về Promise<boolean>.
 *
 * Thay cho `confirm()` của trình duyệt. Chrome cho phép người dùng tick "chặn
 * hộp thoại của trang này" sau vài lần hiện liên tiếp; từ lúc đó `confirm()`
 * trả về false ngay lập tức mà không hiện gì. Với nút Hoàn tất đơn hàng thì
 * hậu quả là bấm mãi không ra đơn, không ra QR, không cả báo lỗi.
 */
function xacNhan(tieuDe, noiDung) {
    return new Promise(resolve => {
        const modal = document.getElementById('xacNhanModal');
        const nutOk = document.getElementById('xnDongY');
        const nutHuy = document.getElementById('xnHuy');
        document.getElementById('xnTieuDe').innerText = tieuDe;
        document.getElementById('xnNoiDung').innerText = noiDung;
        modal.style.display = 'flex';

        const dong = (ketQua) => {
            modal.style.display = 'none';
            nutOk.onclick = null;
            nutHuy.onclick = null;
            modal.onclick = null;
            document.removeEventListener('keydown', khiNhanPhim);
            resolve(ketQua);
        };
        const khiNhanPhim = (e) => { if (e.key === 'Escape') dong(false); };

        nutOk.onclick = () => dong(true);
        nutHuy.onclick = () => dong(false);
        modal.onclick = (e) => { if (e.target === modal) dong(false); };
        document.addEventListener('keydown', khiNhanPhim);
        nutOk.focus();
    });
}

let paymentPollingInterval = null;

async function xacNhanTongTienServer(state) {
    const daXacNhan = Math.round(Number(state.confirmed_total) || 0);
    const serverTotal = Math.round(Number(state.server_total) || 0);
    if (daXacNhan === serverTotal) {
        state.server_total_confirmed = true;
        luuCheckoutDangDo(state);
        return true;
    }
    if (state.server_total_confirmed === true) return true;

    const tendered = Number(state.tendered_amount) || 0;
    const chenhlech = tendered - serverTotal;
    const dongY = await xacNhan(
        dich('pos.checkout.server_total_changed', {
            defaultValue: 'Tổng tiền trên server đã thay đổi'
        }),
        dich('pos.checkout.server_total_body', {
            confirmed: dinhDangTien(daXacNhan),
            actual: dinhDangTien(serverTotal),
            tendered: dinhDangTien(tendered),
            differenceLabel: dich(
                chenhlech >= 0 ? 'pos.cash.change' : 'pos.cash.remaining'
            ),
            difference: dinhDangTien(Math.abs(chenhlech))
        })
    );
    if (!dongY) {
        state.server_total_confirmed = false;
        luuCheckoutDangDo(state);
        showToast(dich('pos.checkout.new_total_retained'));
        return false;
    }
    state.server_total_confirmed = true;
    luuCheckoutDangDo(state);
    return true;
}

async function hoanTatTienMatDangCho(state) {
    const idDon = Number(state.order_id);
    if (!idDon) throw new Error(dich('pos.checkout.no_cash_order_id'));

    currentOrderId = idDon;
    pendingCashOrderId = idDon;
    total = Number(state.server_total ?? state.total ?? total) || 0;
    capNhatTienKhachDua();
    state.tendered_amount = cashTenderedAmount;
    luuCheckoutDangDo(state);

    if (!await xacNhanTongTienServer(state)) return false;
    if (cashTenderedAmount < total) {
        document.getElementById('cashTenderedInput')?.focus();
        showToast(dich('pos.checkout.customer_short', {
            amount: dinhDangTien(total - cashTenderedAmount)
        }));
        return false;
    }

    await apiCall(`/orders/${idDon}/pay`, 'POST', {
        tendered_amount: cashTenderedAmount
    });
    // Pay đã trả success (kể cả idempotent "đã PAID"): từ đây mới được xóa
    // state durable của tab.
    xoaCheckoutDangDo();
    pendingCashOrderId = null;
    showToast(dich('pos.checkout.cash_success', {
        amount: dinhDangTien(cashTenderedAmount - total)
    }));
    await hienHoaDon(idDon);
    return true;
}

async function guiYeuCauTaoDonDangDo(state) {
    const res = await apiCall(
        `/orders/${state.shop_id}`,
        'POST',
        state.create_payload
    );
    checkoutOperationId = null;
    currentOrderId = Number(res.order_id);
    state.order_id = currentOrderId;
    state.server_total = Number.isFinite(Number(res.total))
        ? Number(res.total)
        : Number(state.total) || 0;

    if (state.payment_method === 'transfer') {
        state.phase = 'transfer_pending';
        state.qr_url = res.qr_url || state.qr_url || null;
        luuCheckoutDangDo(state);
        if (state.qr_url) document.getElementById('qrImage').src = state.qr_url;
        document.getElementById('qrTotalTxt').innerText = dinhDangTien(state.server_total);
        document.getElementById('qrSection').style.display = 'block';
        showToast(dich('pos.checkout.created_transfer'));
        DocTien.chuanBiSoTien(res.total);
        startPaymentPolling();
        return;
    }

    state.phase = 'cash_pending';
    state.server_total_confirmed =
        Math.round(Number(state.confirmed_total) || 0) === Math.round(state.server_total);
    pendingCashOrderId = currentOrderId;
    total = state.server_total;
    luuCheckoutDangDo(state);
    document.getElementById('txtTotal').innerText = dinhDangTien(total);
    renderCashQuickAmounts();
    capNhatTienKhachDua();
    await hoanTatTienMatDangCho(state);
}

async function thuTaoDonDangDo(state) {
    if (!state || state.phase !== 'creating' || checkoutBusy) return;
    checkoutOperationId = state.operation_id;
    checkoutBusy = true;
    capNhatNutCheckout();
    try {
        await guiYeuCauTaoDonDangDo(state);
    } catch (e) {
        if (!currentOrderId && laLoi4xx(e)) {
            // POST create trả 4xx: server xác định không tạo đơn, nên có thể bỏ
            // operation cũ và cho sửa giỏ. Network/5xx phải giữ exact payload.
            checkoutOperationId = null;
            xoaCheckoutDangDo();
        } else if (!currentOrderId) {
            luuCheckoutDangDo(state);
        }
        showToast(e.message);
    } finally {
        checkoutBusy = false;
        capNhatNutCheckout();
    }
}

async function checkout() {
    if (checkoutBusy) return;
    if (pendingCashOrderId) return thuTienMatDonDangCho();
    if (checkoutOperationId) {
        if (!activeShift) {
            showToast(dich('pos.checkout.open_shift_retry'));
            return moModalMoCa();
        }
        const state = pendingCheckoutState || docCheckoutDangDo();
        return thuTaoDonDangDo(state);
    }
    if (currentOrderId) return showToast(dich('pos.checkout.order_exists'));
    if(cart.length === 0) return showToast(dich('pos.checkout.empty_cart'));
    if(!activeShift) {
        showToast(dich('pos.checkout.open_shift_first'));
        return moModalMoCa();
    }
    capNhatTienKhachDua();
    if (paymentMethod === 'cash' && cashTenderedAmount < total) {
        document.getElementById('cashTenderedInput')?.focus();
        return showToast(dich('pos.checkout.customer_short', {
            amount: dinhDangTien(total - cashTenderedAmount)
        }));
    }

    // Xác nhận trước khi chốt. Tạo đơn là TRỪ TỒN KHO ngay, và với tiền mặt còn
    // thu tiền luôn - không có bước quay lại. Khi quét mã vạch, quét thừa một
    // món rất dễ xảy ra mà danh sách lại cuộn nên khó thấy, nên bắt buộc phải
    // có một lần đối chiếu tổng số món và tổng tiền bằng mắt.
    const soMon = cart.reduce((n, i) => n + i.quantity, 0);
    const tenPTTT = dich(
        paymentMethod === 'cash' ? 'pos.payment.cash' : 'pos.payment.transfer'
    );
    const dongTomTat = cart
        .map(i => `  ${i.product_name}  ${dinhDangTien(i.price)} × ${dinhDangSoPOS(i.quantity)}`)
        .join('\n');
    const tomTatTienMat = paymentMethod === 'cash'
        ? dich('pos.checkout.confirm_cash', {
            tendered: dinhDangTien(cashTenderedAmount),
            change: dinhDangTien(cashTenderedAmount - total)
        })
        : '';
    const dongY = await xacNhan(
        dich('pos.checkout.confirm_title', {
            lineCount: cart.length,
            itemCount: soMon
        }),
        dich('pos.checkout.confirm_body', {
            items: dongTomTat,
            total: dinhDangTien(total),
            method: tenPTTT,
            cashSummary: tomTatTienMat
        })
    );
    if (!dongY) return;

    const body = {
        // Gửi kèm product_name để hóa đơn/log vẫn đọc được nếu cần đối chiếu,
        // nhưng server định danh sản phẩm bằng product_id.
        items: cart.map(i => ({product_id: i.product_id, product_name: i.product_name, price: i.price, quantity: i.quantity})),
        voucher_code: currentVoucher,
        payment_method: paymentMethod,
        operation_id: taoOperationId()
    };
    if(selectedCustomerId !== null) body.customer_id = selectedCustomerId;
    checkoutOperationId = body.operation_id;
    const state = taoTrangThaiCheckout(body);
    await thuTaoDonDangDo(state);
}

async function thuTienMatDonDangCho() {
    if (!pendingCashOrderId || checkoutBusy) return;
    if (!activeShift) return showToast(dich('pos.shift.closed_or_missing'));
    const state = pendingCheckoutState || docCheckoutDangDo();
    if (!state || state.phase !== 'cash_pending') {
        return showToast(dich('pos.checkout.cash_state_missing'));
    }
    checkoutBusy = true;
    capNhatNutCheckout();
    try {
        await hoanTatTienMatDangCho(state);
    } catch (e) {
        if (Number(e.status) === 404) {
            // 404 xác định đơn không còn tồn tại; bỏ state nhưng giữ giỏ để có
            // thể tạo lại sau khi người dùng kiểm tra.
            xoaCheckoutDangDo();
            currentOrderId = null;
            pendingCashOrderId = null;
            checkoutOperationId = null;
            showToast(dich('pos.checkout.order_missing_recreate', {
                message: e.message
            }));
        } else {
            // Các 4xx khác vẫn có thể là đơn PENDING hợp lệ (ca đóng, chưa đủ
            // tiền...). Giữ order_id để người dùng thu hoặc hủy đúng đơn đó.
            luuCheckoutDangDo(state);
            showToast(
                laLoi4xx(e)
                    ? e.message
                    : dich('pos.checkout.retry_cash_hint', { message: e.message })
            );
        }
    } finally {
        checkoutBusy = false;
        capNhatNutCheckout();
    }
}

async function cancelOrder() {
    if(!currentOrderId) return;
    const idDon = currentOrderId;
    const dongY = await xacNhan(
        dich('pos.order.cancel_title', { id: idDon }),
        dich('pos.order.cancel_body')
    );
    if (!dongY) return;
    try {
        const res = await apiCall(`/orders/${idDon}/cancel`, 'POST');
        stopPaymentPolling();
        if(res.unrestored_items > 0) {
            showToast(dich('pos.order.cancel_partial', {
                count: res.unrestored_items
            }));
        } else {
            showToast(dich('pos.order.cancel_success'));
        }
        resetPOS();
    } catch (e) {
        if (Number(e.status) === 404 && idDon === currentOrderId) {
            // Kết quả xác định: order không còn tồn tại. Bỏ khóa durable nhưng
            // giữ giỏ hiện tại để thu ngân có thể kiểm tra và tạo lại.
            stopPaymentPolling();
            xoaCheckoutDangDo();
            currentOrderId = null;
            pendingCashOrderId = null;
            checkoutOperationId = null;
            document.getElementById('qrSection').style.display = 'none';
            capNhatNutCheckout();
            return showToast(dich('pos.order.no_longer_exists', {
                message: e.message
            }));
        }
        showToast(e.message);
    }
}

function startPaymentPolling() {
    stopPaymentPolling();
    kiemTraThanhToan();
    paymentPollingInterval = setInterval(kiemTraThanhToan, 5000);
}

async function kiemTraThanhToan() {
    if(!currentOrderId) return stopPaymentPolling();
    const idDon = currentOrderId;
    try {
        const statusRes = await apiCall(`/orders/${idDon}`);
        if(idDon !== currentOrderId) return;
        lastPaymentStatus = statusRes;

        if(statusRes.status === 'PAID') {
            stopPaymentPolling();
            // Đọc TRƯỚC khi vẽ hóa đơn. Nếu chuyển thừa, vẫn xuất hóa đơn ngay
            // nhưng lời cảnh báo nêu rõ số cần hoàn.
            if(statusRes.refund_pending) {
                DocTien.canhBaoThuaTien(
                    idDon,
                    statusRes.received_amount,
                    statusRes.refund_due_amount
                );
                showToast(dich('pos.payment.overpaid', {
                    amount: dinhDangTien(statusRes.refund_due_amount)
                }));
            } else {
                DocTien.thongBaoDaNhan(
                    idDon,
                    statusRes.received_amount || statusRes.total_amount
                );
                showToast(dich('pos.payment.transfer_success'));
            }
            await hienHoaDon(idDon);
        } else if(statusRes.status === 'CANCELLED') {
            stopPaymentPolling();
            showToast(dich('pos.payment.cancelled'));
            resetPOS();
        } else if(statusRes.status === 'UNRECONCILED') {
            renderPaymentStatus(statusRes);
            if(statusRes.reconciliation_reason === 'UNDERPAID') {
                // Không dừng polling và không dọn QR: khách có thể chuyển thêm,
                // hoặc nhân viên thu đúng phần còn thiếu bằng tiền mặt.
                const noticeKey = `UNDER:${idDon}:${Math.round(statusRes.received_amount || 0)}`;
                if(lastPaymentNoticeKey !== noticeKey) {
                    lastPaymentNoticeKey = noticeKey;
                    DocTien.canhBaoThieuTien(
                        idDon,
                        statusRes.received_amount,
                        statusRes.remaining_amount
                    );
                    showToast(dich('pos.payment.underpaid', {
                        amount: dinhDangTien(statusRes.remaining_amount)
                    }));
                }
            } else {
                stopPaymentPolling();
                showToast(dich('pos.payment.review_required'));
            }
        }
    } catch (err) {
        console.error('Polling lỗi:', err);
    }
}

function dinhDangTien(value) {
    if (window.FSellingI18n?.formatMoney) {
        return window.FSellingI18n.formatMoney(Math.round(Number(value) || 0));
    }
    return `${Math.round(Number(value) || 0).toLocaleString('vi-VN')} ₫`;
}

function renderPaymentStatus(statusRes) {
    lastPaymentStatus = statusRes;
    const box = document.getElementById('paymentStatusBox');
    const title = document.getElementById('paymentStatusTitle');
    const cashButton = document.getElementById('btnCashTopup');
    const cancelButton = document.getElementById('btnCancelOrder');
    if(!box || !title || !cashButton) return;

    box.style.display = 'block';
    document.getElementById('paymentReceived').innerText = dinhDangTien(statusRes.received_amount);
    document.getElementById('paymentRemaining').innerText = dinhDangTien(statusRes.remaining_amount);

    if(statusRes.reconciliation_reason === 'UNDERPAID') {
        title.innerText = dich('pos.payment.underpaid_title');
        cashButton.style.display = 'block';
        cashButton.innerHTML = htmlNut(
            'ph-money',
            'pos.payment.cash_topup_amount',
            { amount: dinhDangTien(statusRes.remaining_amount) }
        );
    } else if(statusRes.reconciliation_reason === 'LATE_PAYMENT') {
        title.innerText = dich('pos.payment.late_title', {
            amount: dinhDangTien(statusRes.refund_due_amount)
        });
        cashButton.style.display = 'none';
    } else {
        title.innerText = dich('pos.payment.review_title');
        cashButton.style.display = 'none';
    }

    // Khi tiền đã vào thì backend cũng không cho hủy để tránh hoàn kho sai.
    if(cancelButton) {
        cancelButton.disabled = Number(statusRes.received_amount || 0) > 0;
        cancelButton.style.opacity = cancelButton.disabled ? '0.45' : '1';
    }
}

async function buTienMatPhanThieu() {
    if(!currentOrderId) return;
    const idDon = currentOrderId;
    try {
        const statusRes = await apiCall(`/orders/${idDon}`);
        if(
            statusRes.status !== 'UNRECONCILED'
            || statusRes.reconciliation_reason !== 'UNDERPAID'
        ) {
            return showToast(dich('pos.payment.no_longer_underpaid'));
        }
        const remaining = Number(statusRes.remaining_amount || 0);
        const dongY = await xacNhan(
            dich('pos.payment.topup_confirm_title', {
                amount: dinhDangTien(remaining)
            }),
            dich('pos.payment.topup_confirm_body', {
                id: idDon,
                received: dinhDangTien(statusRes.received_amount)
            })
        );
        if(!dongY) return;
        const result = await apiCall(
            `/orders/${idDon}/cash-topup`,
            'POST',
            { amount: remaining, note: 'SYSTEM_POS_CASH_TOPUP' }
        );
        if(result.status === 'PAID') {
            stopPaymentPolling();
            showToast(dich('pos.payment.topup_success'));
            await hienHoaDon(idDon);
        } else {
            renderPaymentStatus(result);
        }
    } catch (e) {
        showToast(e.message);
        kiemTraThanhToan();
    }
}

function stopPaymentPolling() {
    if(paymentPollingInterval) {
        clearInterval(paymentPollingInterval);
        paymentPollingInterval = null;
    }
}

// ===== Hóa đơn sau khi thanh toán =====

/**
 * Tải chi tiết đơn rồi hiện hóa đơn trên màn hình.
 *
 * Gọi `resetPOS()` TRƯỚC khi vẽ: reset dọn giỏ hàng và ẩn khối hóa đơn cũ, nên
 * vẽ sau thì tờ hóa đơn vừa tạo mới không bị dọn mất. Quầy cũng sẵn sàng cho
 * khách tiếp theo ngay trong lúc hóa đơn còn hiển thị.
 */
async function hienHoaDon(orderId) {
    if (!orderId) return resetPOS();
    let d = null;
    try {
        d = await apiCall(`/orders/${orderId}/detail`);
    } catch (e) {
        resetPOS();
        return showToast(dich('pos.order.paid_receipt_error', {
            id: orderId,
            message: e.message
        }));
    }
    resetPOS();
    veHoaDon(d);
    document.getElementById('hoaDonSection').style.display = 'block';
}

// Hóa đơn là tài liệu giao cho khách tại Việt Nam nên luôn giữ tiếng Việt,
// kể cả khi nhân viên đang vận hành POS bằng English.
function dinhDangSoHoaDon(value) {
    return Math.round(Number(value) || 0).toLocaleString('vi-VN');
}

function dinhDangTienHoaDon(value) {
    return `${dinhDangSoHoaDon(value)} ₫`;
}

function dinhDangNgayGioHoaDon(value) {
    const date = window.FSellingI18n?.parseServerDate
        ? window.FSellingI18n.parseServerDate(value)
        : null;
    if (date) return date.toLocaleString('vi-VN');
    if (!value) return '';
    let normalized = String(value);
    if (!/(Z|[+-]\d{2}:?\d{2})$/.test(normalized)) normalized += 'Z';
    const fallbackDate = new Date(normalized);
    return Number.isNaN(fallbackDate.getTime())
        ? String(value)
        : fallbackDate.toLocaleString('vi-VN');
}

function veHoaDon(d) {
    // Tên thu ngân và tiền thối lấy từ bản ghi server, không lấy theo tài khoản
    // đang mở trình duyệt (hóa đơn cũ có thể do người khác bán).
    const nhanVien = d.cashier_username || localStorage.getItem('username') || '—';
    const coChuyenKhoan = Number(d.bank_paid_amount || 0) > 0;
    const coTienMat = Number(d.cash_paid_amount || 0) > 0;
    const coTienKhachDua = d.cash_tendered_amount !== null
        && d.cash_tendered_amount !== undefined;
    const pttt = coChuyenKhoan && coTienMat
        ? 'Chuyển khoản + tiền mặt'
        : (coChuyenKhoan ? 'Chuyển khoản' : 'Tiền mặt');

    const dongHang = (d.items || []).map(i => `
        <tr>
            <td style="padding:0.25rem 0;">${escapeHtml(i.product_name)}<br>
                <span style="color:#64748B; font-size:0.8rem;">${dinhDangSoHoaDon(i.price)} × ${i.quantity}</span></td>
            <td style="padding:0.25rem 0; text-align:right; white-space:nowrap; font-weight:600;">${dinhDangTienHoaDon(i.line_total)}</td>
        </tr>`).join('');

    let tongKet = `<div style="display:flex; justify-content:space-between;"><span>Tạm tính</span><span>${dinhDangTienHoaDon(d.subtotal)}</span></div>`;
    if (d.discount_amount > 0) {
        const ma = d.voucher_code ? ` (${escapeHtml(d.voucher_code)})` : '';
        tongKet += `<div style="display:flex; justify-content:space-between; color:#B45309;"><span>Giảm giá${ma}</span><span>- ${dinhDangTienHoaDon(d.discount_amount)}</span></div>`;
    }
    tongKet += `<div style="display:flex; justify-content:space-between; font-size:1.15rem; font-weight:700; margin-top:0.4rem; padding-top:0.4rem; border-top:2px solid #0F172A;"><span>TỔNG CỘNG</span><span>${dinhDangTienHoaDon(d.total_amount)}</span></div>`;
    if (coChuyenKhoan && coTienMat) {
        tongKet += `<div style="display:flex; justify-content:space-between; margin-top:0.35rem;"><span>Qua ngân hàng</span><span>${dinhDangTienHoaDon(d.bank_paid_amount)}</span></div>`;
        tongKet += `<div style="display:flex; justify-content:space-between;"><span>Bù tiền mặt</span><span>${dinhDangTienHoaDon(d.cash_paid_amount)}</span></div>`;
    }
    if (coTienKhachDua) {
        tongKet += `<div style="display:flex; justify-content:space-between; margin-top:0.35rem;"><span>Khách đưa</span><span>${dinhDangTienHoaDon(d.cash_tendered_amount)}</span></div>`;
        tongKet += `<div style="display:flex; justify-content:space-between; color:#047857; font-weight:700;"><span>Tiền thối</span><span>${dinhDangTienHoaDon(d.cash_change_amount || 0)}</span></div>`;
    }
    if (d.refund_pending) {
        tongKet += `<div style="display:flex; justify-content:space-between; color:#B91C1C; font-weight:700; margin-top:0.35rem;"><span>Thực nhận</span><span>${dinhDangTienHoaDon(d.received_amount)}</span></div>`;
        tongKet += `<div style="display:flex; justify-content:space-between; color:#B91C1C; font-weight:700;"><span>CẦN HOÀN KHÁCH</span><span>${dinhDangTienHoaDon(d.refund_due_amount)}</span></div>`;
    }

    const warning = document.getElementById('hoaDonCanhBao');
    if (warning) {
        if (d.refund_pending) {
            warning.style.display = 'block';
            warning.innerText = `ĐÃ XUẤT HÓA ĐƠN — CẦN HOÀN KHÁCH ${dinhDangTienHoaDon(d.refund_due_amount)}`;
        } else {
            warning.style.display = 'none';
            warning.innerText = '';
        }
    }

    document.getElementById('hoaDonNoiDung').innerHTML = `
        <div style="text-align:center; border-bottom:1px dashed #94A3B8; padding-bottom:0.6rem; margin-bottom:0.6rem;">
            <div style="font-weight:700; font-size:1.05rem;">${escapeHtml(d.shop_name || '')}</div>
            <div style="font-size:0.9rem;">HÓA ĐƠN BÁN HÀNG</div>
        </div>
        <div style="font-size:0.85rem; line-height:1.7; margin-bottom:0.6rem;">
            <div><b>Số đơn:</b> #${d.id}</div>
            <div><b>Thời gian:</b> ${dinhDangNgayGioHoaDon(d.created_at)}</div>
            <div><b>Nhân viên:</b> ${escapeHtml(nhanVien)}</div>
            <div><b>Thanh toán:</b> ${pttt}</div>
            ${d.customer ? `<div><b>Khách hàng:</b> ${escapeHtml(d.customer.name)} (${escapeHtml(d.customer.phone)})</div>` : ''}
        </div>
        <table style="width:100%; border-collapse:collapse; font-size:0.88rem; border-top:1px dashed #94A3B8; border-bottom:1px dashed #94A3B8;">
            ${dongHang}
        </table>
        <div style="margin-top:0.6rem; font-size:0.92rem;">${tongKet}</div>
        <div style="text-align:center; margin-top:0.7rem; font-size:0.8rem; color:#64748B;">Cảm ơn quý khách!</div>`;
}

function dongHoaDon() {
    document.getElementById('hoaDonSection').style.display = 'none';
}

function resetPOS() {
    stopPaymentPolling();
    dongHoaDon();
    xoaCheckoutDangDo();
    cart = [];
    currentVoucher = null;
    voucherMessageKey = null;
    voucherMessageRaw = '';
    document.getElementById('voucherInput').value = '';
    document.getElementById('voucherMsg').innerText = '';
    document.getElementById('qrSection').style.display = 'none';
    const paymentStatusBox = document.getElementById('paymentStatusBox');
    const cashTopupButton = document.getElementById('btnCashTopup');
    const cancelButton = document.getElementById('btnCancelOrder');
    if(paymentStatusBox) paymentStatusBox.style.display = 'none';
    if(cashTopupButton) cashTopupButton.style.display = 'none';
    if(cancelButton) {
        cancelButton.disabled = false;
        cancelButton.style.opacity = '1';
    }
    currentOrderId = null;
    pendingCashOrderId = null;
    checkoutOperationId = null;
    cashTenderedAmount = 0;
    const cashInput = document.getElementById('cashTenderedInput');
    if (cashInput) cashInput.value = '';
    lastPaymentNoticeKey = null;
    lastPaymentStatus = null;
    boChonKhach();  // trả về khách vãng lai cho đơn tiếp theo
    calcCart();
    loadProducts(); // refresh stock
}

// ===== C2d: gắn khách hàng vào đơn ở POS =====
function boChonKhach() {
    if (dangKhoaChinhSuaDon()) return;
    selectedCustomerId = null;
    const el = id => document.getElementById(id);
    if (el('khachDaChon')) {
        el('khachDaChon').setAttribute('data-i18n', 'pos.customer.walk_in');
        el('khachDaChon').innerText = dich('pos.customer.walk_in');
    }
    if (el('khachChuaChon')) el('khachChuaChon').style.display = 'block';
    if (el('khachBoChon')) el('khachBoChon').style.display = 'none';
    if (el('posCustResults')) el('posCustResults').innerHTML = '';
    if (el('posCustSearch')) el('posCustSearch').value = '';
    if (el('posCustNewForm')) el('posCustNewForm').style.display = 'none';
}

function chonKhach(id, ten, sdt) {
    if (dangKhoaChinhSuaDon()) return;
    selectedCustomerId = id;
    const selected = document.getElementById('khachDaChon');
    selected.removeAttribute('data-i18n');
    selected.innerText = `${ten} (${sdt})`;
    document.getElementById('khachChuaChon').style.display = 'none';
    document.getElementById('khachBoChon').style.display = 'block';
}

async function timKhachPOS() {
    if (dangKhoaChinhSuaDon()) return;
    const q = document.getElementById('posCustSearch').value.trim();
    if (!q) return;
    try {
        const list = await apiCall(`/customers/${currentShopId}?q=${encodeURIComponent(q)}`);
        const box = document.getElementById('posCustResults');
        if (!list.length) {
            box.innerHTML = `<div style="color:#94A3B8; font-size:0.8rem;">${dichHtml('pos.customer.not_found')}</div>`;
            return;
        }
        box.innerHTML = '';
        list.slice(0, 5).forEach(customer => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'btn-outline';
            button.style.cssText = 'width:100%; text-align:left; padding:0.35rem 0.5rem; margin-bottom:0.25rem; font-size:0.85rem;';
            button.textContent = `${customer.name} — ${customer.phone}`;
            button.addEventListener('click', () => {
                chonKhach(customer.id, customer.name, customer.phone);
            });
            box.appendChild(button);
        });
    } catch (e) { showToast(e.message); }
}

function hienFormKhachMoi() {
    if (dangKhoaChinhSuaDon()) return;
    const f = document.getElementById('posCustNewForm');
    f.style.display = f.style.display === 'none' ? 'block' : 'none';
    if (f.style.display === 'block') {
        const q = document.getElementById('posCustSearch').value.trim();
        // Nếu người dùng gõ số vào ô tìm, đoán đó là SĐT cho khách mới.
        if (/^\d+$/.test(q)) document.getElementById('posCustNewPhone').value = q;
    }
}

async function taoKhachPOS() {
    if (dangKhoaChinhSuaDon()) return;
    const name = document.getElementById('posCustNewName').value.trim();
    const phone = document.getElementById('posCustNewPhone').value.trim();
    if (!name) return showToast(dich('pos.customer.name_required'));
    if (!phone) return showToast(dich('pos.customer.phone_required'));
    try {
        const kh = await apiCall(`/customers/${currentShopId}`, 'POST', { name, phone });
        document.getElementById('posCustNewName').value = '';
        document.getElementById('posCustNewPhone').value = '';
        chonKhach(kh.id, kh.name, kh.phone);
        showToast(dich('pos.customer.created'));
    } catch (e) { showToast(e.message); }
}

// Cài đặt đọc tiền nằm ở tab Cài Đặt của trang Người bán, không ở đây: màn POS
// phải gọn cho người đứng quầy, mà cấu hình thì chỉ đặt một lần rồi thôi.

[
    ['cashTenderedInput', capNhatTienKhachDua],
    ['openingCashInput', null],
    ['movementAmountInput', capNhatMovementDraft],
    ['actualCashInput', capNhatChenhLechKetCa]
].forEach(([id, callback]) => {
    const input = document.getElementById(id);
    if (!input) return;
    input.addEventListener('input', () => {
        dinhDangONhapTien(input);
        if (callback) callback();
    });
});

document.getElementById('movementNote')?.addEventListener('input', capNhatMovementDraft);

document.querySelectorAll('.pos-modal').forEach(modal => {
    modal.addEventListener('click', event => {
        if (event.target === modal) dongModalCa(modal.id);
    });
});

document.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    const modalMo = [...document.querySelectorAll('.pos-modal')]
        .reverse()
        .find(modal => modal.style.display === 'flex');
    if (modalMo) dongModalCa(modalMo.id);
});

function capNhatNgonNguPOS() {
    // Chỉ vẽ lại từ state hiện có. Không gọi resetPOS(), không tạo request và
    // không thay operation_id/create_payload của các thao tác đang chờ retry.
    renderCategories();
    filterAndRenderProducts();
    updateUI();
    const shopPlaceholder = document.querySelector('#shopSelect option[value=""]');
    if (shopPlaceholder) shopPlaceholder.textContent = dich('pos.shop.select');
    // Thông báo lỗi API thuộc locale của request cũ. Khi đổi ngôn ngữ,
    // dùng lại hướng dẫn kết nối từ catalog hiện tại thay vì giữ câu cũ.
    capNhatThanhCa(
        shiftBarState,
        shiftBarState === 'error' ? '' : shiftBarMessage
    );
    chonLoaiThuChi(movementType, false);
    khoaFormMovement(Boolean(pendingMovementState?.submitted));

    const voucherMessage = document.getElementById('voucherMsg');
    if (voucherMessage) {
        // Lỗi API dạng text thuộc ngôn ngữ của request cũ; xóa khi đổi locale
        // thay vì giữ một câu sai ngôn ngữ trên màn hình.
        if (voucherMessageRaw) {
            voucherMessageRaw = '';
            voucherMessageKey = null;
        }
        voucherMessage.innerText = voucherMessageKey
            ? dich(voucherMessageKey)
            : voucherMessageRaw;
    }

    if (selectedCustomerId === null) {
        const selected = document.getElementById('khachDaChon');
        if (selected) selected.innerText = dich('pos.customer.walk_in');
    }

    document.querySelectorAll('[data-money-quick]').forEach(button => {
        button.innerText = dinhDangTien(Number(button.dataset.moneyQuick) || 0);
    });
    [
        'cashTenderedInput',
        'openingCashInput',
        'movementAmountInput',
        'actualCashInput'
    ].forEach(id => {
        const input = document.getElementById(id);
        if (input && /\d/.test(input.value)) {
            input.value = dinhDangSoPOS(docGiaTriTien(input.value));
        }
    });

    document.querySelectorAll('[data-processing-key]').forEach(button => {
        button.innerHTML = htmlNut(
            'ph-spinner-gap ph-spin',
            button.dataset.processingKey
        );
    });

    if (lastPaymentStatus && document.getElementById('paymentStatusBox')?.style.display !== 'none') {
        renderPaymentStatus(lastPaymentStatus);
    }
    if (pendingCheckoutState?.phase === 'transfer_pending') {
        document.getElementById('qrTotalTxt').innerText = dinhDangTien(
            pendingCheckoutState.server_total ?? total
        );
    }
    if (document.getElementById('closeShiftModal')?.style.display === 'flex') {
        document.getElementById('closeOpeningCash').innerText =
            dinhDangTien(activeShift?.opening_cash_amount || 0);
        document.getElementById('closeExpectedCash').innerText =
            Number.isFinite(Number(activeShift?.expected_cash_amount))
                ? dinhDangTien(activeShift.expected_cash_amount)
                : '—';
        capNhatChenhLechKetCa();
    }
}

document.addEventListener('fselling:localechange', capNhatNgonNguPOS);

capNhatThanhCa('loading');
setMethod(paymentMethod);
// Đồng bộ cả các giá trị tiền tĩnh ban đầu (0 ₫, nút tiền nhanh...) với
// ngôn ngữ đã lưu ngay lần mở trang, không cần chờ người dùng đổi locale.
capNhatNgonNguPOS();
loadShop();
