// POS dùng chung cho chủ shop (SELLER) và nhân viên (STAFF).
(function () {
    const role = localStorage.getItem('role');
    if(role !== 'SELLER' && role !== 'STAFF') window.location.href = '/';
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

const POS_CHECKOUT_STORAGE_PREFIX = 'fselling.pos.checkout.v2';
const POS_MOVEMENT_STORAGE_PREFIX = 'fselling.pos.movement.v1';

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
            showToast('Đã bỏ trạng thái đơn cũ vì bạn không còn truy cập được cửa hàng đó');
        } else if (coQuyenShopDangCho) {
            // Một đơn chưa rõ kết quả phải kéo tab về đúng shop của nó. Nếu giữ
            // shop mới từ localStorage, nút retry/hủy có thể thao tác nhầm quầy.
            currentShopId = pendingShopId;
            localStorage.setItem('currentShopId', currentShopId);
        }
        const sel = document.getElementById('shopSelect');
        sel.innerHTML = '<option value="">-- Chọn Cửa Hàng --</option>';
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
        showToast(e.message || 'Không tải được thông tin cửa hàng');
    }
}

async function changeShopPOS() {
    const val = document.getElementById('shopSelect').value;
    if(!val) return;
    const shopMoi = parseInt(val);
    if (checkoutOperationId || currentOrderId || pendingCashOrderId) {
        document.getElementById('shopSelect').value = String(currentShopId);
        return showToast('Hãy hoàn tất, thử lại hoặc hủy đơn hiện tại trước khi chuyển cửa hàng');
    }
    if (activeShift && shopMoi !== currentShopId) {
        document.getElementById('shopSelect').value = String(currentShopId);
        return showToast('Hãy kết ca hiện tại trước khi chuyển cửa hàng');
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
    container.innerHTML = `<button class="category-btn ${!currentCategoryId ? 'active' : ''}" onclick="filterByCategory(null)">Tất cả</button>`;
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
            <div class="product-stock" style="color: white;">Kho: ${p.stock}</div>
            <img src="${imgUrl}" onerror="this.src='https://via.placeholder.com/150x150?text=Error'" class="product-img">
            <div class="product-info">
                <div class="product-name" title="${escapeHtml(p.name)}">${escapeHtml(p.name)}</div>
                <div class="product-price">${p.price.toLocaleString()} ₫</div>
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
        showToast(`Không tìm thấy sản phẩm có mã "${ma}"`);
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
        showToast('Đơn đã tạo, hãy hoàn tất hoặc hủy đơn trước khi chỉnh sửa');
        return true;
    }
    if (checkoutOperationId) {
        showToast('Kết quả tạo đơn chưa rõ; hãy bấm thử tạo đơn lại');
        return true;
    }
    return false;
}

function addToCart(p) {
    try {
        if (dangKhoaChinhSuaDon()) return false;
        if(!cart) cart = [];
        if(p.stock <= 0) { showToast("Sản phẩm đã hết hàng!"); return false; }
        const existing = cart.find(i => i.product_id === p.id);
        if(existing) {
            if(existing.quantity >= p.stock) { showToast("Vượt quá số lượng tồn kho!"); return false; }
            existing.quantity++;
        }
        else cart.push({ product_id: p.id, product_name: p.name, price: p.price, quantity: 1, max_stock: p.stock });
        calcCart();
        return true;
    } catch (err) {
        console.error("Lỗi thêm vào giỏ:", err);
        showToast("Lỗi hệ thống khi thêm sản phẩm.");
        return false;
    }
}

function updateQty(index, delta) {
    if (dangKhoaChinhSuaDon()) return;
    const item = cart[index];
    if(item.quantity + delta > item.max_stock) return showToast("Vượt quá tồn kho!");
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
            headers: { 'Authorization': `Bearer ${getToken()}` },
            body: formData
        });
        const data = await res.json();
        if(!res.ok) {
            currentVoucher = null; discount = 0; total = subtotal;
            document.getElementById('voucherMsg').innerText = data.detail;
            document.getElementById('voucherMsg').style.color = '#EF4444';
        } else {
            currentVoucher = code;
            discount = data.discount_amount;
            total = data.new_total;
            document.getElementById('voucherMsg').innerText = "Áp dụng thành công!";
            document.getElementById('voucherMsg').style.color = 'var(--success)';
        }
        updateUI();
    } catch(e) { console.log(e); }
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
                    <div class="cart-donGia">${item.price.toLocaleString()} × ${item.quantity}</div>
                </div>
                <div class="cart-o-sl" style="display: flex; gap: 0.3rem; align-items: center; color: white;">
                    <button class="btn-qty" onclick="updateQty(${index}, -1)">-</button>
                    <span>${item.quantity}</span>
                    <button class="btn-qty" onclick="updateQty(${index}, 1)">+</button>
                </div>
                <div class="cart-thanhTien cart-o-tien">${thanhTien.toLocaleString()} ₫</div>
                <button class="btn-del cart-o-xoa" onclick="removeItem(${index})"><i class="ph ph-trash"></i></button>
            </div>
        `;
    });

    document.getElementById('txtSubtotal').innerText = subtotal.toLocaleString() + ' ₫';
    document.getElementById('txtDiscount').innerText = '- ' + discount.toLocaleString() + ' ₫';
    document.getElementById('txtTotal').innerText = total.toLocaleString() + ' ₫';
    renderCashQuickAmounts();
    capNhatTienKhachDua();
}

function setMethod(m) {
    if (currentOrderId || pendingCashOrderId) {
        return showToast('Đơn đã tạo; hãy thanh toán hoặc hủy trước khi đổi phương thức');
    }
    if (checkoutOperationId && !currentOrderId) {
        return showToast('Hãy thử tạo đơn lại trước khi đổi thanh toán');
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
    input.value = raw.replace(/\D/g, '') ? amount.toLocaleString('vi-VN') : '';
    return amount;
}

function datGiaTriTien(inputId, amount) {
    const input = document.getElementById(inputId);
    if (!input) return;
    input.value = Math.max(0, Math.round(Number(amount) || 0)).toLocaleString('vi-VN');
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
            ${index === 0 ? 'Đủ · ' : ''}${amount.toLocaleString('vi-VN')} ₫
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
        status.firstElementChild.innerText = 'Còn thiếu';
        output.innerText = dinhDangTien(Math.abs(change));
    } else {
        status.firstElementChild.innerText = 'Tiền thối';
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
        pendingText.innerText = `Đơn #${pendingCashOrderId} đã tạo nhưng chưa ghi nhận thanh toán.`;
    }
    const thieuTien = paymentMethod === 'cash' && cashTenderedAmount < total;
    const donQRDangCho = currentOrderId !== null && !pendingCashOrderId;
    button.disabled = checkoutBusy || !activeShift || cart.length === 0 || thieuTien || donQRDangCho;
    button.innerHTML = pendingCashOrderId
        ? '<i class="ph ph-arrow-clockwise"></i> Thử thu tiền lại'
        : (checkoutOperationId
            ? '<i class="ph ph-arrow-clockwise"></i> Thử tạo đơn lại'
            : '<i class="ph ph-check-circle"></i> Hoàn tất Đơn Hàng');
    if (!activeShift) button.title = 'Mở ca trước khi bán hàng';
    else if (cart.length === 0) button.title = 'Giỏ hàng đang trống';
    else if (thieuTien) button.title = 'Tiền khách đưa chưa đủ';
    else if (donQRDangCho) button.title = 'Đang chờ thanh toán đơn hiện tại';
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
            ? cashTenderedAmount.toLocaleString('vi-VN')
            : '';
    }
    if (selectedCustomerId !== null) {
        const selected = document.getElementById('khachDaChon');
        if (selected) selected.innerText = state.selected_customer_text || `Khách hàng #${selectedCustomerId}`;
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
        showToast(`Đã phục hồi đơn chuyển khoản #${currentOrderId}`);
    } else if (state.phase === 'cash_pending' && currentOrderId) {
        showToast(`Đã phục hồi đơn tiền mặt #${currentOrderId}; hãy thu tiền hoặc hủy đơn`);
    } else {
        showToast('Kết quả tạo đơn trước đó chưa rõ; bấm “Thử tạo đơn lại”');
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
        text.innerText = 'Đang kiểm tra ca làm việc...';
        meta.innerText = 'Trạng thái được tải trực tiếp từ máy chủ';
        openButton.style.display = 'none';
        movementButton.style.display = 'none';
        closeButton.style.display = 'none';
    } else if (state === 'open' && activeShift) {
        const nguoiMo = activeShift.opened_by_username || localStorage.getItem('username') || 'Nhân viên';
        text.innerText = `Ca #${activeShift.id} đang mở`;
        meta.innerText = `${nguoiMo} · từ ${dinhDangNgayGio(activeShift.opened_at)}`;
        openButton.style.display = 'none';
        movementButton.style.display = '';
        closeButton.style.display = '';
    } else if (state === 'error') {
        text.innerText = 'Chưa xác định được trạng thái ca';
        meta.innerText = message || 'Kiểm tra kết nối rồi tải lại trang';
        openButton.style.display = 'none';
        movementButton.style.display = 'none';
        closeButton.style.display = 'none';
    } else {
        text.innerText = 'Chưa mở ca';
        meta.innerText = 'Mở ca để bắt đầu bán và ghi nhận tiền mặt';
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
        if (hienLoi) showToast(e.message || 'Không tải được trạng thái ca');
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

function datNutDangXuLy(buttonId, dangXuLy, textDangXuLy = 'Đang xử lý...') {
    const button = document.getElementById(buttonId);
    if (!button) return;
    if (dangXuLy) {
        button.dataset.normalHtml = button.innerHTML;
        button.innerHTML = `<i class="ph ph-spinner-gap ph-spin"></i> ${textDangXuLy}`;
        button.disabled = true;
    } else {
        if (button.dataset.normalHtml) button.innerHTML = button.dataset.normalHtml;
        button.disabled = false;
    }
}

function moModalMoCa() {
    if (!currentShopId) return showToast('Vui lòng chọn cửa hàng');
    if (activeShift) return showToast('Bạn đang có một ca mở');
    document.getElementById('openingCashInput').value = '0';
    document.getElementById('openingShiftNote').value = '';
    hienModalCa('openShiftModal', 'openingCashInput');
}

async function moCa() {
    if (!currentShopId || activeShift) return;
    const openingCash = docGiaTriTien(document.getElementById('openingCashInput').value);
    const note = document.getElementById('openingShiftNote').value.trim();
    datNutDangXuLy('btnSubmitOpenShift', true, 'Đang mở ca...');
    try {
        activeShift = await apiCall(`/shifts/${currentShopId}/open`, 'POST', {
            opening_cash_amount: openingCash,
            note: note || null
        });
        dongModalCa('openShiftModal');
        capNhatThanhCa('open');
        showToast(`Đã mở ca #${activeShift.id}`);
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
        movementType === 'PAY_IN' ? 'Ví dụ: Nộp thêm tiền lẻ vào quầy' : 'Ví dụ: Chi mua túi đóng gói';
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
            ? '<i class="ph ph-arrow-clockwise"></i> Thử ghi lại đúng khoản này'
            : '<i class="ph ph-check-circle"></i> Ghi nhận';
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
    if (!activeShift) return showToast('Hãy mở ca trước khi ghi nhận thu / chi');
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
        Number(values?.amount) > 0 ? Number(values.amount).toLocaleString('vi-VN') : '';
    document.getElementById('movementNote').value = values?.note || '';
    chonLoaiThuChi(movementType, false);
    khoaFormMovement(Boolean(pendingMovementState.submitted));
    hienModalCa('cashMovementModal', 'movementAmountInput');
}

async function ghiNhanThuChi() {
    if (!activeShift) return showToast('Ca đã đóng hoặc không còn tồn tại');
    let state = pendingMovementState || docMovementDangDo(activeShift.id);
    let payload = state?.submitted ? state.payload : null;
    if (!payload) {
        const amountInput = document.getElementById('movementAmountInput');
        const amount = docGiaTriTien(amountInput.value);
        const note = document.getElementById('movementNote').value.trim();
        if (amount <= 0) {
            amountInput.focus();
            return showToast('Vui lòng nhập số tiền lớn hơn 0');
        }
        if (!note) {
            document.getElementById('movementNote').focus();
            return showToast('Vui lòng nhập lý do thu / chi');
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
    datNutDangXuLy('btnSubmitMovement', true, 'Đang ghi...');
    try {
        const res = await apiCall(`/shifts/${state.shift_id}/movements`, 'POST', payload);
        if (res?.shift) activeShift = res.shift;
        dongModalCa('cashMovementModal');
        capNhatThanhCa('open');
        showToast(`${payload.movement_type === 'PAY_IN' ? 'Đã thu' : 'Đã chi'} ${dinhDangTien(payload.amount)}`);
        xoaMovementDangDo(state);
    } catch (e) {
        if (laLoi4xx(e)) {
            // 4xx là kết quả xác định: server đã từ chối payload này. Xóa op cũ
            // để người dùng sửa và gửi một thao tác mới.
            xoaMovementDangDo(state);
            khoaFormMovement(false);
            showToast(`${e.message}. Hãy sửa thông tin rồi ghi nhận lại.`);
        } else {
            // Network/5xx: không biết server đã commit chưa, nên giữ nguyên state
            // và khóa form cho tới khi retry cùng payload trả về kết quả rõ ràng.
            pendingMovementState = state;
            luuMovementDangDo(state);
            showToast(`${e.message}. Bấm “Thử ghi lại đúng khoản này” khi có mạng.`);
        }
        await loadCurrentShift(false);
    } finally {
        datNutDangXuLy('btnSubmitMovement', false);
        khoaFormMovement(Boolean(pendingMovementState?.submitted));
    }
}

async function moModalKetCa() {
    if (!activeShift) return showToast('Không có ca đang mở');
    const movementDangDo = docMovementDangDo(activeShift.id);
    if (movementDangDo?.submitted) {
        return showToast('Hãy thử ghi lại khoản thu / chi đang chờ trước khi kết ca');
    }
    if (cart.length > 0 || currentOrderId) {
        return showToast('Hãy hoàn tất hoặc hủy đơn hiện tại trước khi kết ca');
    }
    await loadCurrentShift(false);
    if (!activeShift) return showToast('Ca không còn mở hoặc không tải được dữ liệu ca');

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
        box.innerText = coNhap ? 'Không có số tiền theo sổ để so sánh' : 'Nhập tiền thực đếm để xem chênh lệch';
        return;
    }
    const counted = docGiaTriTien(input.value);
    const variance = counted - expected;
    if (variance === 0) {
        box.className = 'shift-difference';
        box.innerText = 'Khớp tiền theo sổ';
    } else if (variance < 0) {
        box.className = 'shift-difference is-short';
        box.innerText = `Thiếu ${dinhDangTien(Math.abs(variance))}`;
    } else {
        box.className = 'shift-difference';
        box.innerText = `Thừa ${dinhDangTien(variance)}`;
    }
}

async function ketCa() {
    if (!activeShift) return showToast('Ca đã đóng hoặc không còn tồn tại');
    const input = document.getElementById('actualCashInput');
    if (!/\d/.test(input.value)) {
        input.focus();
        return showToast('Vui lòng nhập tiền thực đếm');
    }
    const counted = docGiaTriTien(input.value);
    const expected = Number(activeShift.expected_cash_amount);
    const noteEl = document.getElementById('closingShiftNote');
    const note = noteEl.value.trim();
    if (Number.isFinite(expected) && counted !== expected && !note) {
        noteEl.focus();
        return showToast('Vui lòng ghi chú nguyên nhân khi lệch tiền');
    }

    datNutDangXuLy('btnSubmitCloseShift', true, 'Đang kết ca...');
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
                ? 'Đã kết ca, tiền thực tế khớp sổ'
                : `Đã kết ca, ${variance < 0 ? 'thiếu' : 'thừa'} ${dinhDangTien(Math.abs(variance))}`
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
        'Tổng tiền trên server đã thay đổi',
        `Tổng vừa xác nhận: ${dinhDangTien(daXacNhan)}\n`
        + `Tổng chính xác: ${dinhDangTien(serverTotal)}\n`
        + `Khách đưa: ${dinhDangTien(tendered)}\n`
        + `${chenhlech >= 0 ? 'Tiền thối' : 'Còn thiếu'}: ${dinhDangTien(Math.abs(chenhlech))}\n\n`
        + 'Xác nhận lại tổng chính xác trước khi ghi nhận đã thu tiền.'
    );
    if (!dongY) {
        state.server_total_confirmed = false;
        luuCheckoutDangDo(state);
        showToast('Đơn đã được giữ lại; cần xác nhận tổng mới trước khi thu tiền');
        return false;
    }
    state.server_total_confirmed = true;
    luuCheckoutDangDo(state);
    return true;
}

async function hoanTatTienMatDangCho(state) {
    const idDon = Number(state.order_id);
    if (!idDon) throw new Error('Không có mã đơn tiền mặt để thanh toán');

    currentOrderId = idDon;
    pendingCashOrderId = idDon;
    total = Number(state.server_total ?? state.total ?? total) || 0;
    capNhatTienKhachDua();
    state.tendered_amount = cashTenderedAmount;
    luuCheckoutDangDo(state);

    if (!await xacNhanTongTienServer(state)) return false;
    if (cashTenderedAmount < total) {
        document.getElementById('cashTenderedInput')?.focus();
        showToast(`Khách còn thiếu ${dinhDangTien(total - cashTenderedAmount)}`);
        return false;
    }

    await apiCall(`/orders/${idDon}/pay`, 'POST', {
        tendered_amount: cashTenderedAmount
    });
    // Pay đã trả success (kể cả idempotent "đã PAID"): từ đây mới được xóa
    // state durable của tab.
    xoaCheckoutDangDo();
    pendingCashOrderId = null;
    showToast(`Thu tiền mặt thành công, thối ${dinhDangTien(cashTenderedAmount - total)}`);
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
        showToast('Tạo đơn thành công! Khách vui lòng quét mã.');
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
            showToast('Hãy mở ca trước khi thử tạo lại đơn');
            return moModalMoCa();
        }
        const state = pendingCheckoutState || docCheckoutDangDo();
        return thuTaoDonDangDo(state);
    }
    if (currentOrderId) return showToast('Đang có một đơn chờ thanh toán');
    if(cart.length === 0) return showToast('Giỏ hàng trống!');
    if(!activeShift) {
        showToast('Hãy mở ca trước khi bán hàng');
        return moModalMoCa();
    }
    capNhatTienKhachDua();
    if (paymentMethod === 'cash' && cashTenderedAmount < total) {
        document.getElementById('cashTenderedInput')?.focus();
        return showToast(`Khách còn thiếu ${dinhDangTien(total - cashTenderedAmount)}`);
    }

    // Xác nhận trước khi chốt. Tạo đơn là TRỪ TỒN KHO ngay, và với tiền mặt còn
    // thu tiền luôn - không có bước quay lại. Khi quét mã vạch, quét thừa một
    // món rất dễ xảy ra mà danh sách lại cuộn nên khó thấy, nên bắt buộc phải
    // có một lần đối chiếu tổng số món và tổng tiền bằng mắt.
    const soMon = cart.reduce((n, i) => n + i.quantity, 0);
    const tenPTTT = paymentMethod === 'cash' ? 'Tiền mặt' : 'Chuyển khoản (VietQR)';
    const dongTomTat = cart.map(i => `  ${i.product_name}  ${i.price.toLocaleString()} × ${i.quantity}`).join('\n');
    const tomTatTienMat = paymentMethod === 'cash'
        ? `\nKhách đưa: ${dinhDangTien(cashTenderedAmount)}\nTiền thối: ${dinhDangTien(cashTenderedAmount - total)}`
        : '';
    const dongY = await xacNhan(
        `Chốt đơn ${cart.length} mặt hàng (${soMon} món)?`,
        `${dongTomTat}\n\nTỔNG CẦN THU: ${total.toLocaleString()} đ\nThanh toán: ${tenPTTT}${tomTatTienMat}`
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
    if (!activeShift) return showToast('Ca đã đóng hoặc không còn tồn tại');
    const state = pendingCheckoutState || docCheckoutDangDo();
    if (!state || state.phase !== 'cash_pending') {
        return showToast('Không tìm thấy trạng thái đơn tiền mặt để thử lại');
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
            showToast(`${e.message}. Đơn không còn tồn tại, vui lòng tạo lại.`);
        } else {
            // Các 4xx khác vẫn có thể là đơn PENDING hợp lệ (ca đóng, chưa đủ
            // tiền...). Giữ order_id để người dùng thu hoặc hủy đúng đơn đó.
            luuCheckoutDangDo(state);
            showToast(
                laLoi4xx(e)
                    ? e.message
                    : `${e.message}. Có thể bấm “Thử thu tiền lại”.`
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
        `Hủy đơn #${idDon}?`,
        'Hàng trong đơn sẽ được trả lại kho.'
    );
    if (!dongY) return;
    try {
        const res = await apiCall(`/orders/${idDon}/cancel`, 'POST');
        stopPaymentPolling();
        if(res.unrestored_items > 0) {
            showToast(`Đã hủy đơn. Có ${res.unrestored_items} dòng không hoàn kho được, vui lòng kiểm tra lại tồn kho.`);
        } else {
            showToast("Đã hủy đơn và hoàn lại hàng vào kho.");
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
            return showToast(`${e.message}. Đơn không còn tồn tại.`);
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
                showToast(`Đã thanh toán. Khách chuyển thừa ${dinhDangTien(statusRes.refund_due_amount)} — cần hoàn lại.`);
            } else {
                DocTien.thongBaoDaNhan(
                    idDon,
                    statusRes.received_amount || statusRes.total_amount
                );
                showToast('Thanh toán chuyển khoản thành công!');
            }
            await hienHoaDon(idDon);
        } else if(statusRes.status === 'CANCELLED') {
            stopPaymentPolling();
            showToast('Đơn đã bị hủy, hàng đã được hoàn về kho.');
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
                    showToast(`Chưa đủ tiền: còn thiếu ${dinhDangTien(statusRes.remaining_amount)}. Chưa xuất hóa đơn.`);
                }
            } else {
                stopPaymentPolling();
                showToast('Khoản tiền này cần đối soát riêng. Không giao hàng và không xuất hóa đơn.');
            }
        }
    } catch (err) {
        console.error('Polling lỗi:', err);
    }
}

function dinhDangTien(value) {
    return `${Math.round(Number(value) || 0).toLocaleString('vi-VN')} ₫`;
}

function renderPaymentStatus(statusRes) {
    const box = document.getElementById('paymentStatusBox');
    const title = document.getElementById('paymentStatusTitle');
    const cashButton = document.getElementById('btnCashTopup');
    const cancelButton = document.getElementById('btnCancelOrder');
    if(!box || !title || !cashButton) return;

    box.style.display = 'block';
    document.getElementById('paymentReceived').innerText = dinhDangTien(statusRes.received_amount);
    document.getElementById('paymentRemaining').innerText = dinhDangTien(statusRes.remaining_amount);

    if(statusRes.reconciliation_reason === 'UNDERPAID') {
        title.innerText = 'Đã nhận thiếu tiền — chưa xuất hóa đơn';
        cashButton.style.display = 'block';
        cashButton.innerHTML = `<i class="ph ph-money"></i> Thu bù ${dinhDangTien(statusRes.remaining_amount)} bằng tiền mặt`;
    } else if(statusRes.reconciliation_reason === 'LATE_PAYMENT') {
        title.innerText = `Tiền về sau khi đơn đã hủy — cần hoàn ${dinhDangTien(statusRes.refund_due_amount)}`;
        cashButton.style.display = 'none';
    } else {
        title.innerText = 'Đơn cần kiểm tra đối soát';
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
            return showToast('Đơn không còn ở trạng thái thiếu tiền. Đang tải lại...');
        }
        const remaining = Number(statusRes.remaining_amount || 0);
        const dongY = await xacNhan(
            `Thu bù ${dinhDangTien(remaining)} bằng tiền mặt?`,
            `Đơn #${idDon} đã nhận ${dinhDangTien(statusRes.received_amount)} qua ngân hàng.\n\nSau khi xác nhận, hóa đơn sẽ được xuất ngay.`
        );
        if(!dongY) return;
        const result = await apiCall(
            `/orders/${idDon}/cash-topup`,
            'POST',
            { amount: remaining, note: 'Thu bù tại quầy POS' }
        );
        if(result.status === 'PAID') {
            stopPaymentPolling();
            showToast('Đã thu đủ phần thiếu bằng tiền mặt.');
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
        return showToast(`Đã thanh toán đơn #${orderId}, nhưng không tải được hóa đơn: ${e.message}`);
    }
    resetPOS();
    veHoaDon(d);
    document.getElementById('hoaDonSection').style.display = 'block';
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
                <span style="color:#64748B; font-size:0.8rem;">${(i.price || 0).toLocaleString()} × ${i.quantity}</span></td>
            <td style="padding:0.25rem 0; text-align:right; white-space:nowrap; font-weight:600;">${(i.line_total || 0).toLocaleString()} ₫</td>
        </tr>`).join('');

    let tongKet = `<div style="display:flex; justify-content:space-between;"><span>Tạm tính</span><span>${(d.subtotal || 0).toLocaleString()} ₫</span></div>`;
    if (d.discount_amount > 0) {
        const ma = d.voucher_code ? ` (${escapeHtml(d.voucher_code)})` : '';
        tongKet += `<div style="display:flex; justify-content:space-between; color:#B45309;"><span>Giảm giá${ma}</span><span>- ${d.discount_amount.toLocaleString()} ₫</span></div>`;
    }
    tongKet += `<div style="display:flex; justify-content:space-between; font-size:1.15rem; font-weight:700; margin-top:0.4rem; padding-top:0.4rem; border-top:2px solid #0F172A;"><span>TỔNG CỘNG</span><span>${(d.total_amount || 0).toLocaleString()} ₫</span></div>`;
    if (coChuyenKhoan && coTienMat) {
        tongKet += `<div style="display:flex; justify-content:space-between; margin-top:0.35rem;"><span>Qua ngân hàng</span><span>${dinhDangTien(d.bank_paid_amount)}</span></div>`;
        tongKet += `<div style="display:flex; justify-content:space-between;"><span>Bù tiền mặt</span><span>${dinhDangTien(d.cash_paid_amount)}</span></div>`;
    }
    if (coTienKhachDua) {
        tongKet += `<div style="display:flex; justify-content:space-between; margin-top:0.35rem;"><span>Khách đưa</span><span>${dinhDangTien(d.cash_tendered_amount)}</span></div>`;
        tongKet += `<div style="display:flex; justify-content:space-between; color:#047857; font-weight:700;"><span>Tiền thối</span><span>${dinhDangTien(d.cash_change_amount || 0)}</span></div>`;
    }
    if (d.refund_pending) {
        tongKet += `<div style="display:flex; justify-content:space-between; color:#B91C1C; font-weight:700; margin-top:0.35rem;"><span>Thực nhận</span><span>${dinhDangTien(d.received_amount)}</span></div>`;
        tongKet += `<div style="display:flex; justify-content:space-between; color:#B91C1C; font-weight:700;"><span>CẦN HOÀN KHÁCH</span><span>${dinhDangTien(d.refund_due_amount)}</span></div>`;
    }

    const warning = document.getElementById('hoaDonCanhBao');
    if (warning) {
        if (d.refund_pending) {
            warning.style.display = 'block';
            warning.innerText = `ĐÃ XUẤT HÓA ĐƠN — CẦN HOÀN KHÁCH ${dinhDangTien(d.refund_due_amount)}`;
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
            <div><b>Thời gian:</b> ${dinhDangNgayGio(d.created_at)}</div>
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
    boChonKhach();  // trả về khách vãng lai cho đơn tiếp theo
    calcCart();
    loadProducts(); // refresh stock
}

// ===== C2d: gắn khách hàng vào đơn ở POS =====
function boChonKhach() {
    if (dangKhoaChinhSuaDon()) return;
    selectedCustomerId = null;
    const el = id => document.getElementById(id);
    if (el('khachDaChon')) el('khachDaChon').innerText = 'Khách vãng lai';
    if (el('khachChuaChon')) el('khachChuaChon').style.display = 'block';
    if (el('khachBoChon')) el('khachBoChon').style.display = 'none';
    if (el('posCustResults')) el('posCustResults').innerHTML = '';
    if (el('posCustSearch')) el('posCustSearch').value = '';
    if (el('posCustNewForm')) el('posCustNewForm').style.display = 'none';
}

function chonKhach(id, ten, sdt) {
    if (dangKhoaChinhSuaDon()) return;
    selectedCustomerId = id;
    document.getElementById('khachDaChon').innerText = `${ten} (${sdt})`;
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
            box.innerHTML = `<div style="color:#94A3B8; font-size:0.8rem;">Không tìm thấy. Bấm <i class="ph ph-user-plus"></i> để thêm mới.</div>`;
            return;
        }
        box.innerHTML = list.slice(0, 5).map(c =>
            `<button class="btn-outline" style="width:100%; text-align:left; padding:0.35rem 0.5rem; margin-bottom:0.25rem; font-size:0.85rem;" onclick="chonKhach(${c.id}, '${escapeHtml(c.name)}', '${escapeHtml(c.phone)}')">${escapeHtml(c.name)} — ${escapeHtml(c.phone)}</button>`
        ).join('');
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
    if (!name) return showToast('Vui lòng nhập tên khách');
    if (!phone) return showToast('Vui lòng nhập số điện thoại');
    try {
        const kh = await apiCall(`/customers/${currentShopId}`, 'POST', { name, phone });
        document.getElementById('posCustNewName').value = '';
        document.getElementById('posCustNewPhone').value = '';
        chonKhach(kh.id, kh.name, kh.phone);
        showToast('Đã thêm và chọn khách');
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

capNhatThanhCa('loading');
setMethod(paymentMethod);
loadShop();
