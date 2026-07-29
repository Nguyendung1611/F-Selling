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
        loadCategories();
        loadProducts();
    } catch(e) {}
}

function changeShopPOS() {
    const val = document.getElementById('shopSelect').value;
    if(!val) return;
    currentShopId = parseInt(val);
    localStorage.setItem('currentShopId', currentShopId);
    resetPOS();
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
    const item = cart[index];
    if(item.quantity + delta > item.max_stock) return showToast("Vượt quá tồn kho!");
    if(item.quantity + delta <= 0) cart.splice(index, 1);
    else item.quantity += delta;
    calcCart();
}

function removeItem(index) {
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
        container.innerHTML += `
            <div class="cart-item">
                <div style="font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: #F8FAFC;" title="${escapeHtml(item.product_name)}">${escapeHtml(item.product_name)}</div>
                <div style="color: var(--success);">${item.price.toLocaleString()}</div>
                <div style="display: flex; gap: 0.3rem; align-items: center; color: white;">
                    <button class="btn-qty" onclick="updateQty(${index}, -1)">-</button>
                    <span>${item.quantity}</span>
                    <button class="btn-qty" onclick="updateQty(${index}, 1)">+</button>
                </div>
                <button class="btn-del" onclick="removeItem(${index})"><i class="ph ph-trash"></i></button>
            </div>
        `;
    });

    document.getElementById('txtSubtotal').innerText = subtotal.toLocaleString() + ' ₫';
    document.getElementById('txtDiscount').innerText = '- ' + discount.toLocaleString() + ' ₫';
    document.getElementById('txtTotal').innerText = total.toLocaleString() + ' ₫';
}

function setMethod(m) {
    paymentMethod = m;
    document.getElementById('btnMethodQR').classList.remove('active');
    document.getElementById('btnMethodCash').classList.remove('active');
    if(m==='transfer') document.getElementById('btnMethodQR').classList.add('active');
    else document.getElementById('btnMethodCash').classList.add('active');
    
    // Hide QR section if switching to cash
    if(m === 'cash') document.getElementById('qrSection').style.display = 'none';
}

let paymentPollingInterval = null;

async function checkout() {
    if(cart.length === 0) return showToast("Giỏ hàng trống!");
    try {
        const body = {
            // Gửi kèm product_name để hóa đơn/log vẫn đọc được nếu cần đối chiếu,
            // nhưng server định danh sản phẩm bằng product_id.
            items: cart.map(i => ({product_id: i.product_id, product_name: i.product_name, price: i.price, quantity: i.quantity})),
            voucher_code: currentVoucher,
            payment_method: paymentMethod
        };
        if(selectedCustomerId !== null) body.customer_id = selectedCustomerId;
        const res = await apiCall(`/orders/${currentShopId}`, 'POST', body);
        currentOrderId = res.order_id;
        
        if(paymentMethod === 'transfer') {
            document.getElementById('qrImage').src = res.qr_url;
            document.getElementById('qrTotalTxt').innerText = res.total.toLocaleString() + ' ₫';
            document.getElementById('qrSection').style.display = 'block';
            showToast("Tạo đơn thành công! Khách vui lòng quét mã.");
            startPaymentPolling();
        } else {
            // Tiền mặt -> auto pay for simplicity or just show success
            await apiCall(`/orders/${currentOrderId}/pay`, 'POST');
            showToast("Thu tiền mặt thành công!");
            resetPOS();
        }
    } catch (e) { showToast(e.message); }
}

async function confirmPayment() {
    if(!currentOrderId) return;
    try {
        await apiCall(`/orders/${currentOrderId}/pay`, 'POST');
        stopPaymentPolling();
        showToast("Đã xác nhận tiền vào tài khoản!");
        resetPOS();
    } catch (e) { showToast(e.message); }
}

async function cancelOrder() {
    if(!currentOrderId) return;
    if(!confirm(`Hủy đơn #${currentOrderId}? Hàng trong đơn sẽ được trả lại kho.`)) return;
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
    paymentPollingInterval = setInterval(async () => {
        if(!currentOrderId) return stopPaymentPolling();
        try {
            const statusRes = await apiCall(`/orders/${currentOrderId}`);
            if(statusRes.status === 'PAID') {
                stopPaymentPolling();
                showToast('Thanh toán chuyển khoản thành công!');
                resetPOS();
            } else if(statusRes.status === 'CANCELLED') {
                // Đơn có thể bị hủy tự động do quá hạn thanh toán
                stopPaymentPolling();
                showToast('Đơn đã bị hủy, hàng đã được hoàn về kho.');
                resetPOS();
            } else if(statusRes.status === 'UNRECONCILED') {
                stopPaymentPolling();
                showToast('Tiền về sau khi đơn đã hủy. Vui lòng đối soát trước khi giao hàng!');
                resetPOS();
            }
        } catch (err) {
            console.error('Polling lỗi:', err);
        }
    }, 5000);
}

function stopPaymentPolling() {
    if(paymentPollingInterval) {
        clearInterval(paymentPollingInterval);
        paymentPollingInterval = null;
    }
}

function resetPOS() {
    stopPaymentPolling();
    cart = [];
    currentVoucher = null;
    document.getElementById('voucherInput').value = '';
    document.getElementById('voucherMsg').innerText = '';
    document.getElementById('qrSection').style.display = 'none';
    currentOrderId = null;
    boChonKhach();  // trả về khách vãng lai cho đơn tiếp theo
    calcCart();
    loadProducts(); // refresh stock
}

// ===== C2d: gắn khách hàng vào đơn ở POS =====
function boChonKhach() {
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

loadShop();
loadProducts();