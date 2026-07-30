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

async function loadShop() {
    try {
        const res = await apiCall('/shops');
        allShops = res.filter(s => s.is_active !== false); // fallback if undefined
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
    } catch(e) {
        showToast(e.message || 'Không tải được thông tin cửa hàng');
    }
}

async function changeShopPOS() {
    const val = document.getElementById('shopSelect').value;
    if(!val) return;
    const shopMoi = parseInt(val);
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
function addToCart(p) {
    try {
        if (checkoutOperationId && !currentOrderId) {
            showToast('Kết quả tạo đơn chưa rõ; hãy bấm thử tạo đơn lại');
            return false;
        }
        if (pendingCashOrderId) {
            showToast('Hãy hoàn tất thanh toán tiền mặt của đơn hiện tại');
            return false;
        }
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
    if (checkoutOperationId && !currentOrderId) return showToast('Hãy thử tạo đơn lại trước khi sửa giỏ');
    if (pendingCashOrderId) return showToast('Đơn đã tạo, hãy hoàn tất thanh toán trước');
    const item = cart[index];
    if(item.quantity + delta > item.max_stock) return showToast("Vượt quá tồn kho!");
    if(item.quantity + delta <= 0) cart.splice(index, 1);
    else item.quantity += delta;
    calcCart();
}

function removeItem(index) {
    if (checkoutOperationId && !currentOrderId) return showToast('Hãy thử tạo đơn lại trước khi sửa giỏ');
    if (pendingCashOrderId) return showToast('Đơn đã tạo, hãy hoàn tất thanh toán trước');
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
    if (checkoutOperationId && !currentOrderId) return showToast('Hãy thử tạo đơn lại trước khi đổi voucher');
    if (pendingCashOrderId) return showToast('Đơn đã tạo, không thể đổi voucher lúc này');
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
    if (checkoutOperationId && !currentOrderId) {
        return showToast('Hãy thử tạo đơn lại trước khi đổi thanh toán');
    }
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
        setTimeout(() => document.getElementById('cashTenderedInput')?.focus(), 0);
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

function chonLoaiThuChi(type) {
    movementType = type === 'PAY_OUT' ? 'PAY_OUT' : 'PAY_IN';
    document.getElementById('btnMovementIn').classList.toggle('active', movementType === 'PAY_IN');
    document.getElementById('btnMovementOut').classList.toggle('active', movementType === 'PAY_OUT');
    document.getElementById('movementNote').placeholder =
        movementType === 'PAY_IN' ? 'Ví dụ: Nộp thêm tiền lẻ vào quầy' : 'Ví dụ: Chi mua túi đóng gói';
}

function moModalThuChi() {
    if (!activeShift) return showToast('Hãy mở ca trước khi ghi nhận thu / chi');
    movementOperationId = taoOperationId();
    movementType = 'PAY_IN';
    document.getElementById('movementAmountInput').value = '';
    document.getElementById('movementNote').value = '';
    chonLoaiThuChi('PAY_IN');
    hienModalCa('cashMovementModal', 'movementAmountInput');
}

async function ghiNhanThuChi() {
    if (!activeShift) return showToast('Ca đã đóng hoặc không còn tồn tại');
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
    // Giữ operation_id khi request lỗi để nút retry không thể ghi trùng.
    if (!movementOperationId) movementOperationId = taoOperationId();
    datNutDangXuLy('btnSubmitMovement', true, 'Đang ghi...');
    try {
        const res = await apiCall(`/shifts/${activeShift.id}/movements`, 'POST', {
            movement_type: movementType,
            amount,
            note,
            operation_id: movementOperationId
        });
        if (res?.shift) activeShift = res.shift;
        dongModalCa('cashMovementModal');
        capNhatThanhCa('open');
        showToast(`${movementType === 'PAY_IN' ? 'Đã thu' : 'Đã chi'} ${dinhDangTien(amount)}`);
        movementOperationId = null;
    } catch (e) {
        showToast(e.message);
        await loadCurrentShift(false);
    } finally {
        datNutDangXuLy('btnSubmitMovement', false);
    }
}

async function moModalKetCa() {
    if (!activeShift) return showToast('Không có ca đang mở');
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

async function checkout() {
    if (checkoutBusy) return;
    if(cart.length === 0) return showToast("Giỏ hàng trống!");
    if(!activeShift) {
        showToast('Hãy mở ca trước khi bán hàng');
        return moModalMoCa();
    }
    if (pendingCashOrderId) return thuTienMatDonDangCho();
    if (currentOrderId) return showToast('Đang có một đơn chờ thanh toán');
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

    checkoutBusy = true;
    capNhatNutCheckout();
    try {
        const body = {
            // Gửi kèm product_name để hóa đơn/log vẫn đọc được nếu cần đối chiếu,
            // nhưng server định danh sản phẩm bằng product_id.
            items: cart.map(i => ({product_id: i.product_id, product_name: i.product_name, price: i.price, quantity: i.quantity})),
            voucher_code: currentVoucher,
            payment_method: paymentMethod
        };
        if (!checkoutOperationId) checkoutOperationId = taoOperationId();
        body.operation_id = checkoutOperationId;
        if(selectedCustomerId !== null) body.customer_id = selectedCustomerId;
        const res = await apiCall(`/orders/${currentShopId}`, 'POST', body);
        checkoutOperationId = null;
        currentOrderId = res.order_id;
        
        if(paymentMethod === 'transfer') {
            document.getElementById('qrImage').src = res.qr_url;
            document.getElementById('qrTotalTxt').innerText = res.total.toLocaleString() + ' ₫';
            document.getElementById('qrSection').style.display = 'block';
            showToast("Tạo đơn thành công! Khách vui lòng quét mã.");
            // Nạp trước đúng các từ của số tiền này. Khi webhook về chỉ còn
            // phát ngay, không chen khoảng chờ tải file giữa câu.
            DocTien.chuanBiSoTien(res.total);
            startPaymentPolling();
        } else {
            const idDon = currentOrderId;
            pendingCashOrderId = idDon;
            if (Number.isFinite(Number(res.total))) {
                // Server mới là nguồn đúng về giá/voucher. Nếu tổng có thay đổi
                // do dữ liệu vừa được cập nhật, dùng số server khi kiểm tiền.
                total = Number(res.total);
                document.getElementById('txtTotal').innerText = dinhDangTien(total);
                renderCashQuickAmounts();
                capNhatTienKhachDua();
            }
            if (cashTenderedAmount < total) {
                throw new Error(`Tổng trên server là ${dinhDangTien(total)}; khách còn thiếu ${dinhDangTien(total - cashTenderedAmount)}`);
            }
            await apiCall(`/orders/${idDon}/pay`, 'POST', {
                tendered_amount: cashTenderedAmount
            });
            pendingCashOrderId = null;
            showToast(`Thu tiền mặt thành công, thối ${dinhDangTien(cashTenderedAmount - total)}`);
            await hienHoaDon(idDon);
        }
    } catch (e) {
        // 4xx xác nhận server đã từ chối và không tạo đơn; cho phép sửa giỏ.
        // Lỗi mạng/5xx giữ operation_id để lần bấm sau nhận lại đúng đơn nếu
        // server đã commit nhưng response bị mất.
        if (!currentOrderId && e.status >= 400 && e.status < 500) {
            checkoutOperationId = null;
        }
        showToast(e.message);
    } finally {
        checkoutBusy = false;
        capNhatNutCheckout();
    }
}

async function thuTienMatDonDangCho() {
    if (!pendingCashOrderId || checkoutBusy) return;
    if (!activeShift) return showToast('Ca đã đóng hoặc không còn tồn tại');
    capNhatTienKhachDua();
    if (cashTenderedAmount < total) {
        document.getElementById('cashTenderedInput')?.focus();
        return showToast(`Khách còn thiếu ${dinhDangTien(total - cashTenderedAmount)}`);
    }
    checkoutBusy = true;
    capNhatNutCheckout();
    const idDon = pendingCashOrderId;
    try {
        await apiCall(`/orders/${idDon}/pay`, 'POST', {
            tendered_amount: cashTenderedAmount
        });
        pendingCashOrderId = null;
        showToast(`Thu tiền mặt thành công, thối ${dinhDangTien(cashTenderedAmount - total)}`);
        await hienHoaDon(idDon);
    } catch (e) {
        showToast(`${e.message}. Có thể bấm “Thử thu tiền lại”.`);
    } finally {
        checkoutBusy = false;
        capNhatNutCheckout();
    }
}

async function cancelOrder() {
    if(!currentOrderId) return;
    const dongY = await xacNhan(
        `Hủy đơn #${currentOrderId}?`,
        'Hàng trong đơn sẽ được trả lại kho.'
    );
    if (!dongY) return;
    try {
        const res = await apiCall(`/orders/${currentOrderId}/cancel`, 'POST');
        stopPaymentPolling();
        if(res.unrestored_items > 0) {
            showToast(`Đã hủy đơn. Có ${res.unrestored_items} dòng không hoàn kho được, vui lòng kiểm tra lại tồn kho.`);
        } else {
            showToast("Đã hủy đơn và hoàn lại hàng vào kho.");
        }
        resetPOS();
    } catch (e) { showToast(e.message); }
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
    if (checkoutOperationId && !currentOrderId) {
        return showToast('Hãy thử tạo đơn lại trước khi đổi khách hàng');
    }
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
    if (checkoutOperationId && !currentOrderId) {
        return showToast('Hãy thử tạo đơn lại trước khi đổi khách hàng');
    }
    selectedCustomerId = id;
    document.getElementById('khachDaChon').innerText = `${ten} (${sdt})`;
    document.getElementById('khachChuaChon').style.display = 'none';
    document.getElementById('khachBoChon').style.display = 'block';
}

async function timKhachPOS() {
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
    const f = document.getElementById('posCustNewForm');
    f.style.display = f.style.display === 'none' ? 'block' : 'none';
    if (f.style.display === 'block') {
        const q = document.getElementById('posCustSearch').value.trim();
        // Nếu người dùng gõ số vào ô tìm, đoán đó là SĐT cho khách mới.
        if (/^\d+$/.test(q)) document.getElementById('posCustNewPhone').value = q;
    }
}

async function taoKhachPOS() {
    if (checkoutOperationId && !currentOrderId) {
        return showToast('Hãy thử tạo đơn lại trước khi đổi khách hàng');
    }
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
    ['movementAmountInput', null],
    ['actualCashInput', capNhatChenhLechKetCa]
].forEach(([id, callback]) => {
    const input = document.getElementById(id);
    if (!input) return;
    input.addEventListener('input', () => {
        dinhDangONhapTien(input);
        if (callback) callback();
    });
});

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
